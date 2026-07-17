# 학습 일지: Phase 5 SLAM 입력과 Zenoh 안전 경계 실차 검증

날짜: 2026-07-16
단계: Phase 5A 완료
진행 상태: 무이동 SLAM·분산 안전 경계 검증 완료, 안전 구역 매핑 대기

## 오늘의 목표

- Hyper-V 방화벽 상태를 확정한다.
- TB1에서 SLAM Toolbox가 실제 지도를 만들지 못하는 원인을 증거로 찾는다.
- LDS-02 입력을 안정화하고 `/map`, TF와 0속도를 실차 검증한다.
- Zenoh가 최종 `/cmd_vel` 권한을 침범하지 않도록 최소 허용 목록을 적용한다.
- 결과, 시행착오, 필수 개념과 면접 답변을 문서와 Git에 남긴다.

## 왜 이 작업을 했는가

프로세스가 실행 중이고 토픽 이름이 보이는 것만으로 SLAM과 안전 경계가 정상이라고 할
수 없다. SLAM은 메시지 배열·각도 계약까지 만족해야 하고, 실제 모터 토픽은 로컬
watchdog 하나만 발행해야 한다. 실제 이동 전에 두 조건을 무동작 상태에서 확정했다.

## 진행한 활동과 실제 결과

### 1. Hyper-V 방화벽 완료 판정

`Get-NetFirewallHyperVVMSetting`에서 `DefaultInboundAction=Allow`를 확인했다.
`Enabled=NotConfigured`는 별도 활성값을 지정하지 않았다는 의미이며 기본 인바운드 동작이
실제 허용이므로 추가 규칙을 중복 생성하지 않았다.

### 2. 원본 LDS-02 스캔 100회 측정

첫 SLAM 실행 로그에서 다음 오류를 찾았다.

```text
LaserRangeScan contains 218 range readings, expected 219
```

100개 `/scan`을 직접 수집한 결과는 다음과 같았다.

```text
scan count: 100
ranges/intensities length: 207~219
angle_min: 0.148409888~0.324143887 rad
angle_max: 5.919308662~6.199401855 rad
angle_increment: 0.027454766~0.027674828 rad
scan_time: 0.098711267~0.099502489 sec
```

가장 자주 나온 길이도 216(24회), 211(16회), 215(12회)로 하나가 아니었다. Publisher
존재 여부가 아니라 메시지 내부 geometry가 장애 원인이었다.

### 3. `scan_normalizer` 구현

- 원본 `/scan` 구독
- 0~359도 고정 360-bin `/scan_normalized` 발행
- 각 샘플을 실제 각도로 계산해 가장 가까운 bin에 배치
- 중복 bin은 더 가까운 장애물 선택
- 미관측·유효 범위 밖 bin은 `+inf`
- SLAM Toolbox, AMCL과 두 costmap의 입력을 `/scan_normalized`로 변경
- 원본 `/scan`은 Robot Agent와 진단용으로 보존

구현 직후 로컬 테스트 15개와 TB1 테스트 15개가 통과했고, Zenoh 계약 테스트 추가 후
최종 로컬 전체는 83개, `fleet_navigation`은 19개 모두 통과했다.

### 4. TB1 무이동 SLAM 실기 검증

임시 systemd 사용자 단위로 SLAM을 시작하고 종료 시 자동 정리했다.

```text
/scan_normalized 20회: 모두 360 samples
angle_min: 0
angle_max: 6.2657318 rad
angle_increment: 0.017453292 rad (1 degree)
/map resolution: 0.05 m
/map size: 160 x 192
map -> odom TF: available
/cmd_vel: linear.x=0.0, angular.z=0.0
SLAM error/fatal/exception: none
```

이 결과로 정지 상태 센서·TF·지도 파이프라인은 완료 판정했다. 실제 공간 품질과 loop
closure는 이동 매핑에서 별도로 판정한다.

### 5. Zenoh 최종 속도 권한 문제 발견

TB1 `/cmd_vel --verbose`에 두 Publisher가 보였다.

- `safety_watchdog`
- `zenoh_bridge_ros2dds` 프록시

값은 0이었지만 최종 모터 명령의 단일 권한 계약을 어긴 상태였다. Zenoh 기본 동작이 모든
발견 인터페이스를 중계하기 때문에 발생했다.

### 6. 최소 허용 목록 적용

로봇·관제 브리지에 서로 다른 allow-list를 만들었다.

