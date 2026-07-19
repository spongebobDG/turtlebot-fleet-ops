# 학습 일지: Phase 5 TB1 로컬 Nav2와 웹 목적지 구현

날짜: 2026-07-17

단계: Phase 5
진행 상태: 코드·테스트·운영 문서 구현 및 Humble CI 통과, 실차 검증 대기

## 오늘의 목표

TB1 로컬 Nav2 목표가 기존 watchdog을 우회하지 않게 하고, 웹 지도에서 초기 위치와
목적지를 지정하며, Gateway 단절과 agent 장애에도 로봇 내부에서 정지하는 경계를 만든다.

## 구현한 내용

- `NavigateRobot`, `NavigationLease`, `NavigationStatus`, `SafetyStatus`와 초기 위치·motion
  mode 서비스를 `fleet_interfaces`에 추가했다.
- `motion_arbiter`가 MANUAL/NAVIGATION 입력 하나만 `/safety/cmd_vel_in`으로 전달하게 했다.
- `navigation_agent`가 Nav2 goal, 2초 lease, 0.5초 authorization, e-stop과 startup
  cancel-all을 관리하게 했다.
- agent startup의 IDLE 전환과 Nav2 cancel-all은 서비스 응답을 확인한 뒤에만 준비 완료로
  간주하며, watchdog도 프로세스 시작·재시작 시 `WAITING_NEUTRAL`에서 시작하게 했다.
- 매핑과 주행 launch/systemd 프로필을 상호 배타적으로 만들었다.
- Gateway에 지도 registry, 상태 merge, 초기 위치·목표·취소 REST와 action/lease adapter를
  추가했다.
- 브라우저 canvas에 OccupancyGrid origin translation·yaw·resolution 변환과 클릭-drag
  방향 지정을 추가했다.
- e-stop 성공 뒤 active handle을 lease 목록에서 먼저 제거하고 취소하도록 했다.

## 자동 테스트 추가

- origin yaw를 포함한 world↔cell 및 world↔canvas 변환과
  free/unknown/occupied 정책
- REST 202/409/422와 WARN 확인 흐름, stale navigation/safety 거부
- arbiter mode, 입력 timeout과 authorization timeout
- fake Nav2 action 서버의 성공, feedback 전달, Nav2 거부, 명시적 취소, e-stop 취소,
  실패, 중복 거부와 lease 만료
- Gateway의 실제 0.5초 lease timer와 취소 직후 lease 중단
- agent 재시작 시 Nav2 cancel-all 요청과 Gateway stale lease 소유권 정리
- startup cancel-all 응답 코드 거부와 목표 접수 후 2초 미확인 lease 철회
- Nav2 action 서버 1초 부재 시 authorization 철회와 `FAILED` 종료
- watchdog SafetyStatus와 e-stop 중립 재무장
- Gateway의 ROS 메시지→JSON 변환

GitHub Actions는 ROS 2 Humble, 격리 domain 142에서 다섯 패키지를 빌드·테스트하도록
갱신했다. Nav2 의존성 설치 시간을 고려해 job timeout을 30분으로 늘렸다.

## 이 환경에서 실행한 검증

Windows 로컬 환경에는 ROS 2 Humble이 없어 ROS graph 테스트는 실행하지 못했다. 임시
Python 테스트 도구를 설치해 다음 검사를 실제 실행했다.

- 저장소 Python 파일 AST parse
- 브라우저 `app.js`·`map_math.js` Node 구문 검사와 Canvas 좌표 테스트 3개 통과
- 모든 `package.xml` XML parse
- map/arbiter/registry 순수 정책을 직접 import한 assertion 검사
- ROS 비의존 model, 운영 설정, registry, map, FastAPI와 기존 정책 회귀 테스트
  67개 통과, symbolic link 설치 테스트 1개 skip
- robot/control Python 전체 Ruff E/F 정적 검사 통과
- 매핑·주행·지도 저장 shell script 3개 `bash -n` 통과
- `git diff --check`

