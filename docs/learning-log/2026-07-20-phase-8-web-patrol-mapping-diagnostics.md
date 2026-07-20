# 학습 일지: Phase 8 웹 수동 조종·순찰·매핑·원인 분석

날짜: 2026-07-20

단계: Phase 8

진행 상태: Phase 8 구현·자동 검증·TB1 실차 수용 시험 완료

## 오늘의 목표

실제 로봇 위치와 웹 방향의 불일치를 바로잡은 안전 브랜치 위에서 목적지 최종 yaw, 부드러운
저속 주행, 웹 deadman 수동 조종, 웨이포인트 순찰, 새 지도 작성, ROS 2 로그 원인 분석을 하나의
운영 흐름으로 확장한다. TB1을 움직일 수 없는 동안 가능한 구현과 검증은 모두 끝내고 실제
이동은 작업자가 로봇 옆에 있을 때만 한다.

## 구현한 내용

### 목적지 yaw와 속도 평활화

- 목적지와 웨이포인트는 클릭만으로 확정하지 않고 드래그 또는 숫자 yaw 입력을 요구했다.
- 화면 벡터를 OccupancyGrid origin 회전이 반영된 map 좌표로 바꾼 뒤 yaw를 계산했다.
- TB1 부하에 맞춘 Nav2 controller 5 Hz 뒤에 20 Hz `nav2_velocity_smoother`를 배치했다.
- Nav2 최대 속도 `0.05 m/s`, `0.27 rad/s`와 watchdog의 `0.3 rad/s`·단일 Publisher 경계를 유지했다.

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

WSL에 `ntpdate`를 설치해 네 NTP 서버를 조회하자 offset은 +0.574~+0.586초로 재현됐다. WSL만
보정하면 Windows 공유 시계가 약 40초 뒤 원래 오차를 다시 적용했다. 15초 주기의 WSL timer도
같은 이유로 영구 해법이 아니어서 제거하고 기본 WSL 서비스 상태를 복구했다.

저장소에 관리자용 `configure_windows_time.ps1`를 추가했다. Windows Time을 세 외부 NTP peer에
연결한 뒤 최초 offset이 0.2초보다 크면 `MaxAllowedPhaseOffset`을 한 번만 0으로 바꿔 즉시
보정하고 원래 값을 복구한다. Microsoft가 설명한 점진 보정과 즉시 clock set 경계를 그대로
사용한 것이다. 사전점검도 외부 NTP 표본이 ±0.2초를 넘으면 실차 모드에서 실패하도록 바꿨다.

실행 전 offset `+0.6038752초`가 실행 후 `+0.0032821초`로 줄었다. 이어 Windows stripchart는
`-0.0156~+0.0176초`, WSL NTP 조회는 약 `-0.100초`였고, control bridge와 Gateway를 재시작한
새 systemd invocation에서 70초 동안 timestamp rejection과 ERROR는 0건이었다. TB1은 online,
e-stop 활성, motion 미재무장, 활성 목표 없음 상태를 유지했다. 재부팅 뒤에도
`test_tb1_connection.ps1 -RequireRobot`으로 같은 ±0.2초 기준을 다시 검사한다.

### Deadman, Gateway, Zenoh 단절 정지 측정

초기 위치와 목표가 없는 빈 공간에서 e-stop을 해제하고 `0.1rad/s` 수동 회전 명령만 사용했다.
각 시험 직후에는 e-stop을 다시 활성화했으며 이전 수동 세션이나 목표가 재개되지 않았다.

| 시험 | 최종 `/cmd_vel` non-zero 지속 | 관찰 결과 |
| --- | ---: | --- |
| 한 번의 manual 명령 뒤 갱신 중단 | 0.301초 | 로컬 authorization 만료, arbiter `MANUAL -> IDLE` |
| manual 중 Gateway `SIGKILL` | 0.304초 | systemd 복구 7.532초, 이전 session 비재개 |
| manual 중 control Zenoh bridge `SIGKILL` | 0.305초 | 로컬 timeout 정지, bridge 자동 재시작, 이전 session 비재개 |

