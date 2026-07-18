# Phase 6 설계: TB1 작업·고장·감사 기록

## 범위와 상태

현재 범위는 TB1 한 대뿐이다. TB2 선택, 작업 자동 할당과 재할당은 구현하지 않는다.
SQLite 저장소, REST, 웹 UI와 custom `NavigateRobot` mock을 구현한 뒤 2026-07-19 실제
TB1에서 성공·취소·retry와 Gateway·navigation agent 재시작의 terminal 연동을 검증했다.
Phase 6는 TB1 수용 시험 완료 상태다.

## 책임 경계

```text
RobotStatus / NavigationStatus / SafetyStatus
                    |
             StatusRegistry
                    |
          transition observer
                    v
             OperationsStore
          / faults / tasks / events
                    |
          FastAPI + Web Dashboard
                    |
         NavigationTaskManager
                    |
        기존 NavigateRobot adapter
```

`StatusRegistry`는 최신 상태와 freshness를 담당한다. `OperationsStore`는 시간이 지나도 남아야
하는 작업, 고장 전이와 감사 이벤트를 담당한다. SQLite 실패가 ROS 상태·안전 callback을
막지 않도록 observer는 best-effort로 분리한다. 명령 실행은 기존 Gateway action adapter를
재사용해 lease와 e-stop 경계를 우회하지 않는다.

## 영속 데이터

기본 파일은 `~/.local/share/turtlebot-fleet-ops/operations.sqlite3`이며
`FLEET_OPERATIONS_DB`로 개발·테스트 파일을 분리할 수 있다. DB는 WAL journal을 사용한다.

| 테이블 | 용도 |
| --- | --- |
| `tasks` | 목표 pose, 상태, attempt, 원 작업, command ID와 마지막 메시지 |
| `faults` | robot ID·fault code별 활성 여부, 최초·최근 감지와 해제 시각 |
| `events` | 작업·안전·위치추정·고장 전이의 append-only 감사 기록 |

반복 heartbeat는 이벤트로 저장하지 않는다. 같은 fault가 계속 들어오면 `last_seen`만 갱신하고
발생, 심각도 변경, 해제 때만 event를 추가한다. 그래서 통신 주기와 운영 사건 수가 섞이지 않는다.

## 작업 상태 머신

```text
CREATED -> STARTING -> ACTIVE -> SUCCEEDED
   |          |          |  \-> CANCELED
   |          |          \----> FAILED
   \----------> CANCELED

FAILED or CANCELED --retry--> 새 CREATED task (attempt + 1)
```

재시도는 기존 row를 CREATED로 되돌리지 않는다. 새 `task_id`와 증가한 attempt를 만들고
`parent_task_id`로 원 작업을 연결한다. 과거 실패 원인과 재시도 결과를 동시에 보존하기 위해서다.

task 실행 전에도 기존 navigation REST와 같은 online, ERROR/WARN, map free cell, Nav2·AMCL,
e-stop, motion armed와 활성 목표 검사를 적용한다. task manager는 두 번째 활성 작업을 거부한다.
adapter가 goal을 거부하거나 command ID를 주지 않으면 task를 `FAILED`로 닫는다.
취소 API의 202 응답은 요청 접수이며 로봇의 terminal 상태와 동일 시점이 아니다. 다음 목표는
`NavigationStatus.active_command_id`가 비워질 때까지 기존 중복 목표 검사로 차단한다.

Gateway 프로세스가 재시작되면 이전 프로세스가 가진 ROS action handle에는 다시 연결할 수
없다. 시작 시 DB의 `STARTING`과 `ACTIVE` task를 `FAILED`로 닫고 감사 event를 남긴다. 이
처리는 반복 실행해도 이미 terminal인 task를 바꾸지 않는다. 새 Gateway는 이전 lease도
재개하지 않으므로 로봇 agent가 2초 안에 목표를 취소한다. navigation agent 자체가 재시작해
`UNAVAILABLE`과 빈 command ID를 알릴 때도 대응하는 `ACTIVE` task를 `FAILED`로 닫는다.

## HTTP 인터페이스

- `GET /api/events?robot_id=tb1&limit=100`
- `GET /api/robots/tb1/faults?include_cleared=false`
- `GET /api/tasks`, `GET /api/tasks/{task_id}`
- `POST /api/robots/tb1/tasks`
- `POST /api/tasks/{task_id}/run`
- `DELETE /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/retry`

지도 목적지 API는 즉시 goal을 보내는 저수준 운영 경로로 유지한다. task API는 생성과 실행을
분리해 작업자가 목표를 저장·검토한 뒤 실행할 수 있게 한다.

## 로봇 없는 검증 경계

`weekend_mock.launch.py`는 RobotStatus, NavigationStatus, SafetyStatus, OccupancyGrid,
e-stop·초기 위치 서비스와 `NavigateRobot` action을 제공한다. 성공, 긴 목표 취소, 음수 X
실패, retry, fault 발생·해제와 audit 조회를 검증한다. mock은 모터, LiDAR, DDS/Wi-Fi 지연,
watchdog 물리 정지와 Raspberry Pi 부하의 증거가 아니다.

## 완료 조건

- 저장소 재개방 뒤 task와 fault history가 유지된다.
- 중복 heartbeat가 fault event를 증폭하지 않는다.
- 작업 성공·취소·실패·retry가 REST, DB와 웹에서 일치한다.
- Gateway·navigation agent 재시작 뒤 비종료 task가 자동 재개되지 않고 `FAILED`로 남는다.
- mock REST·WebSocket·Action smoke와 Humble 전체 테스트가 통과한다.
- 실제 TB1 목표의 terminal NavigationStatus가 같은 task 상태로 남는다.

로봇 없는 항목은
[Humble CI run 29601662765](https://github.com/spongebobDG/turtlebot-fleet-ops/actions/runs/29601662765)에서
검증했다. 마지막 TB1 연동 항목도 성공·취소·retry, Gateway 재시작과 navigation agent
강제 종료를 실제 TB1에서 실행해 충족했다. 재부팅 뒤에는 Wi-Fi가 준비된 다음 ROS·Zenoh가
시작되도록 network gate를 추가했고, 관제 재시작 없이 heartbeat 복구와 무재개를 확인했다.
실제 결과는
[Phase 6 TB1 작업·복구 수용 시험](../learning-log/2026-07-19-phase-6-tb1-operations-acceptance.md)에 있다.