Windows에서 개발자 mode가 없어 symbolic link 설치 테스트 1개는 platform 조건으로
skip됐다. 같은 테스트는 Linux Humble CI에서 실행됐고 이후 전체 결과가 통과했다.

## Humble CI 1차 실행

Draft PR #7의 첫 실행은 웹 좌표 테스트와 ROS 2 Humble 설치까지 통과했지만
`rosdep install`에서 중단됐다. Ubuntu 22.04 runner의 `libgoogle-glog-dev`가 요구하는
`libunwind-dev`를 apt가 선택하지 못해 `ros-humble-nav2-bringup` 설치가 실패했다.
코드 빌드 전 runner 의존성 문제이며, Jammy가 같은 virtual dependency의 제공자로
정의한 `libunwind-15-dev`를 rosdep 전에 명시적으로 설치하도록 CI를 보강했다. 다음
실행에서 rosdep, colcon build와 domain 142 전체 테스트 결과를 다시 기록한다.

## Humble CI 2차 실행

Jammy용 `libunwind-15-dev`를 먼저 설치한 뒤에는 `rosdep install`과
`colcon build`가 모두 통과했다. 격리 domain 142 전체 테스트는 87개 중
84개가 통과하고 3개가 실패했다.

- Gateway ROS graph 테스트의 가짜 goal handle 클래스에 ament flake8이 요구하는
  클래스 설명과 공백이 없었다.
- quaternion에서 계산한 yaw는 정확한 `pi/2`였지만 테스트가 반올림한 `1.5708`을
  기본 오차로 비교해 정밀도 차이로 실패했다.
- e-stop 종료 직후 readiness 메시지를 발행하자마자 다음 목표를 보내 비동기 executor가
  새 안전 상태를 처리하기 전에 goal 검사가 실행되는 경쟁 조건이 있었다.

제품의 안전 판정은 바꾸지 않았다. 테스트가 `pi/2` 계약을 직접 비교하고, e-stop 뒤 새
`SafetyStatus`와 readiness가 실제로 처리될 때까지 기다리도록 보강했다. 이 변경은
아래 3차 CI에서 동일한 87개 테스트로 다시 검증했다.

## Humble CI 3차 실행