세 경우 모두 TB1의 0.35초 manual authorization이 Gateway의 재시작 시간이나 네트워크 복구보다
먼저 동작했다. Gateway 종료 시험 뒤 MLOps incident API는 `network_lease` 원인 후보와
`manual_control: Manual command lease expired` 원본 증거를 연결했다. 즉 분석 결과는 정지를
발생시키는 제어 경계가 아니라, 로컬 fail-safe가 동작한 뒤 원인을 설명하는 관측 경계로 유지됐다.

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

첫 재배포 시험에서는 실제 odometry yaw가 약 `0.239 rad` 변해 motor deadband 수정 효과가
확인됐다. 그러나 recorder가 `/cmd_vel_nav=1.0 rad/s`와 최종 명령 상한 `0.3 rad/s`, 순간
odometry `0.351 rad/s`를 함께 포착해 모니터가 시험을 즉시 중단하고 e-stop을 재활성화했다.
로그에는 planner action 응답이 약 1초 늦자 BT가 이를 실패로 판정하고 1.57 rad spin recovery를
시작한 기록이 있었다.

TurtleBot3 Humble 기준 파일은 회복 파라미터를 예전 `recoveries_server` 키 아래 두지만 현재
실행 파일은 `behavior_server` 이름으로 기동된다. 따라서 rewrite 값이 이 노드에 적용되지 않아
기본 `max_rotational_vel=1.0`, `min_rotational_vel=0.4`, `rotational_acc_lim=3.2`가 남았다.
launch에서 behavior node에 `0.3`, `0.05`, `0.6`을 직접 적용하고, TB1 costmap 부하에서 확인된
응답 지연을 회복 실패로 오판하지 않도록 BT server acknowledgement timeout을 20 ms에서 2초로
늘렸다. 이 변경은 2초 fleet lease, 0.5초 arbiter authorization, watchdog 정지 경계를 바꾸지 않는다.

두 번째 4초 시험은 `ACTIVE -> CANCELED`, 취소 HTTP 202, recovery 0회로 끝났다. 최종 command는
`0.3 rad/s` 이하, 관측 odometry 최대 각속도는 `0.278 rad/s`, LiDAR 최소 거리는 `0.308 m`였고
취소 후 선속도·각속도는 사실상 0이었다. planner 지연이 spin recovery로 바뀌는 문제는 사라졌다.
다만 controller가 10 Hz deadline을 여러 번 놓쳤고 e-stop 중에도 4코어 TB1의 load average가
`7.06`이었다. 실제 DWB 설정은 `vx_samples=20`, `vtheta_samples=40`, trajectory debug 활성,
가속도 `2.5/3.2`로 저속 운영에 비해 계산량과 raw 변화가 컸다.

최대 `0.05 m/s`에서는 5 Hz 제어 tick 사이 이동이 최대 1 cm이므로 controller를 5 Hz로 낮추고
DWB 표본을 `10 x 20`, 예측 시간을 1.0초로 줄였다. trajectory debug를 끄고 DWB 가속·감속을
smoother의 `0.08/-0.12 m/s²`, `0.6/-0.8 rad/s²`와 맞췄다. 최종 20 Hz smoothing, 속도 상한,
LiDAR clearance, authorization, watchdog은 유지한다.

저부하 설정의 4초 시험은 deadline miss와 recovery가 모두 0회였고 실제 yaw가 `0.235 rad`
변했다. 최종 command 최대 각속도는 `0.205 rad/s`, 취소 후 각속도는 약 `0.0004 rad/s`였다.
18초 CPU 측정은 평균 약 77.7% 사용이었다. 이어진 전체 목표 시험의 60초 CPU 측정은 평균
약 71.2% 사용이었고 deadline miss는 없었지만, 20초마다 progress timeout과 recovery가 발생해
40.2초에 fleet monitor가 실패 처리했다.

