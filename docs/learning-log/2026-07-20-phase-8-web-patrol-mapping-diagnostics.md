# 학습 일지: Phase 8 웹 수동 조종·순찰·매핑·원인 분석

날짜: 2026-07-20

단계: Phase 8

진행 상태: 로봇 없는 구현·검증 진행, 실차 최종 검증 대기

## 오늘의 목표

실제 로봇 위치와 웹 방향의 불일치를 바로잡은 안전 브랜치 위에서 목적지 최종 yaw, 부드러운
저속 주행, 웹 deadman 수동 조종, 웨이포인트 순찰, 새 지도 작성, ROS 2 로그 원인 분석을 하나의
운영 흐름으로 확장한다. TB1을 움직일 수 없는 동안 가능한 구현과 검증은 모두 끝내고 실제
이동은 작업자가 로봇 옆에 있을 때만 한다.

## 구현한 내용

### 목적지 yaw와 속도 평활화

- 목적지와 웨이포인트는 클릭만으로 확정하지 않고 드래그 또는 숫자 yaw 입력을 요구했다.
- 화면 벡터를 OccupancyGrid origin 회전이 반영된 map 좌표로 바꾼 뒤 yaw를 계산했다.
- Nav2 controller 10 Hz 뒤에 20 Hz `nav2_velocity_smoother`를 배치했다.
- 최대 속도 `0.05 m/s`, `0.3 rad/s`와 watchdog 단일 Publisher 경계를 유지했다.

### 수동 조종

- `ManualCommand.srv`와 TB1 로컬 `manual_control_node`를 추가했다.
- 브라우저는 100 ms마다 lease 성격의 동일 session 명령을 갱신한다.
- 로봇 로컬은 0.35초 동안 갱신이 없으면 0을 발행하고 arbiter를 IDLE로 전환한다.
- navigation과 manual 모두 arbiter와 watchdog을 통과하며 Zenoh에 velocity topic을 노출하지 않았다.

### 순찰

- SQLite에 순찰과 순서가 있는 웨이포인트를 저장했다.
- 각 지점을 기존 `NavigateRobot` action으로 순차 실행해 lease·feedback·cancel을 재사용했다.
- 한 지점 실패, 명시적 취소, 프로세스 재시작에서 다음 지점을 자동 실행하지 않게 했다.

### 운영 프로필과 지도 저장

- navigation/mapping launch 밖에 상시 `profile_manager_node`를 두었다.
- `IDLE`, `MAPPING`, `NAVIGATION` 프로필을 systemd user unit으로 상호 배타적으로 전환한다.
- 프로필 전환과 지도 저장 전에 Gateway가 e-stop을 확인한다.
- 지도와 pose graph를 TB1 로컬 운영 데이터 경로에 함께 저장하도록 했다.

### 로그 MLOps 원인 분석

- 기존 Production 모델의 이상 상태에 규칙 기반 원인 후보를 연결했다.
- localization/TF, collision, progress, lease, sensor, restart, resource, safety를 분류한다.
- API와 웹에 confidence, 원본 증거, 권장 조치를 표시한다.
- 분석 계층은 움직임 명령, e-stop 해제, 자동 재시도를 하지 않는다.

## 검증 결과

- JavaScript 좌표·origin yaw·viewport·robot pose 테스트: 15 passed
- systemd unit 정적 검증: `SYSTEMD_UNIT_VALIDATION_OK restart_units=8 network_gate=1`
- 변경 shell script ShellCheck: 실패 0
- Python compile, JavaScript syntax, `git diff --check`: 실패 0
- 1280×720 웹 시각 검증: body 세로·가로 overflow 없음, 목적지 yaw 표기와 waypoint 모드 확인
- 전체 Humble colcon: 444 tests, 0 errors, 0 failures, 0 skipped
- operations·실제 Nav2·분리 domain Zenoh의 robotless smoke 3종: 모두 통과
- 실제 Nav2 smoke 최종 출력: `/motion/navigation/cmd_vel`은 smoother 1개,
  `/cmd_vel`은 watchdog 1개, 최대 `0.04737 m/s`, `0.16154 rad/s`, 최종 0

