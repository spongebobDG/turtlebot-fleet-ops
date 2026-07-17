# 학습 일지: Phase 5 TB1 로컬 Nav2와 웹 목적지 구현

날짜: 2026-07-17

단계: Phase 5
진행 상태: 코드·테스트·운영 문서 구현, Humble CI와 실차 검증 대기

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
skip됐다. 같은 테스트는 Linux Humble CI에서 실행된다. 현재까지 나머지 검사는
통과했고 Humble `colcon build/test` 결과는 아직 미확인이다.

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

- [ ] Ubuntu 22.04 ROS 2 Humble `rosdep`, `colcon build`, 전체 test 통과
- [ ] 실제 지도와 pose graph 저장
- [ ] AMCL READY와 지도·LiDAR 정합
- [ ] 저속 목표 도달, 취소와 WARN 확인 주행
- [ ] e-stop, Zenoh/Gateway 단절과 프로세스 장애 정지시간
- [ ] `/cmd_vel` publisher 단일성 및 Nav2/watchdog 실제 속도 측정
- [ ] 10분 CPU·메모리 측정

## 다음 작업

[TB1 매핑·Nav2 운영 절차](../setup/tb1-navigation.md)에 따라 CI를 먼저 통과시킨 뒤,
전원 스위치에 접근 가능한 빈 공간에서 체크리스트 순서대로 실차 로그를 채운다. 모든
미확인 항목이 실제 값으로 바뀔 때만 Phase 5를 완료로 표시한다.