e-stop 상태에서 `ComputePathToPose`만 호출해 원인을 분리했다. 현재 yaw `-1.291 rad`에서 global
path 첫 구간 heading은 `1.906 rad`였고, wrapped 차이는 `-3.086 rad`였다. 즉 시계 방향 회전은
반대 명령이 아니라 거의 180도인 두 경로 중 약 `0.055 rad` 더 짧은 방향이었다. Nav2의
`SimpleProgressChecker`는 선형 0.1 m만 확인해 정당한 제자리 회전을 20초 뒤 실패로 봤고, fleet
monitor도 최종 목표 yaw 오차 감소만 각도 진행으로 인정해 path heading을 맞추는 동안의 회전을
인정하지 않았다.

controller plugin을 Humble의 `PoseProgressChecker`로 바꾸고 0.1 m 이동 또는 0.1 rad 회전 중
하나를 진행으로 인정한다. fleet monitor도 최종 yaw 방향과 무관하게 map-frame yaw가 누적
0.1 rad 변하면 진행 창을 갱신한다. 반복 진동이 무한 목표가 되지 않도록 180초 전체 목표 상한은
유지하며, feedback·lease·authorization·watchdog timeout도 바꾸지 않는다.

### 거의 반대 방향 경로 정렬과 최종 yaw 실차 성공

`PoseProgressChecker`만으로는 거의 180도인 경로에서 DWB가 시계·반시계 회전을 번갈아 고르는
경계 상황이 남았다. Humble에 설치된 `nav2_rotation_shim_controller`를 DWB 앞에 배치했다.
경로 첫 0.15m를 보고 현재 방향과 0.6rad 이상 차이가 나면 최대 0.2rad/s로 먼저 제자리 정렬하고,
0.35rad 안에 들어온 뒤 기존 DWB에 제어를 넘긴다. DWB·smoother·arbiter·watchdog과 단일
`/cmd_vel` 소유권은 그대로다.

커밋 `e3bd736` 배포 후 최초 목표는 시작 거리 약 0.37m에서 0.11m까지 줄었고 30.3초 동안
progress timeout과 recovery가 모두 0회였다. 시험 모니터가 명령 상한 0.3rad/s일 때 엔코더 기반
odometry의 순간 0.322rad/s를 감지해 목표를 취소했지만, 이 구간에서 회전 정렬과 직선 이동은
연속으로 이루어졌다. 명령 한도와 실제 응답 사이 여유를 만들기 위해 커밋 `be9cfe4`에서 Nav2,
velocity smoother, behavior server 각속도 상한을 모두 0.27rad/s로 낮췄다. watchdog 한도
0.3rad/s와 수동 조종 clamp는 바꾸지 않았다.

재배포 뒤 실제 parameter는 다음과 같았다.

| 항목 | 런타임 값 |
| --- | --- |
| `FollowPath.plugin` | `nav2_rotation_shim_controller::RotationShimController` |
| `FollowPath.primary_controller` | `dwb_core::DWBLocalPlanner` |
| `FollowPath.max_vel_theta` | `0.27 rad/s` |
| velocity smoother `max_velocity[2]` | `0.27 rad/s` |
| behavior server `max_rotational_vel` | `0.27 rad/s` |
| progress checker | `nav2_controller::PoseProgressChecker` |