- 로봇 → 관제: 상태, 센서, TF, 지도, Nav2 시각화
- 관제 → 로봇: `/safety/cmd_vel_in`, 초기 위치, Goal
- 서비스: e-stop의 서버/클라이언트 반쪽
- Action: `navigate_to_pose` 서버/클라이언트 반쪽
- `/cmd_vel`: 양쪽 모두 미허용

Zenoh 1.9 실제 바이너리를 격리 도메인과 별도 포트에서 실행해 두 구성 모두 정상 파싱과
플러그인 시작을 확인했다. 허용 목록 계약 테스트 4개도 추가했다.

### 7. 운영 재시작과 e-stop 검증

TB1 브리지와 WSL 브리지를 순차 재시작한 뒤 다음을 확인했다.

```text
TB1 /cmd_vel publishers: 1 (safety_watchdog only)
TB1 /cmd_vel subscribers: 1 (turtlebot3_node)
WSL /cmd_vel publishers: 0
WSL /fleet/robot_status publishers: 1
e-stop ON response: success
e-stop 중 /cmd_vel: zero
e-stop OFF response: waiting for a neutral command
/safety/cmd_vel_in subscriptions across Zenoh: 1
neutral commands: 5
Gateway: known_robots=1, online_robots=1
TB1/WSL 운영 서비스: all active
```

로봇에 비영 속도는 한 번도 보내지 않았다.

## 발생한 문제와 해결

### 1. ROS 환경 스크립트와 `set -u`

원격 검증 스크립트에서 `set -u`를 ROS setup보다 먼저 적용해
`AMENT_TRACE_SETUP_FILES`, `COLCON_TRACE` 같은 선택 변수가 미정의로 판정됐다. ROS와
colcon 환경을 먼저 로드하고 검증 스크립트에서는 `-e`, `pipefail`만 사용했다. 제품
패키지 오류가 아니라 Shell 실행 정책의 순서 문제였다.

### 2. Windows CRLF가 WSL Bash 서비스를 중단

Windows의 `core.autocrlf=true`가 수정한 `.sh`를 CRLF로 체크아웃해 WSL에서
`pipefail\r: invalid option name`이 발생했다. 두 스크립트를 LF로 정규화하고 다음
`.gitattributes`를 추가했다.

```gitattributes
*.sh text eol=lf
*.service text eol=lf
*.xml text eol=lf
*.yaml text eol=lf
*.yml text eol=lf
*.json5 text eol=lf
```

`bash -n`, systemd 재시작과 Gateway `online=1`로 복구를 확인했다.

### 3. `ros2` CLI discovery 지연

새 WSL CLI 프로세스의 서비스 조회가 timeout됐지만 같은 환경의 직접 `rclpy` 클라이언트는
2초 안에 e-stop 서비스를 발견하고 응답받았다. 안전 검증은 CLI 화면이 아니라 실제
서비스 요청·응답과 TB1 출력 토픽으로 판정했다. CLI daemon 상태는 기능 완료 조건에서
분리했다.

## 오늘 꼭 기억해야 할 것

1. 토픽이 보인다는 것은 메시지 내용의 계약까지 정상이라는 뜻이 아니다.
2. LaserScan은 `ranges` 길이뿐 아니라 `angle_min/max/increment`가 서로 일관돼야 한다.
3. 가변 각도 데이터를 고칠 때 index를 자르지 말고 실제 각도로 재투영한다.
4. 관측하지 않은 거리는 0이나 가짜 보간보다 `+inf`가 안전하다.
5. 최종 `/cmd_vel` Publisher는 로봇 로컬 watchdog 하나여야 한다.
6. 브리지는 네트워크 연결 도구이면서 권한 경계이므로 필요한 인터페이스만 허용한다.
7. e-stop 해제 직후에는 비영 입력을 재개하지 않고 중립 명령으로 재무장한다.
8. Windows와 Linux가 함께 쓰는 저장소는 실행 스크립트 LF 규칙을 저장소에 고정한다.

## 면접에서 이렇게 설명한다

### “토픽이 있는데 왜 SLAM이 안 됐나요?”

> ROS graph에서 Publisher는 보였지만 SLAM 로그는 스캔 길이 불일치를 보고했습니다.
> 100개 메시지를 측정하니 길이가 207~219이고 시작·끝 각도도 변했습니다. 그래서 토픽
> 연결 문제가 아니라 소비자가 기대하는 LaserScan geometry 계약 문제로 좁혔습니다.

### “왜 padding이나 truncate를 하지 않았나요?”

> 배열 길이뿐 아니라 시작 각도가 변해 단순 padding은 같은 index를 다른 물리 방향으로
> 만들 수 있습니다. SLAM 점군을 왜곡하지 않도록 각 샘플의 실제 각도를 계산해 고정
> 360-bin으로 재투영했습니다.

