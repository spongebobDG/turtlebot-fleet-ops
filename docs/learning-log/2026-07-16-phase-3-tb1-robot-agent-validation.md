# 2026-07-16 Phase 3 TB1 Robot Agent 실차 검증

단계: Phase 3

진행 상태: 완료

브랜치: `feat/phase-3-robot-agent`

검증 revision: `86047b7`

## 오늘의 목표

TB1의 실제 battery, odom, LDS-02와 Linux 자원을 `RobotStatus`로 집계하고, source 중단을
stale fault로 감지한 뒤 bringup 재시작 시 자동 복구되는지 확인한다.

## 직접 SSH 운영 기반 준비

관제 PC에 프로젝트 전용 Ed25519 key를 생성하고 사용자가 공개키만 TB1·TB2에 한 번
등록했다. 비밀번호를 코드, 명령 기록과 Git에 저장하지 않고 두 로봇에 비대화식 SSH가
가능해졌다.

```text
tb1: SSH OK, Phase 3 repository present
tb2: SSH OK, ROS 2 and repository not installed yet
```

## TB1 최신 자동 테스트

직접 SSH로 revision을 pull하고 build·test를 실행했다.

```text
Starting >>> fleet_interfaces
Finished <<< fleet_interfaces
Starting >>> robot_agent
Finished <<< robot_agent
collected 33 items
33 passed, 2 warnings
Summary: 33 tests, 0 errors, 0 failures, 0 skipped
```

## 실행한 구성

Domain 42에서 다음을 백그라운드로 실행했다.

- TurtleBot3 bringup
- Phase 2 Safety Watchdog
- Phase 3 Robot Agent

확인한 노드:

```text
/diff_drive_controller
/ld08_driver
/robot_agent
/robot_state_publisher
/safety_watchdog
/turtlebot3_node
```

Safety Watchdog의 `/cmd_vel` 출력이 모든 축 0인 것을 확인한 뒤 source 중단 시험을
진행했다.

## 정상 상태 결과

`/fleet/robot_status` endpoint는 `robot_agent` Publisher 1개였고 RELIABLE QoS로
확인됐다. 실제 상태 snapshot은 다음과 같았다.

| 항목 | 실제 결과 |
| --- | ---: |
| robot ID / hostname | `tb1` / `tb1` |
| level / faults | `0` / 없음 |
| battery | 86.66%, 12.06V, present |
| odom | received·fresh·valid 모두 true |
| scan | received·fresh·valid 모두 true |
| scan valid points | 162개 |
| nearest scan | 약 0.393m |
| CPU | 37.7% |
| memory | 14.3% |
| disk | 19.0% |
| Wi-Fi | `wlan0`, -35dBm, quality 100% |
| source age | battery 0.007초, odom 0.003초, scan 0.115초 |
| status rate | 평균 1.000 Hz |

CPU와 Wi-Fi 값은 snapshot이므로 실행 시점에 따라 변한다. 이 표는 성능 보장값이 아니라
검증 순간의 실제 증거다.

## Stale 장애 주입

처음에는 백그라운드 `ros2 launch` 부모 PID에 SIGINT를 보냈지만 자식 driver가 계속
실행돼 source가 끊기지 않았다. Agent가 계속 `level=0`을 유지했으며, 장애 조건이 실제로
성립하지 않았으므로 올바른 결과였다.

두 번째 시험에서는 `ld08_driver`와 `turtlebot3_ros` 자식 process에 TERM을 보내 실제
source 발행을 중단했다. 약 8초 후 snapshot은 다음과 같았다.

```text
level: 2
battery_fresh: false
odom_fresh: false
scan_fresh: false
fault_codes:
- ODOM_STALE
- SCAN_STALE
- BATTERY_STALE
```

각 source의 마지막 수신 이후 age는 약 10.8~10.9초였다. Agent transition log는 설정된
timeout 순서를 그대로 보여줬다.

```text
Robot health level=2: ODOM_STALE
Robot health level=2: ODOM_STALE, SCAN_STALE
Robot health level=2: ODOM_STALE, SCAN_STALE, BATTERY_STALE
```

따라서 odom 1초, scan 2초, battery 5초 정책이 실제 process 중단에서도 적용됐다.

## 자동 복구 검증

기존 bringup을 완전히 종료한 뒤 다시 시작했다. LDS-02와 OpenCR source가 재개되자
Agent log가 다음과 같이 바뀌었다.

```text
Robot health level=2: ODOM_STALE, BATTERY_STALE
Robot health OK
```

복구 snapshot은 다시 `level=0`, 세 source received·fresh·valid true, fault 없음이었다.
Robot Agent 자체를 재시작하지 않아도 source 복구를 자동 반영했다.

## 발생한 문제와 해결

### PowerShell에서 WSL/SSH로 전달한 script의 BOM·CRLF

첫 remote start script는 PowerShell pipeline이 BOM과 CRLF를 포함해 Linux bash에서
`set: command not found`와 로그 경로의 `\r` 문제를 만들었다. 실제 ROS process는
시작됐지만 마지막 log 조회가 실패했다. 이후 remote 실행을 단순 SSH 명령으로 분리하고
process와 log를 별도 검증했다. 장기 운영 script는 저장소의 LF 파일로 배포해야 한다.

### Process 선택 pattern이 원격 shell까지 종료

한 SSH 문장 안에 종료 pattern과 동일한 bringup 시작 문자열이 함께 있어 `pkill -f`가
원격 shell도 선택했다. 종료와 시작을 별도 SSH 명령으로 분리해 해결했다. 실무에서는
PID file 또는 systemd unit으로 정확히 관리해야 한다.

## 완료 체크리스트

- [x] TB1 custom interface·Agent build
- [x] TB1 자동 테스트 33개 통과
- [x] 정상 실제 RobotStatus `level=0`
- [x] battery, odom, scan과 last received 확인
- [x] Wi-Fi signal 확인
- [x] 평균 status rate 1.000 Hz
- [x] source 중단 stale fault 확인
- [x] bringup 재시작 후 자동 OK 복구
- [x] 시험 전 Safety Watchdog 0 출력 확인

## 다음에 할 일

Phase 3 PR을 최종 리뷰하고 main에 squash merge한다. 이후 Phase 4에서 관제 PC에 Fleet
Gateway와 최소 FastAPI REST·WebSocket·HTML dashboard를 만들고, RobotStatus heartbeat
age로 TB1 online/offline을 판정한다.