마지막 방향 정렬 목표 command ID는 `95899d0cd0144b3391d678fd12acf60a`였다. 결과는
`ACTIVE -> SUCCEEDED`, 모니터 전체 7.65초, Nav2 navigation time 2.7007초, recovery 0회였다.
요청 pose `(0.1150, -0.0350, 0.0005rad)`에 대해 최종 map pose는
`(0.0996, -0.1262, 0.0566rad)`였으며 0.10m·0.15rad 허용오차 안이다. raw controller부터
smoother, arbiter, watchdog, 최종 `/cmd_vel`까지 기록한 최대 명령 각속도는 모두
`0.27rad/s`였고 성공 후 quiet 각속도는 최대 `0.000363rad/s`였다. LiDAR 최소 거리는
`0.448m`, recovery는 0회였다. 시험 직후 e-stop을 다시 활성화했고 motion은 미재무장,
활성 command는 없는 상태다. Draft PR #14의 `Humble build and test`도 커밋 `be9cfe4`에서
통과했다.

### 지도 저장·운영 원본 복원과 AMCL 재기동

MAPPING 프로필에서 안전 deadman 수동 조종으로 새 scan을 수집하고 map yaml/pgm과 pose graph를
저장했다. Zenoh 응답이 저장 도중 끊겨 HTTP 요청은 오래 대기했지만, profile manager의 저장 완료
상태와 네 파일을 다시 읽어 검증한 경우에만 Gateway가 성공으로 처리하도록 보강했다. 수정 후
저장 API는 95.251초 뒤 HTTP 202를 반환했다.

별도 acceptance 디렉터리의 생성 지도 validator 결과는 다음과 같다.

| 항목 | 값 |
| --- | ---: |
| 크기 | 53 × 112 cell |
| known cell | 561 |
| known 비율 | 0.0945 |
| occupied / free | 63 / 498 |
| pose graph | 파일과 data 모두 존재 |

운영 지도는 시험 전 backup에서 복원했고 yaml, pgm, posegraph, posegraph.data 네 파일의 SHA-256이
시험 전과 정확히 같았다. NAVIGATION 프로필 재기동 뒤 웹 초기 위치를 적용해 AMCL과 Nav2가
ready가 됐고 production map이 바뀌지 않았음을 확인했다. 실제 공간 지도는 Git에 넣지 않았다.

### 순찰 translation과 최종 yaw 분리

경로 진행 heading과 사용자가 요청한 최종 yaw 차이가 0.15rad보다 크면 하나의 pose에서 두 제어
목표가 경쟁했다. 순찰 worker를 다음처럼 바꿨다.

1. 현재 pose에서 웨이포인트까지의 진행 heading으로 translation goal 실행
2. 성공한 실제 도착 x/y에서 사용자가 지정한 yaw로 orientation-only goal 실행
3. 두 단계 사이 취소·e-stop·lease·재시작이 있으면 다음 목표를 보내지 않음

웨이포인트 `(-0.203470388, -0.111203484, 0.814565380)`과
`(0.002384995, 0.107024747, -2.327027273)`의 한 loop는 64.11초에 `COMPLETED`됐다.
LiDAR 최소는 약 0.508m, odometry 최대 선속도는 0.04758m/s, 최대 각속도는 0.25711rad/s였다.
명시적 취소는 남은 웨이포인트를 시작하지 않았고 Gateway 종료 뒤 systemd가 복구돼도 이전
순찰은 재개되지 않았다.

### 600초 순찰과 `/cmd_vel` 단일 소유권

첫 장시간 시험은 216.4초에 `0.176m < 0.190m` clearance로 안전 취소됐다. 이 값을 단발 센서
노이즈로 보고 필터를 완화하려 했으나, 작업자가 전원선을 정리하려 로봇을 잠시 들었다는 물리
개입이 확인됐다. 따라서 guard 동작은 정상이며 기준을 변경하지 않았다. 배터리로 전환하고
로봇을 바닥에 내려놓은 뒤 물리 개입 없는 새 시험을 수행했다.

600초 시험은 20 loop 순찰을 실행한 뒤 정확히 600초에 명시적으로 취소하고 e-stop을 적용했다.
11번째 loop까지 진행했으며 30초 표본은 다음 범위였다.

| 측정 | 결과 |
| --- | ---: |
| CPU | 66.1~73.6% |
| 메모리 | 27.1~27.3% |
| load average | 4.96~9.04 |
| LiDAR 최소 | 0.519m |
| 배터리 | 12.19V → 12.00V |
| robot fault | 0건 |

