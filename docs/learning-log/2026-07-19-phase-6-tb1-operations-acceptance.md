# 학습 일지: Phase 6 TB1 작업·복구 실차 수용 시험

날짜: 2026-07-19

단계: Phase 6

진행 상태: TB1 실차 수용 시험 완료

## 오늘의 목표

로봇 없이 구현한 task·fault·event 기능을 실제 TB1의 `NavigateRobot`, lease, Nav2 terminal
상태와 연결한다. 작업 성공·취소·retry뿐 아니라 Gateway·navigation agent 재시작과 TB1
재부팅에서 이전 작업이 자동 재개되지 않는지 확인한다.

## 검증 환경과 원칙

- 대상: TB1 한 대, ROS 2 Humble domain 42
- 통신: TB1과 관제 PC의 Zenoh ROS 2 DDS bridge
- 저장: 관제 PC의 SQLite operations DB
- 지도: Phase 5에서 저장한 실제 지도와 pose graph
- 안전: 한 번에 한 목표 또는 한 장애만 주입하고 시험 종료 시 e-stop·0속도 유지
- 보안: 정확한 사설 IP와 Wi-Fi 정보는 기록하지 않음

## 작업 수명주기 결과

SQLite와 `GET /api/tasks`에서 총 여섯 attempt의 이력이 재시작 뒤에도 유지됐다.

| 시나리오 | 결과 |
| --- | --- |
| 실행 전 취소 | `CANCELED`, command ID 없음 |
| 취소 작업 retry | 새 task, attempt 2, parent 연결, 실제 목표 `SUCCEEDED` |
| 실행 중 명시적 취소 | task와 NavigationStatus 모두 `CANCELED`, active command 해제 |
| 취소 작업 retry | 새 attempt가 recovery 0으로 `SUCCEEDED` |
| ACTIVE 중 Gateway 재시작 | task `FAILED`, 새 Gateway가 이전 lease·action을 재소유하지 않음 |
| ACTIVE 중 navigation agent 강제 종료 | task `FAILED`, systemd 재시작 뒤 빈 command ID와 0속도 |

Gateway 재시작 시 로봇의 downstream Nav2가 이미 terminal에 도달한 경우도 있었다. 그러나 새
Gateway는 이전 action handle의 소유자가 아니므로 downstream 결과를 자기 task 성공으로
소급하지 않고 `Fleet Gateway restarted; prior task will not resume`로 실패 처리했다. 이는
결과를 잃은 것이 아니라 소유권이 불명확한 작업을 성공으로 추정하지 않는 fail-closed 정책이다.

navigation agent 강제 종료 시험에서는 systemd의 새 MainPID와 restart count 증가를 확인했다.
task는 `Navigation agent restarted; prior task will not resume` 메시지로 `FAILED`가 됐고,
10초 동안 active command가 다시 생기지 않았다.

## 영속 기록과 무재개

Gateway를 재시작한 뒤에도 과거 성공·취소·실패 task, retry의 `attempt`와 `parent_task_id`, fault와
event가 다시 조회됐다. 재시작 시점의 비종료 task만 실패로 닫혔으며 이미 terminal인 행은
바뀌지 않았다.

TB1 재부팅 뒤 20개 snapshot을 0.5초 간격으로 표본화한 결과는 다음과 같다.

```text
active tasks: 0
active command observed: false
max |linear velocity|: 0.000485 m/s
max |angular velocity|: 0.000312 rad/s
```

값은 odometry 정지 잡음 수준이며 실제 `/cmd_vel` 메시지는 모든 축 0이었다.

## 재부팅에서 발견한 실제 결함

첫 재부팅에서는 systemd unit이 active여도 Gateway heartbeat가 돌아오지 않았다. TB1의
Zenoh·ROS 프로세스가 Wi-Fi 주소와 기본 경로가 생기기 전에 시작되어 DDS가 잘못된 네트워크
상태에 바인딩된 것이 원인이었다. 관제 PC 서비스를 재시작하는 것은 증상을 우회할 뿐 로봇
부팅 순서를 보장하지 못했다.

다음 보강을 적용했다.

1. `tb1-network-ready.service` oneshot 추가
2. 기본 IPv4 경로와 global IPv4 주소가 생길 때까지 무기한 대기
3. bringup, watchdog, agent, Zenoh, mapping, navigation의 `After`와 `Wants`에 gate 추가
4. 배포·preflight·systemd validator·회귀 테스트에 새 unit 포함

재배포 뒤 TB1을 다시 재부팅했다. 재부팅 요청 약 50초 후 Wi-Fi SSH가 복구됐고 network gate는
실제 `wlan0` 주소 준비를 기록했다. 관제 PC Gateway와 Zenoh를 재시작하지 않은 상태에서 uptime
60초인 새 RobotStatus가 online=true, heartbeat age 약 0.35초로 들어왔다. core와 navigation
unit은 active, mapping은 inactive였고 active command는 없었다. 초기 위치를 다시 적용하자
AMCL pose `(-0.987, -0.195, 2.795)` 부근에서 `READY`가 됐다.

