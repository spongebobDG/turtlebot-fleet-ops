# Phase 8: 웹 수동 조종·순찰·매핑·원인 분석 설계

## 상태

로봇 없는 환경의 구현과 자동 검증, TB1 목적지 yaw·평활화 실차 검증은 완료했다. 물리 환경에서
deadman 단절 정지, 지도 저장 산출물, 순찰 반복, 장애 복구와 10분 자원을 확인하기 전에는
Phase 8을 완료로 표시하지 않는다.

## 목표

Phase 8은 한 화면의 TB1 관제에 다음 운영 경로를 추가한다.

- 목적지마다 반드시 최종 방향을 지정한다.
- Nav2 명령을 20 Hz로 보간해 저속 이동을 부드럽게 만든다.
- 누르고 있는 동안만 동작하는 수동 조종을 제공한다.
- 방향을 포함한 여러 웨이포인트를 순서대로 반복 순찰한다.
- 웹에서 매핑·주행 프로필을 안전하게 전환하고 지도와 pose graph를 저장한다.
- ROS 2 로그 이상 점수에 사람이 이해할 수 있는 원인·근거·권장 조치를 연결한다.

대상은 계속 `tb1` 한 대다. TB2, 인증·TLS·RBAC, 자율 지도 갱신은 이 Phase의 범위가 아니다.

## 전체 데이터 흐름

```text
Web dashboard
  ├─ destination/waypoint (x, y, yaw) ──> Gateway ──> NavigateRobot
  ├─ deadman manual session ────────────> Gateway ──> ManualCommand
  ├─ MAPPING/NAVIGATION/save ───────────> Gateway ──> profile manager
  └─ incident view <──────────────────── raw JSONL + Production model registry

NavigateRobot/Nav2 ──> /motion/navigation/cmd_vel ─┐
ManualCommand ───────> /motion/manual/cmd_vel ─────┼─> motion arbiter
                                                    └─> /safety/cmd_vel_in
                                                         └─> watchdog ─> /cmd_vel
```

Nav2와 수동 조종 모두 watchdog을 우회하지 않는다. Zenoh allowlist에도 속도 토픽을 넣지 않고
명령 서비스와 상태만 전달한다.

## 목적지 방향과 평활화

지도에서 목표점을 클릭한 뒤 12 px 이상 드래그해야 방향이 유효해진다. 숫자로 입력할 때는
유한한 yaw 값을 라디안으로 받으며 UI에는 라디안과 도를 함께 표시한다. 방향 없는 목표는
전송 버튼을 활성화하지 않는다. 웨이포인트에도 같은 규칙을 적용해 각 지점의 도착 자세를
고정한다.

Nav2 controller는 TB1 자원에 맞춘 5 Hz로 계산하고 `nav2_velocity_smoother`가 20 Hz로 보간한다. 정상
controller 출력과 spin·backup 같은 recovery 출력도 모두 smoother 입력을 공유한다.

| 항목 | 값 |
| --- | --- |
| 최대 선속도 | `0.05 m/s` |
| Nav2 최대 각속도 | `0.27 rad/s` |
| 최대 선가속도/감속도 | `0.08 / -0.12 m/s²` |
| 최대 각가속도/감속도 | `0.6 / -0.8 rad/s²` |
| 피드백 방식 | `OPEN_LOOP` |
| 명령 timeout | `0.5 s` |

이 제한은 이미 검증한 watchdog 상한과 같거나 더 보수적이다. 평활화는 속도 계단을 줄일 뿐
watchdog의 timeout, e-stop, Publisher 단일 소유권을 바꾸지 않는다.

경로가 현재 차체 방향과 거의 반대일 때 DWB가 양쪽 회전을 번갈아 선택하지 않도록 Humble의
`RotationShimController`를 DWB 앞에 둔다. 0.15m 앞의 경로 heading과 0.6rad 이상 차이가 나면
0.2rad/s로 먼저 정렬하고 0.35rad 안에서 DWB에 넘긴다. 최종 목적지 yaw는 기존 goal checker와
DWB가 맞춘다. Nav2 명령은 0.27rad/s로 제한해 watchdog의 0.3rad/s 한도 아래에 응답 여유를 둔다.

## Deadman 수동 조종

브라우저는 버튼을 누를 때 수동 세션을 만들고 100 ms마다 동일 세션 ID로 명령을 갱신한다.
버튼을 놓거나 포인터가 취소되거나 창이 focus를 잃거나 페이지가 종료되면 세션 삭제를
요청한다. 삭제 요청 자체가 유실되더라도 TB1의 `manual_control_node`가 마지막 명령 후
`0.35 s`에 0을 발행하고 arbiter를 `IDLE`로 되돌린다.

서버는 `linear.x`와 `angular.z`만 허용하고 각각 `0.05 m/s`, `0.3 rad/s`로 clamp한다.
e-stop, offline, ERROR, stale profile, MAPPING이 아닌 프로필, 활성 navigation/patrol 또는
미재무장 상태에서는 세션을 거부한다. WARN은 기존 확인 절차를 그대로 사용한다.

## 순찰 상태 모델

순찰은 SQLite에 순찰 정의와 순서가 있는 웨이포인트를 저장한다. 실행 worker는 한 번에 하나의
`NavigateRobot` 목표만 보내고 성공한 뒤 dwell 시간을 거쳐 다음 지점으로 진행한다. 지정한
loop 수를 완료하면 순찰 상태가 `COMPLETED`가 된다. 각 내부 `NavigateRobot` 목표는
`SUCCEEDED`여야 다음 지점으로 진행한다.

