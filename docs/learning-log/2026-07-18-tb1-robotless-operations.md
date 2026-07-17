# 학습 일지: TB1 로봇 없는 운영 기능 완성

날짜: 2026-07-18

단계: Phase 5 안전 복원과 Phase 6 TB1 운영 기능

진행 상태: 구현·로컬 비ROS·브라우저·Humble CI 완료, TB1 실차 연동 대기

## 목표

기존 문서의 결정대로 TB2를 현재 범위에서 제외하고, TB1을 다시 연결하기 전까지 가능한
코드·테스트·웹·배포 검증과 공부 문서를 모두 끝낸다.

## 이전 기록 감사에서 찾은 누락

- 실제 LDS-02는 `/scan` 길이가 207~219로 바뀌어 SLAM이 거부했고 360-bin 각도 재투영을
  실차에서 검증했지만 현재 브랜치에 빠져 있었다.
- `scan_queue_size=10`, `minimum_travel_distance=0.05`, 지도 `free_thresh=0.196`과 pose graph
  round-trip 검증이 실차 근거가 있는 값이었다.
- Zenoh 기본 bridge가 `/cmd_vel` proxy Publisher가 된 적이 있어 direction allow-list가
  필수였지만 현재 설정에 없었다.
- 잔류 teleop 입력 뒤부터는 5cm·30도 보호 이동과 pose checkpoint를 쓰기로 했었다.
- TB1 로그·고장·단일 작업 수명주기가 로봇 없는 기간의 우선순위였다.

## 구현한 내용

- 스캔 정규화, SLAM 값, 지도 validator, 보호 이동과 Zenoh allow-list를 현재
  `navigation_agent` 구조로 복원했다.
- SQLite WAL 기반 `tasks`, `faults`, `events` 저장소를 추가했다.
- fault 발생·심각도 변경·해제만 event로 남기고 heartbeat 중복은 제거했다.
- 작업 생성·실행·취소·실패·retry API와 parent/attempt lineage를 추가했다.
- 웹에 작업 실행·취소·retry, 활성 고장과 감사 이벤트 패널을 추가했다.
- 현재 `NavigateRobot`, lease, NavigationStatus, SafetyStatus와 지도·초기 위치를 제공하는
  lightweight mock과 success·cancel·failure·retry smoke를 추가했다.
- systemd unit 상호 배타성, restart 정책과 의존 관계를 자동 검사하는 script를 추가했다.

## 첫 안전 복원 CI에서 발견한 문제

실제 Nav2 stack smoke와 Zenoh action smoke는 통과했지만 최종 colcon test의 보호 이동
통합 테스트 5개가 실패했다. smoke가 시작한 `ros2 launch` 자식 프로세스가 부모 PID 종료
뒤 남아 같은 domain에서 `motion_arbiter` Publisher로 발견됐고, 구형 fixture도 guard 출력을
`/safety/cmd_vel_in`으로 직접 연결해 새 arbiter 경계를 우회하고 있었다.

제품의 단독 Publisher 검사가 이 격리 실패를 정확히 차단했다. smoke 프로세스를 새 process
group으로 시작해 group 전체를 종료하고, fixture는 고유 토픽에서
`manual -> relay -> watchdog -> final` 경로를 사용하도록 바꿨다. 테스트를 느슨하게 만들거나
외부 Publisher를 허용하지 않았다.

다음 CI에서는 Nav2와 Zenoh smoke가 통과한 뒤 작업 smoke가 취소 직후 새 실패 시나리오를
시작하며 `409 active goal`로 멈췄다. task 취소 응답과 로봇 action terminal status 반영 사이의
짧은 비동기 구간이었다. 제품의 중복 목표 차단을 약화하지 않고 smoke client가
`active_command_id` 소멸을 확인한 뒤 다음 목표를 시작하도록 수정했다.

작업 smoke가 통과한 같은 실행의 전체 테스트에서는 Robot Agent stale 통합 테스트 한 개가
실패했다. 세 sensor message를 연속 발행해도 executor callback 수신 시각은 조금씩 다르므로,
가장 먼저 stale이 된 odom snapshot에는 scan이 아직 fresh일 수 있었다. 제품 timeout을
늘리지 않고 테스트가 battery·odom·scan 세 stale code가 모두 포함된 snapshot을 기다리도록
동기화 조건을 바로잡았다.

## 로컬 검증

Windows에는 ROS 2 Humble이 없어 ROS graph 테스트는 CI로 남겼다. 로컬에서는 다음을 실행했다.

- SQLite·FastAPI·task manager·registry·map 테스트: 29 passed, 1 Windows symlink skip
- navigation 순수 model·지도 validator·motion·운영 설정·Zenoh 계약: 62 passed
- watchdog policy 15 passed, Robot Agent model·system metrics 30 passed
- 로컬 비ROS Python 합계: 136 passed, 1 skip
- 전체 추가 Python AST, pycodestyle와 pyflakes 통과
- shell script `bash -n`, map Canvas 기존 테스트 구조와 `git diff --check`
- ROS-free seeded dashboard에서 WebSocket 연결과 작업 저장·실행·취소, fault·audit 갱신,
  console error 0개를 실제 브라우저로 확인

## 최종 로봇 없는 CI 결과

[GitHub Actions run 29596474724](https://github.com/spongebobDG/turtlebot-fleet-ops/actions/runs/29596474724)에서
다음을 모두 통과했다.

- Ubuntu 22.04, ROS 2 Humble, 5개 workspace 패키지 build
- `173 tests, 0 errors, 0 failures, 0 skipped`
- 실제 Nav2·AMCL·agent·arbiter·watchdog·Gateway robotless stack smoke
- Zenoh 1.9.0의 분리 DDS domain 사이 custom action smoke
- 작업 성공·취소·실패·retry, fault·audit 영속화 smoke
- systemd unit, launch 인자, shell, Python preview 정적 validation

## 배운 점

1. 이전 실차 증거는 새 구현보다 우선해 현재 코드에 보존해야 한다.
2. process 종료는 launch 부모 PID 종료와 전체 ROS 자식 종료가 같은지 확인해야 한다.
3. 안전 테스트는 새 아키텍처 경계를 실제로 통과해야 하며 편의를 위해 우회하면 안 된다.
4. 최신 snapshot과 운영 event history는 별도 저장 모델이 필요하다.
5. retry는 상태 되돌리기가 아니라 새 시도 생성이다.

## 실차로 남긴 항목

- 최종 loop closure 지도와 pose graph 저장
- 웹 초기 위치 뒤 AMCL·LiDAR 정합
- 저속 도달·취소·WARN과 `/cmd_vel` 단일 Publisher
- e-stop, Gateway/Zenoh lease 단절과 프로세스 장애 주입
- 10분 주행 CPU·메모리와 실제 로그·측정값 문서화