종료 결과는 patrol `CANCELED`, navigation `CANCELED`, e-stop active, motion-armed false였고
odometry는 선속도 `-0.0005m/s`, 각속도 `0.0002rad/s`로 사실상 0이었다. ROS graph에서
`/cmd_vel` Publisher는 `safety_watchdog` 하나, subscriber는 `turtlebot3_node` 하나였다.

### 성공 경로 INFO를 장애로 승격한 MLOps 오탐 보정

최근 raw 로그 incident에서 `Navigation agent ready: ... lease timeout=2.0s`가 `network_lease`로,
성공 순찰 중 Rotation Shim이 처리한 INFO transform 메시지가 localization/progress 원인으로,
costmap의 `Using plugin obstacle_layer` 초기화 INFO가 collision 원인으로 과대 집계됐다. raw
JSONL과 anomaly feature는 보존하되 이 네 root-cause 분류는 WARNING 이상만 incident로
승격하도록 바꿨다. `lease expired`, 실제 transform warning/error와 LiDAR clearance guard 오류는
계속 잡힌다. 성공 INFO 억제와 실제 warning/error 보존을 포함한 `fleet_gateway` 패키지 전체
테스트가 통과했다.

정상 프로필 전환 journal에는 별도의 데이터 품질 문제가 있었다. `ros2 launch`가 모든 child에
SIGINT를 보낼 때 `manual_control_node`가 spin과 destroy에서 받은 `KeyboardInterrupt`를 traceback으로
출력했고, navigation agent는 executor가 끝나기 전에 node를 파괴해 미회수 coroutine의 invalid
publisher warning을 남겼다. 실제 장애가 아니라 종료 순서의 경쟁이었다.

manual process는 spin·destroy·rclpy shutdown 각각의 반복 interrupt를 정상 종료로 흡수한다.
navigation agent는 fail-closed shutdown 뒤 executor를 먼저 종료하고 node를 제거·파괴한다.
종료 interrupt 회귀를 포함한 `navigation_agent` 패키지 테스트 114개가 통과했다. 실차에서는
e-stop 아래 NAVIGATION→IDLE 전환의 새 journal에서 traceback, KeyboardInterrupt, 미회수 coroutine을
다시 검사한다.

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
- [x] 실제 목표 yaw·평활화 확인 (`ACTIVE -> SUCCEEDED`, 전체 명령 최대 0.27rad/s)
- [x] 현재 WSL·TB1 시각 차이 500 ms 미만 및 새 bridge 오류 없음 확인
- [x] Windows Time 외부 NTP 영구 설정과 즉시 보정 (Windows +0.003초, 새 bridge 70초 오류 0건)
- [x] deadman·Gateway·Zenoh 단절 정지 시간 측정 (최종 0.301~0.305초, 무재개)
- [x] 새 환경 매핑·저장·AMCL 재기동과 운영 원본 checksum 복원
- [x] 실차 순찰·취소·비재개와 incident 확인
- [x] 600초 주행 CPU·메모리 및 단일 `/cmd_vel` Publisher 기록

## 완료 상태

Phase 8의 필수 실차 항목과 측정 기록을 모두 완료했다. 이후 작업은 Production 모델의 장기 drift,
다른 크기의 현장 지도와 저상 장애물 같은 운영 확장 backlog이며 Phase 8 완료 조건은 아니다.
TB2와 다중 로봇 할당도 현재 TB1 단일 로봇 MVP 범위에 포함하지 않는다.

## 관련 문서

- [Phase 8 설계](../design/phase-8-web-patrol-mapping-diagnostics.md)
- [Phase 8 공부 문서](../study/phase-8-web-control-patrol-diagnostics.md)
- [Phase 8 운영 절차](../setup/tb1-web-patrol-mapping.md)
