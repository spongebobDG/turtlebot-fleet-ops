# TB1 작업·감사·재부팅 복구 운영 및 검증

이 절차는 Phase 6의 단일 로봇 task, fault·event 이력과 프로세스·재부팅 복구를 실제 TB1에서
검증한다. 지도 작성과 초기 위치 절차는
[TB1 매핑·Nav2 운영](tb1-navigation.md)을 먼저 따른다. 정확한 사설 IP와 Wi-Fi 정보는
저장소에 기록하지 않는다.

## 1. 시작 전 안전 조건

- 작업자가 전원 스위치에 접근할 수 있는 빈 공간을 사용한다.
- 지도와 pose graph가 TB1의
  `~/.local/share/turtlebot-fleet-ops/maps/tb1/`에 있어야 한다.
- `/cmd_vel` Publisher가 C++ watchdog guard 하나뿐인지 확인한다.
- Gateway snapshot에서 TB1이 online이고 safety·navigation status가 fresh인지 확인한다.
- 초기 위치 적용 전과 프로세스 장애 주입 전에는 활성 task와 active command가 없어야 한다.

```bash
systemctl --user is-active \
  tb1-network-ready.service \
  tb1-bringup.service \
  tb1-safety-watchdog.service \
  tb1-robot-agent.service \
  tb1-zenoh-bridge.service

systemctl --user enable --now tb1-navigation.service
systemctl --user is-active tb1-navigation.service tb1-mapping.service
```

기대값은 navigation `active`, mapping `inactive`다. 웹에서 초기 위치를 적용한 뒤
`NavigationStatus.state=READY`, `active_command_id=""`를 확인한다.

## 2. 작업 API 수명주기

작업 생성과 실행은 분리한다. 아래 좌표는 예시이므로 실제 지도의 free cell로 바꾼다.

```bash
curl -sS -X POST http://localhost:8000/api/robots/tb1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"x": 0.0, "y": 0.0, "yaw": 0.0, "confirm_warnings": false}'

curl -sS -X POST http://localhost:8000/api/tasks/TASK_ID/run
curl -sS http://localhost:8000/api/tasks/TASK_ID
curl -sS -X DELETE http://localhost:8000/api/tasks/TASK_ID
curl -sS -X POST http://localhost:8000/api/tasks/TASK_ID/retry
```

검증 순서는 다음과 같다.

1. 실행 전 task를 취소해 `CANCELED`와 빈 command ID를 확인한다.
2. 취소 task를 retry하고 새 task ID, `attempt=2`, 원 task를 가리키는
   `parent_task_id`를 확인한다.
3. 짧은 목표를 실행해 task와 NavigationStatus가 모두 `SUCCEEDED`인지 확인한다.
4. 다른 짧은 목표를 실행 중 취소하고 둘 다 `CANCELED`인지 확인한다.
5. 같은 목표의 retry가 새 attempt로 성공하는지 확인한다.

`202` 취소 응답만으로 terminal로 판정하지 않는다. `active_command_id`가 비고 task가
terminal 상태가 될 때까지 기다린다. 새 목표가 기존 목표를 자동 교체해서는 안 된다.

## 3. 감사·고장 이력

```bash
curl -sS 'http://localhost:8000/api/events?robot_id=tb1&limit=100'
curl -sS 'http://localhost:8000/api/robots/tb1/faults?include_cleared=true'
curl -sS http://localhost:8000/api/tasks
```

같은 fault heartbeat가 반복돼도 발생 event 수가 계속 늘어나면 안 된다. fault가 해제되면
기존 fault row의 해제 시각과 별도 해제 event가 남아야 한다. Gateway 재시작 뒤에도 이전
task, event와 fault history가 SQLite에서 다시 조회되어야 한다.

## 4. 프로세스 복구 시험

고장 주입은 한 번에 하나만 수행하고 각 시험 뒤 목표 없음과 0속도를 먼저 확인한다.

### Gateway 재시작

ACTIVE task 중 관제 PC에서 Gateway를 재시작한다. 새 Gateway는 이전 ROS action handle과
lease를 소유하지 않으므로 task를 `FAILED`로 닫고 이전 목표를 재개하지 않아야 한다.

```bash
systemctl --user restart fleet-gateway.service
systemctl --user is-active fleet-gateway.service
```

### navigation agent 종료

TB1에서 navigation service의 agent 자식 프로세스만 종료한다. systemd가 profile을 재시작한
뒤 task는 `FAILED`, navigation은 빈 command ID, 속도는 0이어야 한다. 남은 목표를 이어서
실행하면 실패다.

```bash
systemctl --user show tb1-navigation.service -p MainPID -p NRestarts
journalctl --user -u tb1-navigation.service --since '5 minutes ago' --no-pager
```

실제 PID 종료는 현장 수용 시험 스크립트나 승인된 절차에서만 수행한다. 단순 운영 점검 중에는
임의로 프로세스를 종료하지 않는다.

## 5. 재부팅 자동 복구

TB1의 ROS 서비스는 `tb1-network-ready.service` 이후에 시작한다. 이 oneshot은 기본 IPv4
경로와 global IPv4 주소가 모두 생길 때까지 기다린다. `network-online.target`만으로는
실제 Wi-Fi 주소가 준비됐음을 보장하지 못한다.

재부팅 전 e-stop, 빈 active command와 `/cmd_vel=0`을 확인한다. 재부팅 뒤 관제 PC의
Gateway와 Zenoh는 재시작하지 않고 다음을 확인한다.

```bash
systemctl --user is-active \
  tb1-network-ready.service \
  tb1-bringup.service \
  tb1-safety-watchdog.service \
  tb1-robot-agent.service \
  tb1-zenoh-bridge.service \
  tb1-navigation.service

journalctl --user -u tb1-network-ready.service -b --no-pager
```

합격 조건은 다음과 같다.

- network gate 로그에 실제 인터페이스와 주소 준비 완료가 기록된다.
- core와 navigation unit은 active, mapping은 inactive다.
- Gateway가 새 uptime을 가진 fresh TB1 snapshot을 다시 받는다.
- active task와 active command가 0개이며 이전 작업이 재개되지 않는다.
- 웹 초기 위치 재적용 뒤 `READY`가 된다.
- 최종 e-stop 상태에서 `/cmd_vel=0`이다.

## 6. 배포 테스트 수치 해석

TB1 acceptance 배포는 현재 소스의 다섯 robot 패키지만 격리 domain 142에서 순차 실행한다.
Raspberry Pi에서 패키지를 병렬 실행하면 통합 테스트의 safety heartbeat가 CPU 경합으로 stale될
수 있으므로 안전 timeout은 늘리지 않고 `--executor sequential`을 사용한다. 결과도 각
`build/<package>` 경로에 한정해 삭제된 과거 패키지의 잔여 결과를 합계에 넣지 않는다.

2026-07-19 최신 실제 결과는 TB1 144개, 관제 PC 전체 191개이며 오류와 실패는 0개다.

## 7. 종료 상태

수용 시험이 끝나면 활성 task와 active command가 없는지 확인하고 e-stop을 활성화한다.
마지막으로 `/cmd_vel` 한 메시지가 모든 축 0인지 확인한다. 이전 목표는 e-stop 해제나 프로세스
재시작만으로 재개되어서는 안 된다.
