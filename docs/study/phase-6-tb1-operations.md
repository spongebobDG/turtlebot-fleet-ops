# Phase 6: TB1 작업 상태 머신과 운영 기록

## 반드시 알아야 할 개념

1. 최신 상태 snapshot과 시간 순서가 필요한 event history는 목적이 다르다.
2. heartbeat마다 로그를 남기면 실제 장애 전이가 반복 데이터에 묻힌다.
3. ROS action goal과 운영 task는 같은 식별자가 아니다.
4. retry는 과거 실패를 덮지 않는 새 attempt여야 한다.
5. 영속 저장 실패가 로봇 상태·안전 callback을 막으면 안 된다.
6. task manager도 기존 map·WARN·e-stop·lease 검사를 그대로 통과해야 한다.
7. SQLite WAL은 단일 Gateway의 읽기·쓰기 동시성을 단순하게 처리하는 선택이다.
8. mock 성공은 상태 계약 증거이지 물리 주행 증거가 아니다.
9. 취소 요청 수락과 로봇 action의 terminal 상태 반영은 같은 시점이 아니다.
10. 프로세스 재시작 뒤 이전 action 소유권을 복원할 수 없으면 task도 fail-closed로 닫아야 한다.
11. `systemd active`와 실제 운영 네트워크 준비는 같은 조건이 아니다.
12. 테스트 합계에는 현재 source package 범위를 함께 기록해야 한다.

## 개념 설명

### Snapshot과 event는 무엇이 다른가?

Snapshot은 “지금 TB1이 어떤 상태인가”에 빠르게 답한다. Event는 “언제 무엇이 바뀌었고 누가
무슨 요청을 했는가”를 복원한다. WebSocket에는 최신 snapshot을 반복 전송하고, 지도와 감사
기록은 별도 REST로 필요할 때 가져오는 이유다.

### 왜 fault heartbeat를 그대로 저장하지 않는가?

2Hz 상태에서 10분 동안 같은 고장이 유지되면 1,200개의 중복 행이 생긴다. 발생 한 건,
`last_seen` 갱신, 해제 한 건으로 모델링하면 장애 지속 시간과 복구 여부를 바로 계산할 수 있다.

### Action command ID와 task ID를 왜 나누는가?

command ID는 한 번의 ROS action과 lease를 묶고 잘못된 취소를 막는다. task ID는 작업 생성,
실행 전 대기, 결과와 retry lineage까지 포함하는 운영 식별자다. task가 재시도되면 새 action과
새 command ID가 생기므로 두 ID를 하나로 쓰면 과거 실행과 현재 실행이 섞인다.

### retry 때 같은 task를 다시 ACTIVE로 바꾸면 왜 안 되는가?

실패한 시도와 다음 시도의 경계가 사라져 성공률, 실패 원인과 작업자의 판단을 추적할 수 없다.
새 task를 만들고 `parent_task_id`, `attempt`로 연결하면 모든 시도를 보존할 수 있다.

### SQLite를 선택한 이유는?

현재 작성자는 한 Gateway, 한 TB1과 소규모 이벤트를 운영한다. 별도 DB 서버 없이 트랜잭션,
index와 재시작 후 복구를 얻을 수 있고 백업도 한 파일로 단순하다. 다중 Gateway와 높은 쓰기
처리량이 필요해질 때 PostgreSQL 같은 외부 DB를 검토하면 된다.

### 저장 실패를 왜 best-effort observer로 격리하는가?

감사 DB 잠금이나 디스크 오류 때문에 RobotStatus callback이 예외로 중단되면 웹 freshness와
명령 차단 판단까지 오래된 상태가 될 수 있다. 기록 오류는 별도 경보 대상이지만 안전·상태
수신 경로를 멈추게 해서는 안 된다.

### 취소 API가 202면 바로 새 목표를 보내도 되는가?

아니다. 202는 취소 요청이 접수됐다는 뜻이며 action server가 terminal result를 내고
`NavigationStatus.active_command_id`를 비울 때까지 짧은 전파 구간이 남을 수 있다. 이때 새
목표를 허용하면 두 action의 상태와 lease가 겹칠 수 있다. Gateway는 기존 활성 목표 검사를
유지하고, 자동 smoke도 `active_command_id`가 사라진 것을 확인한 뒤 다음 시나리오를 시작한다.

### Gateway 재시작 뒤 ACTIVE task를 왜 다시 실행하지 않는가?

SQLite에는 task가 남아도 이전 프로세스의 ROS action goal handle과 lease timer는 남지 않는다.
새 프로세스가 DB 상태만 보고 lease를 다시 발행하면 이미 취소 중인 Nav2 목표를 잘못 되살릴 수
있다. 그래서 시작 시 `STARTING`과 `ACTIVE`를 `FAILED`로 닫고 새 attempt만 명시적으로 만들게
한다. navigation agent도 재시작 시 Nav2 cancel-all과 IDLE을 확인하므로 양쪽이 같은
무재개 원칙을 가진다.

### ROS·Zenoh를 왜 Wi-Fi 주소 준비 뒤 시작해야 하는가?

`network-online.target`이 도달했거나 unit이 active라는 사실만으로 실제 운영 인터페이스에
global IPv4 주소와 기본 경로가 있다는 뜻은 아니다. DDS와 Zenoh가 너무 일찍 시작되면 로봇
프로세스는 살아 있어도 관제 heartbeat가 돌아오지 않을 수 있다. 이 프로젝트는 로봇 로컬
network gate가 두 조건을 직접 확인한 뒤 ROS runtime을 시작한다.