## 배포 테스트 경합과 수치 감사

네트워크 gate 첫 배포에서 전체 테스트 한 건이
`Safety status became unavailable or stale`로 취소됐다. 같은 navigation package를 단독 실행하자
87개가 모두 통과했다. 새 정적 회귀 테스트를 포함한 재실행에서는 navigation 88개가 통과했다.
Raspberry Pi에서 여러 패키지 테스트를 병렬 실행해 safety heartbeat가 지연된 것이 원인이었다.

안전 freshness timeout을 늘리지 않고 TB1 acceptance만 `--executor sequential`로 바꿨다. 또한
`colcon test-result`를 선택한 현재 package의 `build/<package>`로 한정했다. 그 결과 현재 소스
다섯 패키지는 다음처럼 통과했다.

```text
fleet_interfaces: 0
safety_watchdog_guard: 5
safety_watchdog: 18
robot_agent: 33
navigation_agent: 88
total: 144 tests, 0 errors, 0 failures, 0 skipped
```

이 과정에서 과거 문서의 TB1 `223` 또는 직전 전체 출력 `224`에는 이미 소스에서 제거된
`fleet_navigation` build 디렉터리의 과거 결과가 섞였음을 발견했다. 당시 명령의 출력 자체는
보존하되 최신 완료 수치는 현재 소스 범위 144개로 정정한다. 관제 PC는 Gateway 46개를 포함해
전체 191개다. 테스트 합계도 source scope를 명시하지 않으면 품질 지표가 부풀 수 있다는 점을
배웠다.

관제 PC 최종 회귀의 첫 build에서는 병렬로 시작한 `robot_agent`의 Python 3.10 프로세스가
출력 없이 종료됐다. WSL kernel log에 해당 PID의 general protection fault와 signal 11이
기록됐고, 같은 `setup.py --help-commands`를 단독 실행하면 정상 통과했다. 메모리와 디스크도
충분했으므로 제품 코드 실패가 아니라 이 PC의 병렬 Python subprocess 불안정으로 판정했다.
로컬 `verify_workspace.sh`의 build도 순차화해 재현성을 높였고, 이후 전체 검증 결과로 최종
판정했다.

## 완료 판정

- [x] 실제 task 성공·실행 중 취소·retry lineage
- [x] SQLite 재개방과 Gateway 재시작 뒤 이력 유지
- [x] Gateway 재시작 중 ACTIVE task 실패·무재개
- [x] navigation agent 강제 종료 뒤 systemd 복구·실패·무재개
- [x] TB1 재부팅 뒤 Wi-Fi→ROS·Zenoh 자동 복구
- [x] 재부팅 뒤 active task·command 0, 관제 수동 재시작 없음
- [x] 실제 지도 초기 위치 재적용 뒤 `READY`
- [x] TB1 source-scoped 144개 테스트 통과
- [x] 최종 e-stop 성공과 `/cmd_vel=0`

이 증거로 Phase 6와 현재 문서에 정의한 TB1 단일 로봇 MVP 수용 시험을 완료로 판정한다.
TB2, 다중 로봇 자동 할당과 저상 장애물 센서 보강은 후속 범위다.

## 배운 점

1. `systemd active`는 네트워크가 올바르게 준비됐다는 뜻이 아니다.
2. 프로세스 재시작 뒤 action 소유권을 복원할 수 없으면 자동 재개보다 명시적 실패가 안전하다.
3. 취소 HTTP 202와 로봇 terminal 상태는 별도 시점이므로 active command 해제를 확인해야 한다.
4. 안전 통합 테스트의 일시 실패를 timeout 완화로 숨기지 말고 실행 자원 경합을 제거해야 한다.
5. 테스트 합계는 현재 소스 package 범위를 함께 기록해야 재현 가능하다.

## 복습 문제와 정답

### 1. Gateway 재시작 뒤 로봇이 성공 result를 냈는데 task를 왜 성공으로 바꾸지 않는가?

정답: 새 Gateway는 이전 action handle과 lease의 소유자가 아니어서 그 result가 자기 task와
정확히 같은 실행이라는 소유권을 증명할 수 없기 때문이다. 실패로 닫고 명시적 retry를 만든다.

### 2. `network-online.target` 뒤에도 왜 별도 network gate가 필요한가?

정답: target 도달만으로 운영 인터페이스의 global IPv4 주소와 기본 경로가 실제 준비됐다고
보장할 수 없기 때문이다. ROS DDS와 Zenoh가 바인딩되기 전에 두 조건을 직접 확인한다.

### 3. 단독 테스트는 통과하고 병렬 전체 테스트만 실패하면 무엇을 먼저 의심하는가?

정답: 제품 timeout을 늘리기 전에 CPU·executor 경합으로 heartbeat나 callback scheduling이
지연됐는지 확인한다. 실차 배포 acceptance는 순차 실행해 결정성을 우선한다.

## 관련 커밋

- `bee98ca fix: wait for TB1 network before ROS startup`
- `46766e9 fix: serialize TB1 acceptance tests`
