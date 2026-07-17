# Phase 5 설계: TB1 로컬 Nav2와 웹 목적지 제어

## 상태

코드와 자동 테스트를 구현하고 Ubuntu 22.04 ROS 2 Humble CI에서 5개 패키지 빌드와
격리 domain 142의 87개 테스트를 통과했다. TB1에서 지도 작성, AMCL 정합, 목표 도달과
장애 주입을 아직 실행하지 않았으므로 Phase 5를 완료로 표시하지 않는다.

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
             safety_watchdog
                    | /cmd_vel
             TurtleBot3 base
```

Gateway는 명령 식별자와 lease를 소유한다. `navigation_agent`는 로컬 안전 상태와
lease를 확인하고 Nav2 목표를 소유한다. `motion_arbiter`는 입력 출처를 하나만
고른다. `safety_watchdog`은 최종 속도 제한, e-stop, dead-man timeout과 중립
재무장을 담당하며 실제 `/cmd_vel`의 유일한 정상 publisher다.

## 상태 머신

`NavigationStatus`는 다음 상태를 사용한다.

| 상태 | 의미 |
| --- | --- |
| `UNAVAILABLE` | 지도, Nav2 또는 필수 상태가 준비되지 않음 |
| `IDLE` | 목표가 없고 아직 위치추정 준비 전 |
| `LOCALIZING` | 초기 위치를 발행했고 새 AMCL pose를 기다림 |
| `READY` | 지도, Nav2, AMCL, RobotStatus와 안전 상태가 모두 최신 |
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

## motion 권한

arbiter mode는 `IDLE`, `MANUAL`, `NAVIGATION` 중 하나다. 매핑 프로필은 MANUAL,
주행 프로필은 시작과 재시작 때 IDLE이다. navigation agent가 목표와 유효한 lease를
모두 보유할 때만 authorization `true`를 10 Hz로 발행한다.

다음 두 시간이 독립적으로 적용된다.

- Gateway lease 만료: 2.0초. agent가 목표를 `LEASE_EXPIRED`로 끝내고 Nav2를 취소한다.
- 로컬 authorization 만료: 0.5초. agent가 죽더라도 arbiter가 0을 출력한다.

arbiter 출력도 watchdog 0.5초 timeout과 `0.05 m/s`, `0.3 rad/s` clamp를 통과한다.

## e-stop 순서

Gateway는 watchdog e-stop 서비스 성공을 먼저 기다린다. 그 다음 활성 action
handle을 lease 목록에서 제거하고 취소한다. agent도 `SafetyStatus`를 보고 motion
mode를 IDLE로 바꾸고 downstream Nav2 목표를 취소한다. 취소 응답이 유실되어도
watchdog 0과 lease 만료가 독립적으로 정지를 강제한다.

해제 뒤 watchdog은 `WAITING_NEUTRAL`이다. IDLE arbiter가 보내는 0을 받은 뒤에만
`motion_armed=true`가 되고, 이전 action handle과 lease는 이미 제거되어 자동
재출발하지 않는다.

watchdog 프로세스 재시작도 `WAITING_NEUTRAL`로 시작한다. 활성 주행 중이었다면 agent가
`motion_armed=false`를 받아 목표와 authorization을 취소하고 arbiter를 IDLE로 만든다.
그 IDLE 0이 watchdog을 재무장하므로 watchdog 복구가 이전 목표를 재개하지 않는다.
agent가 재시작해 이전 command를 더 이상 active로 보고하지 않으면 Gateway도 한 번
확인했던 command의 lease 소유권을 제거해 새 목표가 stale handle에 막히지 않게 한다.
action accept 직후 agent가 종료되어 active 상태를 한 번도 확인하지 못한 경우에도
Gateway는 2초 확인 timeout 뒤 lease를 철회하고 cancel을 요청한다.
Nav2 action 서버가 1초 동안 사라지면 agent는 authorization과 motion mode를 철회하고
custom 목표를 `FAILED`로 끝내므로, 사라진 downstream result를 무기한 기다리지 않는다.

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
Nav2 프로세스와 agent/arbiter는 실패 시 재시작하되, agent startup hook이 motion을
IDLE로 만들고 모든 잔존 Nav2 goal을 취소한다.

Nav2의 전체 plugin 구성은 설치된 TurtleBot3 Humble Burger 기준 파일을 사용하고,
저장소 소유 `tb1_nav2_rewrites.yaml`로 DWB/recovery 속도와 progress checker 값을
고정한다. 최종 watchdog은 이 설정과 독립적으로 같은 속도 상한을 다시 강제한다.

## 완료 조건

자동 테스트는 Python world↔cell과 브라우저 world↔canvas 좌표 회전, 셀 정책,
API 409/422, WARN 확인, fake Nav2
성공·거부·feedback·취소·실패, Gateway lease 주기, lease 만료, authorization 만료,
e-stop과 재시작 취소를 다룬다. 최종 완료에는
[실차 절차](../setup/tb1-navigation.md)의 모든 측정값과 로그가 추가로 필요하다.

## 참고 기준

- [Nav2 mapping/localization setup](https://docs.nav2.org/setup_guides/sensors/mapping_localization.html)
- [Zenoh ROS 2 DDS bridge와 action 지원](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds)
- [TurtleBot3 Navigation](https://emanual.robotis.com/docs/en/platform/turtlebot3/navigation/)
- [Humble NavigateToPose action 계약](https://github.com/ros-navigation/navigation2/blob/humble/nav2_msgs/action/NavigateToPose.action)
