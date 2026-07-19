# Phase 5 설계: TB1 로컬 Nav2와 웹 목적지 제어

## 상태

코드와 자동 테스트를 구현하고 Ubuntu 22.04 ROS 2 Humble CI와 현재 관제 PC에서
6개 패키지 빌드, 당시 격리 domain 142의 189개 테스트와 실제
Nav2·AMCL·Gateway·watchdog policy·watchdog guard를 함께 실행하는
[robotless smoke](https://github.com/spongebobDG/turtlebot-fleet-ops/actions/runs/29585666278)를
통과했다. 별도의 robot/control domain에서 Zenoh 1.9.0만 통신 경로로 사용해
`NavigateRobot` 목표·feedback·result·cancel과 lease/status를 왕복하는
[action smoke](https://github.com/spongebobDG/turtlebot-fleet-ops/actions/runs/29587499227)도
통과했다. 현재 PC에는 WSL2·Humble·Zenoh·Gateway와 Windows 로그인 자동 시작도
구성했다.

2026-07-19에는 TB1에서 지도와 pose graph 저장, AMCL 정합, 웹 목표 성공·취소·WARN,
e-stop, 2초 lease 만료, agent·Nav2·arbiter·watchdog 장애와 10분 자원 표본을 실행했다.
최종 `/cmd_vel` Publisher를 C++ guard 하나로 고정하고 guard 재시작도 중립 입력 전에는
비영점 명령을 차단하도록 보강한 뒤 회귀 테스트와 실차 재시험을 통과했다. 이후 source scope를
감사한 최신 기준은 관제 PC 격리 Humble 191개와 TB1 현재 소스 패키지 144개다. 과거 TB1
`223` 합계에는 삭제된 패키지의 build 잔여 결과가 포함됐으며 최신 완료 수치에는 사용하지 않는다. 이 증거로
Phase 5를 완료로 판정한다. 저상 장애물 LiDAR 사각과 반복 큰 방향 전환에서 관찰한
recovery·stale 취소는 완료를 숨기지 않는 운영 제한으로 별도 기록한다.

## 책임 경계

```text
Browser
  | REST goal / cancel / initial pose
Fleet Gateway (WSL)
  | NavigateRobot action + NavigationLease (0.5 s)
Zenoh ROS 2 bridge
  |
navigation_agent (TB1) ------> Nav2 NavigateToPose
  | authorization                 |
  |                         /motion/navigation/cmd_vel
  +-------------------------------+
                    |
             motion_arbiter
                    | /safety/cmd_vel_in
        safety_watchdog_policy (Python)
                    | /safety/watchdog_cmd_vel
         safety_watchdog guard (C++)
                    | /cmd_vel
             TurtleBot3 base
```

Gateway는 명령 식별자와 lease를 소유한다. `navigation_agent`는 로컬 안전 상태와
lease를 확인하고 Nav2 목표를 소유한다. `motion_arbiter`는 입력 출처를 하나만
고른다. Python `safety_watchdog_policy`는 e-stop, dead-man timeout과 중립 재무장을
판정한다. 별도 C++ `safety_watchdog` guard는 policy 입력을 0.25초 안에 받지 못하면 0을
발행하고 속도 상한과 시작 후 중립 조건을 다시 적용한다. 실제 `/cmd_vel`의 유일한 정상
publisher는 C++ guard다.

## 상태 머신

`NavigationStatus`는 다음 상태를 사용한다.

| 상태 | 의미 |
| --- | --- |
| `UNAVAILABLE` | 지도, Nav2 또는 필수 상태가 준비되지 않음 |
| `IDLE` | 목표가 없고 아직 위치추정 준비 전 |
| `LOCALIZING` | 초기 위치를 발행했고 새 AMCL pose를 기다림 |
| `READY` | 지도, ACTIVE Nav2 lifecycle, AMCL, RobotStatus와 안전 상태가 모두 최신 |
| `ACTIVE` | 하나의 NavigateRobot/Nav2 목표 실행 중 |
| `SUCCEEDED` | 목표 성공 |
| `CANCELED` | 작업자, e-stop 또는 안전 상태로 취소 |
| `FAILED` | Nav2 거부 또는 실패 |
| `LEASE_EXPIRED` | 일치하는 Gateway lease가 2초 넘게 오지 않음 |

AMCL 준비는 `/initialpose` 발행 이후에 수신한 새 `/amcl_pose`만 인정한다. 오래된
위치 샘플로 READY가 되는 것을 막기 위해 receipt time을 사용하며, 로봇·안전·AMCL
상태가 stale이면 새 목표를 받지 않는다.
활성 주행 중 robot, safety 또는 localization 상태가 stale이 되어도 authorization을
닫고 목표를 취소한다.

Nav2 action server의 발견만으로는 준비로 간주하지 않는다. `bt_navigator`는 action
endpoint가 graph에 보인 뒤에도 lifecycle이 configure/activate 중일 수 있다. agent는
`/bt_navigator/get_state`가 `PRIMARY_STATE_ACTIVE`를 반환하고 action server도 준비된
경우에만 `nav2_ready=true`를 발행하고 목표를 받는다.

## motion 권한

arbiter mode는 `IDLE`, `MANUAL`, `NAVIGATION` 중 하나다. 매핑 프로필은 MANUAL,
주행 프로필은 시작과 재시작 때 IDLE이다. navigation agent가 목표와 유효한 lease를
모두 보유할 때만 authorization `true`를 10 Hz로 발행한다.

다음 두 시간이 독립적으로 적용된다.

- Gateway lease 만료: 2.0초. agent가 목표를 `LEASE_EXPIRED`로 끝내고 Nav2를 취소한다.
- 로컬 authorization 만료: 0.5초. agent가 죽더라도 arbiter가 0을 출력한다.

arbiter 출력은 policy의 0.5초 timeout과 `0.05 m/s`, `0.3 rad/s` clamp를 통과하고,
그 출력은 다시 C++ guard의 0.25초 timeout과 동일한 clamp를 통과한다.
Humble Nav2 내부에서는 controller가 `cmd_vel_nav`를 만들고 `velocity_smoother`가 최종
Nav2 속도를 만든다. 반면 `behavior_server`의 recovery 동작은 `/cmd_vel`을 직접
발행한다. 저장소 소유 non-composed Nav2 launch는 controller의 `cmd_vel`만
`cmd_vel_nav`로, smoother의 `cmd_vel_smoothed`와 behavior의 `cmd_vel`만
`/motion/navigation/cmd_vel`로 각각 remap한다. 공통 group remap을 쓰지 않으므로
smoother 입력과 출력이 합쳐지지 않으며, 정상 주행과 recovery 어느 쪽도 watchdog을
우회하지 않는다.

## e-stop 순서

Gateway는 watchdog e-stop 서비스 성공을 먼저 기다린다. 그 다음 활성 action
handle을 lease 목록에서 제거하고 취소한다. agent도 `SafetyStatus`를 보고 motion
mode를 IDLE로 바꾸고 downstream Nav2 목표를 취소한다. 취소 응답이 유실되어도
watchdog 0과 lease 만료가 독립적으로 정지를 강제한다.

해제 뒤 watchdog은 `WAITING_NEUTRAL`이다. IDLE arbiter가 보내는 0을 받은 뒤에만
`motion_armed=true`가 되고, 이전 action handle과 lease는 이미 제거되어 자동
재출발하지 않는다.

policy 프로세스 재시작은 `WAITING_NEUTRAL`로 시작한다. C++ guard도 시작·재시작 직후
비영점 입력을 차단하고 중립을 먼저 요구한다. guard는 transient-local 재시작 신호를
발행해 policy를 `WAITING_NEUTRAL`로 되돌린다. 활성 주행 중이었다면 agent가
`motion_armed=false`를 받아 목표와 authorization을 취소하고 arbiter를 IDLE로 만든다.
그 IDLE 0이 두 계층을 재무장하므로 watchdog 복구가 이전 목표를 재개하지 않는다.
agent가 재시작해 이전 command를 더 이상 active로 보고하지 않으면 Gateway도 한 번
확인했던 command의 lease 소유권을 제거해 새 목표가 stale handle에 막히지 않게 한다.
action accept 직후 agent가 종료되어 active 상태를 한 번도 확인하지 못한 경우에도
Gateway는 2초 확인 timeout 뒤 lease를 철회하고 cancel을 요청한다.
Nav2 action 서버가 1초 동안 사라지면 agent는 authorization과 motion mode를 철회하고
custom 목표를 `FAILED`로 끝내므로, 사라진 downstream result를 무기한 기다리지 않는다.

Nav2 `SimpleProgressChecker`는 odom 이동량을 기준으로 한다. 바퀴 미끄러짐이나 위치추정
불일치로 odom만 움직이고 map pose가 목표에 가까워지지 않는 경우에는 실패를 감지하지 못할 수
있다. navigation agent는 이 경계를 보완해 Nav2 feedback의 `distance_remaining`과 map-frame
현재 yaw가 목표 오차를 실제로 줄이는지 독립적으로 감시한다. 거리 0.05m 또는 yaw 0.1rad 이상의
개선이 20초 동안 없거나, feedback이 3초 동안 끊기거나, 한 목표가 180초를 넘으면 downstream
Nav2 goal을 취소하고 custom action을 `FAILED`로 닫은 뒤 arbiter를 `IDLE`로 돌린다. recovery
횟수가 증가하면 새 20초 진척 창을 한 번 부여하지만 180초 절대 상한은 늘어나지 않는다.

## 지도와 좌표 계약

지도 REST 응답은 `width`, `height`, `resolution`, `origin {x,y,yaw}`와 ROS
OccupancyGrid 행 우선 `data`를 그대로 제공한다. 값 범위는 `-1..100`이다. 지도는
WebSocket snapshot에 넣지 않고 페이지가 선택한 로봇에 대해 한 번 가져온다.

world 좌표를 cell로 바꿀 때 origin translation 뒤에 `-origin_yaw` 회전을 적용하고
resolution으로 나눈다. 지도 밖, unknown(-1), 또는 0보다 큰 셀은 초기 위치와
목표 모두 거부한다. 브라우저 canvas도 같은 origin 회전을 적용하며 y축 화면 반전을
별도로 처리한다.

## ROS 2 공개 인터페이스

- action: `/tb1/navigation/navigate` (`NavigateRobot`)
- services: `/tb1/navigation/set_initial_pose`,
  `/tb1/navigation/set_motion_mode`
- fleet topics: `/fleet/navigation_status`, `/fleet/navigation_lease`,
  `/fleet/safety_status`
- velocity: `/motion/manual/cmd_vel`, `/motion/navigation/cmd_vel`,
  `/safety/cmd_vel_in`, `/cmd_vel`

ROS 2 Humble의 `NavigateToPose` result에는 상세 Nav2 error code가 없다. 따라서
`NavigateRobot`의 outcome과 ROS action status로 성공·취소·실패를 보존하고,
`nav2_error_code`는 Humble에서 0이다. 새 배포판에서 필드가 존재하면 agent가 값을
전달하도록 호환 코드를 사용한다.

## HTTP 정책

- `GET /api/robots/{id}/map`
- `PUT /api/robots/{id}/localization/initial-pose`
- `POST /api/robots/{id}/navigation/goals`
- `DELETE /api/robots/{id}/navigation/goals/{command_id}`

잘못된 지도 좌표는 422, 운용 상태 충돌은 409, ROS adapter 부재나 timeout은 503이다.
ERROR, offline, stale 상태, e-stop, 미재무장, 활성 목표는 새 목표를 막는다. WARN은
fault 목록을 보여준 뒤 `confirm_warnings=true`로 다시 보낸 경우에만 허용한다.

## 운영 프로필과 데이터

`tb1-mapping.service`와 `tb1-navigation.service`는 상호 `Conflicts=` 관계다. 지도와
pose graph는 `~/.local/share/turtlebot-fleet-ops/maps/tb1/`에 두며 Git에 넣지 않는다.
Nav2 프로세스와 arbiter·두 watchdog 계층은 실패 시 재시작한다. agent가 종료되면 개별
node respawn 대신 navigation launch 전체를 종료하고 systemd가 전체 프로필을 다시
시작한다. agent startup hook은 motion을 IDLE로 만들고 모든 잔존 Nav2 goal을 취소한
뒤에만 ready를 허용한다. systemd `ExecStartPost`는 로봇 Zenoh bridge도 재시작해 재생성된
service·action endpoint 경로를 갱신한다.

Nav2의 전체 plugin 구성은 설치된 TurtleBot3 Humble Burger 기준 파일을 사용하고,
저장소 소유 `tb1_nav2_rewrites.yaml`로 DWB/recovery 속도와 progress checker 값을
고정한다. 최종 watchdog은 이 설정과 독립적으로 같은 속도 상한을 다시 강제한다.

## 완료 조건

자동 테스트는 Python world↔cell과 브라우저 world↔canvas 좌표 회전, 셀 정책,
API 409/422, WARN 확인, fake Nav2 성공·거부·feedback·취소·실패, Gateway lease 주기,
lease 만료, authorization 만료, e-stop, guard 입력 timeout과 재시작 취소를 다룬다. 고정된
feedback을 계속 내보내는 fake Nav2로 map-frame 진척 timeout, downstream cancel, `FAILED`,
motion `IDLE` 복귀도 검사한다.
robotless smoke는 실제 Humble Nav2·AMCL·agent·arbiter·두 watchdog 계층·Gateway를
합성 map/TF/scan/odom과 함께
띄워 HTTP 성공·취소·e-stop, 속도 상한과 `/cmd_vel` publisher 단일성을 검사한다.
Zenoh smoke는 DDS domain 160과 161을 분리해 직접 discovery를 차단하고 Zenoh 1.9.0
브리지 사이에서 custom action의 goal·feedback·성공 result·cancel과
`NavigationLease`·`NavigationStatus`가 모두 전달되는지 검사한다.

실차 완료 증거는 [실차 절차](../setup/tb1-navigation.md)와
[수용 시험 일지](../learning-log/2026-07-19-phase-5-tb1-navigation-acceptance.md)에 기록했다.
핵심 결과는 단일 `/cmd_vel` Publisher, 0.05 m/s·0.3 rad/s 상한, lease 단절 후
2.112초의 0 출력과 2.263초의 `LEASE_EXPIRED`, e-stop 비영점→0 0.003초, explicit cancel
0.978초, guard 장애 후 0.955초와 무재개다. 10분 표본에서 CPU와 메모리의 90% 경고는
지속되지 않았다.

## 참고 기준

- [Nav2 mapping/localization setup](https://docs.nav2.org/setup_guides/sensors/mapping_localization.html)
- [Zenoh ROS 2 DDS bridge와 action 지원](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds)
- [TurtleBot3 Navigation](https://emanual.robotis.com/docs/en/platform/turtlebot3/navigation/)
- [Humble NavigateToPose action 계약](https://github.com/ros-navigation/navigation2/blob/humble/nav2_msgs/action/NavigateToPose.action)
- [Humble Nav2 navigation launch와 속도 remap](https://github.com/ros-navigation/navigation2/blob/humble/nav2_bringup/launch/navigation_launch.py)
- [ROS 2 static remap 적용 순서](https://design.ros2.org/articles/static_remapping.html#order-of-applying-remapping-rules)