### “왜 Zenoh에서 `/cmd_vel`을 막았나요?”

> 최종 모터 토픽은 timeout, clamp, e-stop과 중립 재무장을 집행하는 로봇 로컬
> watchdog만 발행해야 합니다. 브리지 프록시가 같은 토픽을 발행하면 원격 생산자가 안전
> 경계를 우회하거나 다중 Publisher 경쟁이 생길 수 있어, 원격 속도는 오직
> `/safety/cmd_vel_in`으로만 허용했습니다.

### “수정이 안전하다는 것을 어떻게 확인했나요?”

> 정적 테스트로 allow-list 양쪽 반쪽과 `/cmd_vel` 금지를 검사했고, 실제 Zenoh 1.9로
> 구성을 파싱했습니다. 운영 재시작 뒤 TB1 graph에서 watchdog Publisher 1개, WSL에서는
> `/cmd_vel` Publisher 0개를 확인했습니다. 이어 e-stop ON·OFF, 0속도와 중립 재무장,
> Robot Status와 Gateway online까지 end-to-end로 확인했습니다.

## 복습 문제와 정답

### 1. `ranges` 길이만 360으로 만들면 충분한가?

정답: 아니다. 각 index가 나타내는 실제 각도와 `angle_min/max/increment`도 일관돼야 한다.
그렇지 않으면 같은 벽이 잘못된 방향에 배치된다.

### 2. 미관측 bin에 0을 넣으면 왜 위험한가?

정답: LaserScan의 0은 매우 가까운 장애물 또는 유효 범위 밖 값으로 소비자마다 다르게
처리될 수 있다. `+inf`는 해당 방향에 유효한 반사가 없었다는 의미를 명확히 전달한다.

### 3. Zenoh 양쪽에 allow-list가 필요한 이유는?

정답: 한쪽의 ROS Publisher/Service Client와 다른 쪽의 ROS Subscriber/Service Server가
각각 별도 route 반쪽을 만들기 때문이다. 한쪽만 허용하면 연결이 완성되지 않거나 반대
방향의 불필요한 인터페이스가 남는다.

### 4. `/cmd_vel`이 0이면 Publisher가 둘이어도 괜찮은가?

정답: 아니다. 지금 값이 0이라는 관측과 누가 앞으로 비영 값을 발행할 권한이 있는지는
다른 문제다. 최종 권한은 하나로 제한해야 예측 가능하고 감사 가능한 안전 경계가 된다.

### 5. e-stop OFF 직후 중립 명령을 요구하는 이유는?

정답: 조이스틱이나 원격 Publisher가 이전 비영 입력을 계속 보내는 상태에서 즉시 움직이는
것을 막기 위해서다. 사람이 입력을 중립으로 돌렸음을 확인한 뒤에만 다시 허용한다.

### 6. CRLF 문제를 개인 PC 설정이 아니라 `.gitattributes`로 고친 이유는?

정답: 협업자와 CI 환경이 달라도 저장소 자체가 Linux 실행 파일의 LF 계약을 강제해야
재현 가능하기 때문이다.

## 완료 체크리스트

- [x] Hyper-V 기본 인바운드 Allow 확인
- [x] 원본 LDS-02 100회 형상 측정
- [x] 고정 각도 `scan_normalizer` 구현·테스트
- [x] TB1 `/map`, `map -> odom`, 0속도 무이동 검증
- [x] Zenoh 최소 권한 allow-list 구현·실제 파싱
- [x] 최종 `/cmd_vel` Publisher를 watchdog 1개로 제한
- [x] 원격 e-stop, 중립 재무장과 Gateway 자동 복구 검증
- [x] Linux LF 저장소 정책 추가
- [x] 로컬 전체 83개 테스트 통과
- [ ] 안전 구역에서 저속 수동 매핑
- [ ] 지도 저장·품질 검토
- [ ] AMCL과 Nav2 Goal 실차 검증

## 다음에 할 일

1. 사용자가 TB1의 물리 안전 조건과 매핑 공간을 확인한다.
2. SLAM을 시작하고 watchdog 경유 저속 teleop으로 폐곡선을 만든다.
3. 지도·pose graph를 저장하고 RViz에서 품질을 검토한다.

## 관련 커밋

- `730591e fix: normalize LDS-02 scans for SLAM`
- `b5475d7 fix: restrict Zenoh ROS routes`
- `b789b15 chore: enforce Linux line endings`