Draft PR #7의
[Actions 실행 29573131531](https://github.com/spongebobDG/turtlebot-fleet-ops/actions/runs/29573131531)에서
웹 좌표 테스트, ROS 2 Humble 설치, Jammy Nav2 의존성 설치, `rosdep install`,
5개 패키지 `colcon build`와 격리 domain 142 `colcon test`가 모두 통과했다.
`colcon test-result --verbose` 최종 결과는
`87 tests, 0 errors, 0 failures, 0 skipped`였다.

이 결과로 인터페이스 생성, fake Nav2 action의 성공·거부·feedback·취소·실패,
2초 lease, 0.5초 authorization, e-stop과 watchdog 재무장, Gateway REST·ROS graph,
지도 좌표 계약의 자동 검증 기준선을 확보했다. 실제 TB1 센서 정합과 물리 정지시간은
자동 테스트로 대신하지 않고 아래 실차 항목에 계속 남긴다.

## 로봇 없는 실제 Nav2 stack smoke 확장

fake action 통합 테스트만으로는 설치된 Humble Nav2의 launch, lifecycle, plugin,
remap과 실제 Gateway 연결을 한 번에 증명하지 못한다. 로봇 없이 다음 실제 프로세스를
격리 domain 142에서 함께 실행하는 headless smoke를 추가했다.

- 임시 80×80 free map과 TF·odom·scan·AMCL·RobotStatus를 발행하고 `/cmd_vel`을
  적분하는 `robotless_fixture.py`
- 실제 `map_server`, AMCL, controller/planner/behavior/BT navigator와 velocity smoother
- 실제 navigation agent, motion arbiter, safety watchdog과 Fleet Gateway
- 실제 HTTP 초기 위치·목표 성공·명시적 취소·e-stop·중립 재무장 흐름
- `/cmd_vel` publisher 단일성, controller의 중간 topic, watchdog 속도 상한과 최종 0

이 검증을 CI에 올리는 과정에서 로봇 없이도 일곱 가지 운영 결함을 발견했다.

1. ROS setup script는 `set -u`와 함께 source할 수 없으므로 source 구간만 nounset을
   해제해야 했다.
2. CI runner에는 선택한 `rmw_cyclonedds_cpp`가 기본 설치되지 않아 runtime 의존성을
   명시해야 했다.
3. Humble Nav2 launch의 `PythonExpression(['not ', use_composition])`에는 소문자
   문자열 `false`가 아니라 Python boolean 표현인 `False`를 전달해야 했다.
4. action server가 graph에 나타난 시점과 `bt_navigator` lifecycle ACTIVE 시점이 달라,
   endpoint만 보고 READY를 발행하면 activation 직전 목표가 거부됐다.
5. Nav2가 성공한 직후 새 `/amcl_pose`가 terminal `SUCCEEDED`를 `READY`로 덮어써
   Gateway와 웹이 결과를 관찰하지 못했다.
6. Humble bringup에서 controller는 내부 `cmd_vel_nav`를 발행하고
   `velocity_smoother`가 `cmd_vel_smoothed → cmd_vel` remap으로 최종 속도를 발행한다.
   바깥 `/cmd_vel` remap만 두면 이 내부 결과에 규칙이 다시 적용되지 않아 watchdog과
   smoother가 실제 `/cmd_vel`을 함께 발행했다. 반대로 `cmd_vel_smoothed`만 remap하면
   `behavior_server`의 네 recovery publisher가 실제 `/cmd_vel`에 남았다.
7. 두 공통 remap을 함께 두면 실제 `/cmd_vel`은 watchdog 하나로 정리되지만, 먼저
   적용되는 공통 `/cmd_vel` 규칙이 controller와 smoother 입력에도 걸렸다. 그 결과
   controller와 smoother 입력·출력이 `/motion/navigation/cmd_vel`에 합쳐져 smoothing
   경로가 무너졌다. 저장소 소유 non-composed Nav2 launch에서 controller, smoother,
   behavior 각각에 노드별 remap을 주어야 했다.

네 번째 문제는 smoke 대기 시간을 늘려 숨기지 않았다. navigation agent가
`/bt_navigator/get_state`를 조회해 `PRIMARY_STATE_ACTIVE`와 action server 준비가 모두
참일 때만 `nav2_ready`와 목표 접수를 허용하도록 수정했다. fake Nav2 통합 테스트에도
inactive 동안 `_ready_for_goal`이 false인 회귀 검사를 추가했다.
`SUCCEEDED`·`CANCELED`·`FAILED`·`LEASE_EXPIRED` terminal 상태는 새 초기 위치나 새 목표가
들어오기 전까지 보존하며, 반복 AMCL pose가 덮어쓰지 않게 했다.

e-stop scenario의 목표는 현재 pose에서 goal checker tolerance보다 충분히 멀어야 한다.
경계 안의 목표는 `ACTIVE`를 관찰하기 전에 정상 성공할 수 있으므로, 합성 map의 1.0m
자유 셀을 사용해 실제 이동 중 e-stop 전이를 결정적으로 만든다.

robotless smoke는 실제 ROS graph 계약을 크게 넓히지만 합성 센서와 단순 운동학을 쓴다.
실제 LiDAR 정합, 바퀴와 바닥의 동역학, Zenoh 단절 정지시간, systemd 복구와 Raspberry
Pi 자원 사용량은 실차 증거로 남긴다.

## Robotless stack 최종 CI 증거

Draft PR #7의
[Actions 실행 29585666278](https://github.com/spongebobDG/turtlebot-fleet-ops/actions/runs/29585666278)에서
저장소 소유 Nav2 launch와 강화된 graph 검사가 통과했다.

- 실제 HTTP 초기 위치 뒤 `READY`, 목표 `SUCCEEDED`, 명시적 `CANCELED`, e-stop 취소와
  중립 재무장 뒤 자동 재개 없음
- 실제 `/cmd_vel`: publisher 1개 `safety_watchdog`
- `/motion/navigation/cmd_vel`: publisher 5개
  (`velocity_smoother` 1개 + `behavior_server` recovery 4개), subscriber 1개
  `motion_arbiter`
- `/cmd_vel_nav`: publisher 1개 `controller_server`, subscriber 1개
  `velocity_smoother`
- 최종 telemetry: 비영 명령 114개, 최대 선속도 `0.05 m/s`, 최대 각속도
  `0.3 rad/s`, 종료 선속도·각속도 모두 0
- 5개 패키지 build 뒤 `89 tests, 0 errors, 0 failures, 0 skipped`

따라서 합성 환경에서 controller smoothing, recovery, arbiter와 watchdog 소유권까지
ROS graph로 확인했다. 이 수치는 실제 바닥에서의 정지거리나 Raspberry Pi 부하를
의미하지 않으므로 Phase 5 완료 근거에는 실차 결과를 추가해야 한다.

## Zenoh 격리-domain action smoke

[Actions 실행 29587499227](https://github.com/spongebobDG/turtlebot-fleet-ops/actions/runs/29587499227)에서
고정 버전 Zenoh ROS 2 DDS bridge 1.9.0을 설치하고 robot domain 160과 control domain
161 사이의 통신을 bridge TCP 경로로만 제한했다. 다음 custom action과 fleet topic
계약이 실제 Humble graph에서 통과했다.

- `NavigateRobot` 첫 목표 accept, feedback 3회 이상과 `SUCCEEDED` result
- `NavigationLease`의 control→robot 전달과 2초 이내 lease age
- `NavigationStatus`의 `READY`·`SUCCEEDED`·`CANCELED` robot→control 전달
- 두 번째 목표의 원격 cancel과 `CANCELED` result
- 같은 실행에서 실제 Nav2 stack smoke와 `89 tests, 0 errors, 0 failures, 0 skipped`

이 검증을 추가하면서 이전 문서 커밋의 CI가 `rosdep update` 원격 파일 다운로드 중
connection reset으로 실패한 것도 확인했다. 코드 실패가 아닌 일시적 네트워크 오류였고,
`rosdep update`를 최대 3회 재시도하도록 workflow를 보강했다. 다음 실행에서는 첫 시도에
성공했다.

결과적으로 로봇 없이 확인 가능한 Nav2 local graph와 Zenoh remote action 경계를 모두
자동화했다. 실제 TB1에서 남은 것은 센서·모터·LAN·systemd·자원 사용량을 포함한 물리
검증이며, 이를 자동 테스트 성공으로 대체하지 않는다.

## 검토 중 발견하고 보강한 점

### stale 보조 상태

RobotStatus heartbeat만 최신이고 navigation agent나 watchdog 상태가 오래된 경우, 이전
`nav2_ready=true`를 웹이 그대로 쓸 수 있었다. navigation/safety receipt age에 독립적인
`fresh` 값을 붙이고 stale이면 409로 거부했다. agent 자체도 로봇·안전·AMCL freshness를
다시 검사하므로 Gateway와 로봇 양쪽에 방어가 있다.

### e-stop과 goal 접수 경합

watchdog e-stop service 응답과 action goal 접수가 동시에 진행될 수 있다. Gateway에
로컬 e-stop 상태를 두고 pending goal이 뒤늦게 accept되면 즉시 cancel하며 lease를
시작하지 않게 했다. 이미 active인 goal은 e-stop 성공 뒤 active 목록에서 먼저 제거해
lease를 멈추고 cancel한다.

### Humble Nav2 result 계약

ROS 2 Humble의 `NavigateToPose` result는 `std_msgs/Empty`라 상세 error code가 없다.
custom action은 성공·취소·실패·lease 만료 outcome을 보존하고, 상세 code 필드가 있는
새 Nav2 배포판에서는 `getattr`로 전달한다. Humble에서는 code 0과 action status/message를
사용한다.

### watchdog 프로세스 재시작

watchdog이 주행 도중 재시작하면 기존 구현은 새 프로세스가 곧바로 motion-armed 상태가
되어 아직 살아 있는 Nav2 명령을 통과시킬 수 있었다. 시작 상태를
`WAITING_NEUTRAL`로 바꾸고 즉시 `motion_armed=false`를 발행한다. agent는 이를 받아
활성 목표와 authorization을 취소하고 arbiter를 IDLE로 바꾸며, 그 뒤의 0 입력만
watchdog을 재무장한다. ROS graph 테스트와 실차 장애 주입은 Humble CI 및 TB1에서
확인한다.

### agent·Nav2 재시작 뒤 stale goal

agent가 재시작하면 로봇 쪽 활성 goal은 사라져도 Gateway가 예전 action handle을 계속
보관해 새 요청을 409로 막을 수 있었다. Gateway가 한 번 확인한 active command와 이후
NavigationStatus를 대조해 더 이상 일치하지 않으면 lease 소유권을 제거하게 했다. 또한
Nav2 action 서버가 사라지면 downstream result future가 끝나지 않을 수 있으므로, 1초
부재 뒤 authorization을 철회하고 custom action을 `FAILED`로 끝내는 로컬 실패 신호를
추가했다. 이 ROS graph 전이는 Humble CI와 실차 장애 주입에서 확인한다.

## 아직 확인하지 않은 항목

- [x] Ubuntu 22.04 ROS 2 Humble `rosdep`, 5개 패키지 `colcon build`, 89개 test 통과
- [x] 실제 Nav2·AMCL·agent·arbiter·watchdog·Gateway robotless stack smoke
- [x] Zenoh 1.9.0 격리-domain action·feedback·result·cancel·lease·status smoke
- [ ] 실제 지도와 pose graph 저장
- [ ] AMCL READY와 지도·LiDAR 정합
- [ ] 저속 목표 도달, 취소와 WARN 확인 주행
- [ ] e-stop, Zenoh/Gateway 단절과 프로세스 장애 정지시간
- [ ] `/cmd_vel` publisher 단일성 및 Nav2/watchdog 실제 속도 측정
- [ ] 10분 CPU·메모리 측정

## 실차 연결 뒤 예상 시간

TB1·SSH·WSL·빈 시험 공간이 준비된 순수 실차 검증은 `3시간 5분~4시간 35분`으로
계산했다. 이 문서를 처음 작성할 때의 관제 환경 준비 추정은 `30~60분`이었다.
2026-07-18에 현재 PC의 WSL2·Humble·Nav2·Zenoh·Gateway 설치와 무로봇 검증을 실제로
완료했다. 따라서 연결 당일 환경 준비 시간은 더하지 않고 순수 실차 범위를 유지하며,
40분 buffer를 포함한 시험 창은 `5시간 15분`으로 갱신했다. 최신 산정은
[운영 절차의 실차 수용 시험 결과](../setup/tb1-navigation.md#실차-수용-시험-결과)와
[현재 PC 준비 완료 일지](2026-07-18-control-pc-readiness.md)를 따른다.

## 다음 작업

[TB1 매핑·Nav2 운영 절차](../setup/tb1-navigation.md)에 따라 전원 스위치에 접근 가능한
빈 공간에서 체크리스트 순서대로 실차 로그를 채운다. 모든
미확인 항목이 실제 값으로 바뀔 때만 Phase 5를 완료로 표시한다.

## 후속 결과

위 미확인 항목은 2026-07-19 TB1에서 모두 실행했다. watchdog 프로세스 장애에서 발견한
Publisher 공백은 C++ guard로 보강했고 자동 테스트와 실차 재시험을 통과했다. 후속 Phase 6
감사에서 최신 source-scoped 기준을 관제 PC 191개, TB1 144개로 정정했다. 과거 TB1 전체
합계에는 제거된 패키지의 build 잔여 결과가 섞여 있었다.
측정값과 Phase 5 완료 판정은
[TB1 로컬 Nav2 실차 수용 시험](2026-07-19-phase-5-tb1-navigation-acceptance.md)에 있다.