Windows의 WSL 마운트에서는 systemd-analyze가 unit 파일을 executable/world-writable로 보고하는
경고가 발생했다. 이는 NTFS drvfs 권한 표현 때문이며 unit 내용 검증 자체는 성공했다. 실제
TB1에 배포된 파일은 deploy script가 정상 Linux 권한으로 설치한다.

## 문제와 해결

### 화면 방향과 실제 전방이 반대로 보였던 문제

TB1 LDS-02의 원본 angle 0과 실제 차체 전방이 반대인 장착 특성을 앞선 안전 변경에서
`/scan_normalized`와 overlay에 같은 π 보정으로 통일했다. Phase 8에서는 목표 화살표를
screen angle이 아니라 map 좌표 벡터로 계산해 그 기준을 유지했다.

### 브라우저 종료 시 정지 요청 유실 가능성

처음에는 pointer release에서 DELETE를 보내는 것만으로는 부족했다. 탭 강제 종료나 네트워크
단절에서는 요청이 도착하지 않을 수 있으므로 TB1 로컬 authorization timeout을 최종 fail-safe로
두었다.

### 프로필 전환 서비스의 자기 종료 가능성

전환 서비스를 navigation launch 안에 넣으면 그 launch를 중지하는 순간 응답과 다음 launch
시작이 끊길 수 있다. 별도 always-on systemd service로 분리해 해결했다.

### 순찰 자동 재개의 위험

Gateway 재시작 후 ACTIVE 순찰을 그대로 이어가면 사용자가 예상하지 못한 출발이 된다. durable
정의는 보존하지만 실행 상태는 실패로 정리하고 명시적 재실행만 허용했다.

### 기존 관제 runtime을 보존하면서 Phase 8로 전환

커밋과 GitHub CI 완료 후 실제 `fleet-gateway.service`가 읽던
`/home/fleetops/turtlebot-fleet-ops`를 확인했다. 이 복사본은 오래된 commit 위에 대량의
미커밋·미추적 파일이 있는 상태였으므로 자동 checkout이나 reset을 하지 않았다. 대신 원격의
검증된 브랜치를 `/home/fleetops/turtlebot-fleet-ops-phase8`에 별도로 clone하고 build했다.
WSL에서 새 overlay의 `fleet_gateway` 92개 테스트가 통과한 뒤 다음 조건을 모두 확인했다.

- TB1 online
- e-stop 활성
- motion 미재무장
- 활성 navigation command 없음

그 상태에서 systemd drop-in으로 관제 PC의 `fleet-control-zenoh.service`와
`fleet-gateway.service`만 새 경로로 전환했다. TB1 서비스와 로봇 motion 경로는 변경하지 않았다.
전환 후 두 서비스는 active였고 process command line도 새 clone과 install 경로를 가리켰다.
`/api/health`, `/api/patrols`, `/api/mlops/ros2-logs/incidents`는 모두 HTTP 200이었으며 TB1의
`estop_active=true`, `motion_armed=false`도 유지됐다. 1280×720 실제 runtime 화면은 가로·세로
overflow 없이 순찰·deadman·프로필·로그 MLOps 영역을 한 화면에 표시했고, e-stop 중 deadman은
잠금 상태였다.

기존 dirty 작업 트리와 기존 log MLOps service는 보존했다. 로봇에 새 interface와 Phase 8
서비스를 배포하기 전에는 새 manual/profile/map-save 요청이 fail-closed하는 것이 정상이다.

### Zenoh timestamp 교체 로그와 시각 보정