### 테스트 실패 때 safety timeout을 늘리지 않은 이유는?

단독 navigation 통합 테스트 87개가 모두 통과하고 Pi의 병렬 package 실행에서만 safety status가
stale됐다. 제품의 freshness 계약이 틀린 것이 아니라 CPU scheduling 경합이었다. 따라서 0.5초·
2초 안전 계약은 유지하고 실차 acceptance executor를 순차화했다. 안전 한계를 넓혀 테스트를
맞추는 것보다 검증 환경의 결정성을 높이는 선택이다.

## 실제 TB1 증거

2026-07-19에 다음을 실제 저장 지도와 TB1 terminal 상태로 확인했다.

- 실행 전 취소, 성공, 실행 중 취소와 retry attempt 성공
- Gateway 재시작과 navigation agent 강제 종료 중 ACTIVE task의 `FAILED`·무재개
- SQLite 재개방 뒤 여섯 task attempt, parent lineage, fault·event 이력 유지
- TB1 재부팅 뒤 관제 재시작 없이 Wi-Fi→ROS·Zenoh→Gateway heartbeat 자동 복구
- 재부팅 뒤 active task와 command 0, 10초 표본 속도는 정지 잡음 수준
- 초기 위치 재적용 뒤 AMCL·Nav2 `READY`, 최종 e-stop과 `/cmd_vel=0`
- TB1 현재 소스 범위 144개, 관제 PC 전체 191개 테스트 통과

세부 측정은
[Phase 6 TB1 작업·복구 수용 시험 일지](../learning-log/2026-07-19-phase-6-tb1-operations-acceptance.md)에 있다.

## 틀리기 쉬운 설명

| 틀린 설명 | 올바른 설명 |
| --- | --- |
| 현재 fault_codes만 보면 장애 이력을 안다 | 발생·해제 시각은 별도 event와 fault history가 필요하다 |
| retry는 FAILED를 CREATED로 되돌리면 된다 | 새 attempt를 만들어 과거 실패를 보존한다 |
| task가 ACTIVE면 로봇은 반드시 움직인다 | action accepted 상태이며 lease·Nav2·watchdog이 계속 허가해야 한다 |
| 취소 API가 성공하면 즉시 새 goal을 보내도 된다 | terminal status와 active command 해제를 확인해야 한다 |
| Gateway 재시작 뒤 ACTIVE task를 이어서 lease하면 된다 | 이전 action handle을 복원할 수 없으므로 실패로 닫고 명시적으로 retry한다 |
| SQLite면 동시성 문제가 없다 | 짧은 transaction, timeout, WAL과 단일 writer 경계를 설계해야 한다 |
| mock에서 성공했으니 TB1도 성공한다 | API·상태 전이만 검증했으며 센서·모터·LAN은 실차 항목이다 |

## 면접 모범 답변

> TB1 운영 기능에서는 최신 상태와 이력을 분리했습니다. Registry는 heartbeat freshness를 계산하고,
> SQLite store는 fault의 발생·해제 전이와 task 수명주기를 저장합니다. 작업은 생성과 실행을
> 분리하고 ROS action command ID를 연결합니다. 실패나 취소 후 retry는 기존 행을 되돌리지 않고
> parent와 attempt를 가진 새 task로 만들어 이력을 보존합니다. 모든 실행은 기존 map, WARN,
> e-stop과 lease 검사를 재사용하며, robotless custom-action mock으로 성공·취소·실패·retry를
> 검증하되 물리 주행 증거와는 구분했습니다.

실차 검증 뒤에는 다음처럼 설명할 수 있다.

> 실제 TB1에서 task 성공·취소·retry를 NavigationStatus와 SQLite terminal 상태까지 연결했습니다.
> Gateway와 navigation agent를 ACTIVE 작업 중 재시작했을 때 이전 action 소유권을 추정해
> 복구하지 않고 task를 실패로 닫아 자동 재개를 막았습니다. 재부팅에서는 Wi-Fi 주소와 기본
> 경로를 확인하는 로봇 로컬 network gate를 추가해 관제 서비스 재시작 없이 heartbeat가
> 복구되는 것을 확인했습니다.

## 복습 문제와 정답

### 1. 같은 fault가 2Hz로 들어올 때 event는 몇 개가 필요한가?

정답: 지속 중에는 발생 event 한 개면 되고 `last_seen`만 갱신한다. 복구 시 해제 event 한 개를
추가한다. 심각도가 변하면 그 전이도 별도 event다.

### 2. task와 command ID의 수명 차이는 무엇인가?

정답: task는 생성부터 retry lineage까지, command ID는 한 번의 action과 lease까지만 산다.

### 3. mock으로 검증할 수 없는 핵심 항목은 무엇인가?

정답: 실제 LiDAR·지도 정합, 모터 정지시간, Zenoh LAN 단절, systemd 프로세스 복구와 Pi 자원이다.

### 4. Gateway 재시작 때 `STARTING`과 `ACTIVE` task를 어떻게 처리하는가?

정답: 둘 다 `FAILED`로 닫고 감사 event를 남긴다. 이전 action과 lease는 자동 재개하지 않으며,
작업자가 원인을 확인한 뒤 새 retry attempt를 만든다.

### 5. unit이 active인데 관제 heartbeat가 없으면 무엇을 확인하는가?

정답: 프로세스 상태만 반복 확인하지 않고 운영 인터페이스의 global IPv4 주소, 기본 경로,
Zenoh remote bridge route와 새 RobotStatus uptime 순서로 확인한다.