다음 원칙을 지킨다.

- 새 순찰은 기존 목표를 자동 교체하지 않는다.
- 어느 한 웨이포인트라도 실패하면 전체 순찰을 실패 처리한다.
- 취소는 현재 action 목표를 취소하고 남은 지점을 실행하지 않는다.
- Gateway 재시작 시 실행 중이던 순찰을 실패로 정리하며 자동 재개하지 않는다.
- 각 웨이포인트는 지도 내부의 free cell이고 유한한 `map` 좌표와 yaw여야 한다.

## 매핑 프로필 관리

`profile_manager_node`는 navigation/mapping launch와 독립된 user service로 상시 실행한다.
`SetOperatingProfile`은 `IDLE`, `MAPPING`, `NAVIGATION`만 허용하고 systemd user unit을
상호 배타적으로 전환한다. 전환 전에 Gateway가 e-stop을 확인하므로 프로필 변경만으로 로봇이
출발할 수 없다.

- `MAPPING`: SLAM Toolbox async, arbiter, manual control을 실행하고 Nav2/AMCL은 실행하지 않는다.
- `NAVIGATION`: 저장 지도, AMCL, Nav2, navigation agent, manual control을 실행한다.
- `IDLE`: 두 운영 launch를 모두 중지한다.

지도 저장은 `%h/.local/share/turtlebot-fleet-ops/maps/tb1/`의 고정 파일명에 map yaml/pgm과
pose graph를 함께 저장한다. overwrite 의사를 명시하지 않으면 기존 파일을 덮어쓰지 않는다.
실제 공간 지도는 Git에 넣지 않는다.

## ROS 2 로그 원인 분석과 MLOps 경계

기존 수집 → window 집계 → candidate 학습 → gate → Production 승격 → 추론 흐름은 유지한다.
새 incident API는 최근 raw JSONL에서 규칙 기반 증거를 추출하고 Production 모델 상태를 함께
표시한다. 분류 범주는 localization/TF, collision clearance, navigation progress,
network lease, sensor data, process restart, resource pressure, safety stop이다.

각 incident는 다음을 반환한다.

- 원인 후보와 confidence
- 판단에 사용한 node/logger/message 증거
- 작업자가 확인할 권장 조치
- 연결된 Production model 버전과 이상 상태

이 기능은 진단 보조다. 모델이나 규칙이 스스로 e-stop을 해제하거나 명령을 재시도하거나
프로필을 바꾸지 않는다. 원본 로그와 deterministic safety state가 최종 근거다.

## 공개 HTTP 인터페이스

| API | 동작 |
| --- | --- |
| `POST /api/robots/{id}/manual/sessions` | deadman 세션 시작 |
| `PUT /api/robots/{id}/manual/sessions/{session_id}` | 속도 갱신 |
| `DELETE /api/robots/{id}/manual/sessions/{session_id}` | 즉시 정지·세션 종료 |
| `POST /api/robots/{id}/profiles/{profile}` | IDLE/MAPPING/NAVIGATION 전환 |
| `POST /api/robots/{id}/mapping/save` | map과 pose graph 저장 |
| `POST /api/robots/{id}/patrols` | 웨이포인트 순찰 정의 생성 |
| `POST /api/patrols/{patrol_id}/run` | 순찰 실행 |
| `DELETE /api/patrols/{patrol_id}` | 순찰 취소 |
| `GET /api/mlops/ros2-logs/incidents` | 원인·증거·권장 조치 조회 |

## 로봇 없는 검증과 남은 실차 검증

로봇 없는 검증은 좌표·origin 회전, UI 최종 방향 계약, 서비스 상태 코드, manual timeout,
순찰 성공·취소·재시작 정리, profile allowlist, 원인 분류, fake Nav2와 실제 Nav2 robotless stack,
분리 DDS domain Zenoh action을 포함한다. smoke에서는 최종 `/cmd_vel` Publisher가 watchdog
하나뿐이고 속도 상한과 정지 0이 유지되는지도 검사한다.

실차 deadman과 통신 프로세스 종료 시험에서는 단일 명령 갱신 중단, Gateway `SIGKILL`, control
Zenoh bridge `SIGKILL` 뒤 최종 `/cmd_vel` non-zero가 각각 0.301초, 0.304초, 0.305초에 끝났다.
세 경우 모두 arbiter는 `IDLE`로 돌아갔고 복구 뒤 이전 session을 재개하지 않았다.
관제 PC는 Windows Time을 외부 NTP에 고정해 offset을 +0.604초에서 +0.003초로 보정했고, 새
Zenoh bridge 실행을 70초 감시하는 동안 timestamp rejection과 ERROR가 발생하지 않았다.

다음 항목은 아직 실차에서만 완료할 수 있다.

1. 새 환경 매핑, map/pose graph 저장, navigation 재기동과 AMCL 정합
2. 여러 방향의 웨이포인트 순찰, 명시적 취소, 재시작 후 비재개
3. 남은 실제 오류 로그가 incident 원인·근거와 연결되는지 확인
4. 10분 주행 CPU·메모리와 watchdog 단일 `/cmd_vel` Publisher 확인

남은 예상 실차 시간은 새로운 결함이 없을 때 2~3시간이다. localization 또는 Zenoh 문제를 다시
조정해야 하면 1~2시간의 여유가 더 필요하다.