전환 전 관제 bridge 로그에서 TB1 수신 timestamp가 WSL 현재 시각보다 약 0.57초 앞서 500 ms
허용치를 넘고, Zenoh이 timestamp를 교체한 기록을 확인했다. TB1의 `systemd-timesyncd`는
`ntp.ubuntu.com`에 동기화되어 offset 약 1.5 ms였지만 Windows는 `Local CMOS Clock`, 미동기화
상태였고 WSL이 Windows 시각을 따르고 있었다.

WSL에 `ntpdate`를 설치해 네 NTP 서버를 조회하자 offset은 +0.574~+0.586초로 재현됐다. TB1이
e-stop 활성, motion 미재무장, 활성 목표 없음인 것을 다시 확인한 뒤 WSL 시각을 NTP에 맞추고
control bridge와 Gateway를 재시작했다. 재조회 offset은 +0.001~+0.013초였고 새 bridge PID에는
timestamp rejection이 더 이상 기록되지 않았다. TB1 online과 e-stop 상태도 유지됐다.

Windows Time 자체는 관리자 권한이 필요한 별도 호스트 설정이다. 현재 WSL runtime은 보정됐지만
Windows 또는 WSL을 재부팅한 뒤에는 실차 이동 전에 NTP offset과 bridge 오류를 다시 확인한다.

### TB1 Phase 8 배포와 profile status 복구

관제 PC만 Phase 8로 전환한 상태에서 웹 초기 위치 적용은 `Profile status is stale`로 거부됐다.
Gateway snapshot의 `mapping`이 `null`이었고, TB1에는 `tb1-profile-manager.service`가 설치되지 않은
이전 runtime이 실행 중이었다. 관제와 로봇의 공개 interface 버전이 다른 것이 직접 원인이었다.

TB1을 online, e-stop 활성, motion 미재무장, 활성 목표 없음으로 만든 뒤 저장소의 fail-closed 배포
절차로 commit `7c3879d`를 설치했다. 배포 절차는 navigation/mapping과 runtime 서비스를 먼저
정지하고 격리 domain 142에서 robot package를 build/test한 뒤 여덟 user unit을 설치했다. 완료
시점에는 navigation과 mapping을 모두 inactive로 남기고 profile manager만 IDLE로 기동했다.

배포 후 다음을 확인했다.

- `/fleet/mapping_status`: `IDLE`, fresh, map available
- `tb1-profile-manager.service`: enabled/active
- 저장된 map·pose graph 네 파일 보존 및 checksum 수집
- `/cmd_vel` Publisher: safety watchdog 한 개
- `/safety/cmd_vel_in` Publisher: IDLE에서 0개
- evidence: `output/tb1-acceptance/20260720-044020/`

다시 e-stop을 활성화한 상태에서 `NAVIGATION` 프로필로 전환했다. profile status는 fresh한
`NAVIGATION`으로 바뀌었고 Nav2/AMCL process와 새 `manual_control_node`가 실행됐다. 이때
navigation 상태 `UNAVAILABLE`과 AMCL의 “initial pose를 설정하라”는 로그는 실패가 아니라 아직
초기 위치를 받지 않은 정상 대기 상태다. 실제 위치와 방향은 작업자가 웹 지도에서 다시 지정한다.

### 경로는 생성되지만 실제 바퀴가 돌지 않은 원인

초기 위치 정합 뒤 세 목표가 모두 접수되고 Nav2 path도 생성됐지만, 20초 동안 map pose가
변하지 않아 `Failed to make progress in map frame`으로 종료됐다. 안전을 위해 e-stop을 먼저
활성화한 뒤, 작업자가 빈 공간을 확인한 상태에서 같은 목표를 4초만 실행하며 각 속도 계층과
odometry를 동시에 기록했다.

- `/cmd_vel_nav`, smoother, arbiter, watchdog, 최종 `/cmd_vel`까지 모두 non-zero 명령 전달
- DWB 원본 최대 각속도: `0.007692 rad/s`
- 4초 odometry yaw 변화: 약 `-0.000697 rad`로 사실상 정지
- 실제 `FollowPath.min_speed_theta`와 `min_speed_xy`: 모두 `0.0`

기존 `min_rotational_vel: 0.05`는 Nav2 behavior server 계열 설정이고 DWB `FollowPath`의 최소
샘플 속도를 제한하지 않았다. `vtheta_samples=40`, 최대 각속도 `0.3 rad/s` 조합에서 가장 작은
샘플 `0.3/39 = 0.007692 rad/s`가 그대로 선택된 것이 측정값과 일치했다. 최대 속도나 watchdog을
완화하는 대신 DWB에 `min_speed_theta: 0.05`, `min_speed_xy: 0.02`를 지정했다. 제자리 회전을
허용하기 위해 `min_vel_x: 0.0`은 유지했고 기존 상한 `0.05 m/s`, `0.3 rad/s`도 바꾸지 않았다.
수정 후 `navigation_agent` 전체 110개 테스트가 통과했으며, 실차 재배포·짧은 회전 검증 전까지
e-stop을 유지한다.

## 배운 점

“부드럽게 움직인다”는 요구는 단순히 timeout을 늘리는 문제가 아니었다. command 보간과
가속도 제한을 추가하되 stale authorization과 watchdog 정지는 더 짧고 독립적으로 유지해야
한다. 사용성 개선과 fail-safe는 같은 파라미터를 타협하는 대신 서로 다른 계층으로 설계하는
편이 명확했다.

MLOps도 모델 점수만 보여 주면 운영 기능이 되기 어렵다. dataset·model lineage와 함께 실제
logger·message 근거, 확인 순서를 연결해야 작업자가 판단에 사용할 수 있다. 동시에 분석 모델에
제어권을 주지 않는 경계가 로봇 시스템에서는 중요하다.

## 완료 체크리스트

- [x] 목적지·웨이포인트 최종 yaw 입력 계약
- [x] Nav2 20 Hz velocity smoothing과 기존 속도 상한 유지
- [x] TB1 로컬 timeout을 가진 웹 deadman manual
- [x] durable 순찰 정의와 순차 action 실행
- [x] 매핑·주행 프로필과 지도·pose graph 저장 서비스
- [x] ROS 2 로그 원인·증거·권장 조치 API와 UI
- [x] 로봇 없는 단위·통합·smoke·화면 검증
- [x] 기존 WSL 작업 트리를 보존한 clean Phase 8 관제 runtime 전환
- [x] TB1 Phase 8 배포와 profile status 수신
- [x] Nav2 무진행 원인을 DWB 최소 속도와 실제 odometry로 분리 진단
- [ ] 실제 목표 yaw·평활화 확인
- [x] 현재 WSL·TB1 시각 차이 500 ms 미만 및 새 bridge 오류 없음 확인
- [ ] Windows Time 영구 동기화 또는 재부팅 후 WSL NTP 재확인
- [ ] deadman·Gateway·Zenoh 단절 정지 시간 측정
- [ ] 새 환경 매핑·저장·AMCL 재기동
- [ ] 실차 순찰·취소·비재개와 incident 확인
- [ ] 10분 주행 CPU·메모리 및 단일 `/cmd_vel` Publisher 기록

## 남은 시간

새로운 결함이 없다면 실차 최종 검증은 3~4시간으로 예상한다. 배포·서비스 20~30분,
yaw·manual 20~30분, 매핑 35~50분, 순찰 30~45분, 장애·로그 35~50분, 10분 주행과 기록
20~30분이다. localization 또는 Zenoh 재조정이 필요하면 1~2시간을 추가한다.

## 관련 문서

- [Phase 8 설계](../design/phase-8-web-patrol-mapping-diagnostics.md)
- [Phase 8 공부 문서](../study/phase-8-web-control-patrol-diagnostics.md)
- [Phase 8 운영 절차](../setup/tb1-web-patrol-mapping.md)
