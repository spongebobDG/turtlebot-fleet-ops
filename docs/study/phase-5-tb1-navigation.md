# Phase 5: 로컬 Nav2, 좌표 변환과 lease 기반 안전

## 핵심 설명

이번 단계의 핵심은 “웹이 Nav2를 호출한다”가 아니라 원격 목표가 끊겨도 로봇 내부에서
안전하게 취소되는 제어 소유권을 만드는 것이다. Gateway는 명령과 lease를 소유하고,
TB1 agent는 Nav2 목표를 소유하며, arbiter와 watchdog이 속도 권한을 독립적으로 닫는다.

자동 검증에서는 Ubuntu 22.04 ROS 2 Humble로 5개 패키지를 빌드하고, 격리 domain
142에서 fake Nav2 action, lease, e-stop, watchdog 재무장과 Gateway 계약을 포함한
89개 테스트와 실제 Nav2 stack robotless smoke가 통과했다. 자동 테스트는 상태 전이와
ROS graph 연결의 증거지만, 실제 LiDAR 정합과 정지거리·CPU·메모리 검증을 대신하지
않는다.

## 왜 Nav2를 TB1에서 실행하는가

원격 PC Nav2는 계산 자원에는 유리하지만 네트워크 단절이 제어 loop에 직접 영향을 준다.
TB1 로컬 실행은 map, AMCL, costmap과 controller를 로봇 가까이에 둔다. 대신 Raspberry
Pi의 CPU·메모리를 10분 주행으로 확인해야 한다. 이번 선택은 무조건 우월해서가 아니라
단절 안전성을 우선한 trade-off다.

## OccupancyGrid 좌표 변환

OccupancyGrid origin은 단순한 왼쪽 아래 픽셀 위치가 아니라 translation과 yaw를 가진
pose다. world point에서 origin을 빼고 `-yaw`만큼 회전한 local 좌표를 resolution으로
나눠 cell을 얻는다.

```text
dx = world_x - origin_x
dy = world_y - origin_y
local_x =  cos(yaw) * dx + sin(yaw) * dy
local_y = -sin(yaw) * dx + cos(yaw) * dy
cell_x = floor(local_x / resolution)
cell_y = floor(local_y / resolution)
```

ROS data index는 `cell_y * width + cell_x`다. canvas는 아래로 y가 증가하므로 화면
y 반전도 필요하다. origin yaw를 생략하면 회전된 지도에서 클릭 위치가 다른 셀로 간다.

### world와 canvas의 양방향 변환

브라우저는 ROS 행 순서를 뒤집어 그리므로 world→canvas는 다음 순서를 따른다.

```text
canvas_x = local_x / resolution
canvas_y = map_height - local_y / resolution
```

canvas→world는 이 순서의 역변환이다. 먼저 화면 y 반전을 되돌리고 resolution을 곱한
뒤, `+origin_yaw` 회전과 origin translation을 적용한다.

```text
local_x = canvas_x * resolution
local_y = (map_height - canvas_y) * resolution
world_x = origin_x + cos(yaw) * local_x - sin(yaw) * local_y
world_y = origin_y + sin(yaw) * local_x + cos(yaw) * local_y
```

두 변환은 서로 왕복했을 때 원래 좌표가 나와야 한다. 그래서 Canvas 구현을 DOM과
분리한 순수 함수로 만들고, y 반전·90도 origin 회전·비정상 해상도를 Node 테스트로
검증한다. 서버도 같은 좌표를 다시 cell로 변환해 free cell인지 확인하므로 브라우저
표시만 믿고 명령을 통과시키지 않는다.

## AMCL READY 조건

지도와 `/amcl_pose`가 존재한다는 것만으로는 충분하지 않다. 이전 실행의 latched 또는
오래된 위치를 신뢰하면 잘못된 곳에서 경로를 시작할 수 있다. 웹 초기 위치를 `/initialpose`
로 발행한 시각 이후 새 AMCL pose를 받았고, 그 pose가 freshness timeout 안에 있을 때만
localization ready다.

## action server 발견과 lifecycle ACTIVE는 다르다

ROS graph에 action server가 보인다는 것은 endpoint가 생성됐다는 뜻이지, Nav2가 목표를
실행할 수 있다는 뜻은 아니다. lifecycle node는 `unconfigured → inactive → active`로
전이한다. `bt_navigator`가 inactive인 짧은 구간에도 `/navigate_to_pose` server가
발견될 수 있고, 이때 목표를 보내면 Nav2가 거부한다.

따라서 준비 조건은 두 신호의 AND다.

```text
nav2_ready = action_server_ready
             AND bt_navigator.lifecycle == ACTIVE
             AND startup IDLE/cancel-all acknowledged
             AND map received
```

robotless smoke가 바로 이 경쟁을 재현했다. 초기 구현은 action endpoint만 보고 READY를
발행해 lifecycle activation 직전 목표를 접수했다. agent가
`/bt_navigator/get_state`를 주기적으로 확인하도록 바꾼 뒤에는 inactive 동안
fail-closed `UNAVAILABLE`을 유지한다. 이 사례는 “토픽/서비스 존재 검사”와 “기능 준비
검사”를 구분해야 한다는 일반적인 ROS 2 운영 원칙이다.

## lease와 authorization 차이

- lease는 Gateway가 action을 계속 소유하고 있다는 분산 heartbeat다. 0.5초마다 보내며
  TB1에서 2초 만료한다.
- authorization은 agent가 arbiter에 주는 로컬 속도 권한이다. 10 Hz로 보내며 0.5초
  만료한다.

Gateway/Zenoh 단절에는 lease가 대응하고 agent 프로세스 사망에는 authorization이 더
빠르게 대응한다. 둘 중 하나가 stale이면 arbiter 또는 agent가 0과 취소를 만든다.

## Humble Nav2의 속도 topic 흐름

Humble `nav2_bringup`은 controller의 `cmd_vel`을 내부 `cmd_vel_nav`로 바꾸고,
`velocity_smoother`가 이를 받아 smoothed `cmd_vel`을 발행한다. 한편
`behavior_server`의 recovery 동작은 `/cmd_vel`을 직접 발행한다. 공통 group remap은
Nav2 bringup 내부 remap보다 먼저 적용되어 controller나 smoother 입력까지 바꿀 수
있다. 저장소 소유 non-composed launch는 노드를 직접 시작하면서 controller의
`cmd_vel → cmd_vel_nav`, smoother의 `cmd_vel_smoothed → /motion/navigation/cmd_vel`,
behavior의 `cmd_vel → /motion/navigation/cmd_vel` 규칙을 각 노드에만 적용한다.

```text
controller_server --cmd_vel_nav--> velocity_smoother
velocity_smoother --/motion/navigation/cmd_vel--> motion_arbiter
behavior_server --/motion/navigation/cmd_vel--> motion_arbiter
motion_arbiter --/safety/cmd_vel_in--> safety_watchdog --/cmd_vel--> base
```

따라서 `/motion/navigation/cmd_vel`의 주행 publisher는 `velocity_smoother`이고 recovery
중에는 `behavior_server`도 같은 안전 입력을 사용한다. 그 topic을 controller가 직접
발행한다고 단정하면 Nav2 내부 smoothing 단계를 놓친다. 실제 base topic `/cmd_vel`의
publisher는 여전히 `safety_watchdog` 하나여야 한다.

## command ID가 필요한 이유

ROS action 자체에도 goal ID가 있지만 HTTP 사용자와 Gateway lease가 같은 명령을
식별하려면 공개된 안정적인 ID가 필요하다. Gateway가 `command_id`를 만들고 action,
lease, status와 DELETE 경로에 동일하게 사용한다. 취소 요청의 ID가 현재 active ID와
다르면 409로 거부하므로 늦게 도착한 이전 UI 요청이 새 목표를 취소하지 못한다. 새
목표도 active command를 자동 대체하지 않는다.

## receipt time과 message stamp

lease와 상태 freshness는 상대 호스트의 ROS stamp가 아니라 수신 측 monotonic time으로
계산한다. 서로 다른 장비의 시계가 조금 어긋나거나 NTP가 시간을 보정해도 만료 계산이
뒤로 가지 않게 하기 위해서다. message stamp는 관찰과 로그 상관관계에는 유용하지만,
분산 timeout의 단독 권한 근거로 쓰지 않는다.

## e-stop과 cancel의 차이

action cancel은 경로 실행을 정상적으로 끝내 달라는 요청이다. e-stop은 action 상태와
무관하게 최종 속도를 즉시 0으로 만드는 안전 상태다. 따라서 e-stop은 watchdog을 먼저
잠그고, 그 뒤 lease 제거와 action cancel을 수행한다. cancel 응답이 늦거나 유실되어도
watchdog과 lease timeout이 남는다.

## 재시작은 복구가 아니라 새 권한 획득이다

프로세스가 다시 실행됐다는 사실만으로 이전 이동 권한을 되살리면 안 된다.

| 재시작/장애 | fail-closed 동작 |
| --- | --- |
| navigation agent 종료 | arbiter authorization이 0.5초 뒤 만료되어 0 출력 |
| navigation agent 시작 | arbiter IDLE 응답과 Nav2 cancel-all 응답을 확인한 뒤 ready 판정 |
| Nav2 action 서버 부재 | 1초 지속 시 authorization 철회, custom action `FAILED` |
| Nav2 endpoint는 보이나 lifecycle inactive | `nav2_ready=false`, 새 목표 거부 |
| arbiter 종료 | watchdog 입력이 끊겨 0.5초 timeout, 재시작 mode는 IDLE |
| watchdog 시작·재시작 | `WAITING_NEUTRAL`과 `motion_armed=false`로 시작 |
| Gateway의 이전 action handle | 확인한 active command가 status에서 사라지면 lease 소유권 제거 |
| 목표 접수 직후 agent 종료 | 2초 안에 active command 확인이 없으면 lease 철회와 cancel 요청 |

watchdog은 IDLE 0을 새로 받아야 재무장한다. agent의 startup cancel-all은 요청을 보낸
것만으로 성공 처리하지 않고 서비스 응답의 성공 코드까지 확인한다. Gateway도 action
accept만으로 lease를 계속 소유하지 않고 2초 안에 같은 command가 active로 보고되는지
확인한다. 이 원칙 때문에 systemd respawn은
프로세스 가용성을 회복하지만 목표 재개 권한을 자동으로 회복하지 않는다.

## custom action이 Nav2 action을 감싸는 이유

웹이 Nav2 `NavigateToPose`를 직접 호출하면 fleet command ID, WARN 확인, lease age와
로봇별 안전 상태를 하나의 계약으로 묶기 어렵다. `NavigateRobot`은 Nav2 goal을 로봇
로컬에서 소유하며 현재 pose, 남은 거리·시간, recovery 수와 lease age를 전달한다.
Humble의 `NavigateToPose` result에는 상세 error code가 없으므로 custom result는 ROS
action terminal status와 로컬 실패 원인을 보존하고, error code 필드가 있는 배포판은
그 값을 추가로 전달한다.

## 자주 틀리는 설명

| 틀린 설명 | 정확한 설명 |
| --- | --- |
| Nav2를 remap했으니 안전하다 | arbiter authorization과 watchdog clamp/timeout까지 통과해야 한다 |
| e-stop 해제는 이전 작업 재개다 | 중립 재무장 후에도 이전 action과 lease는 폐기된 상태다 |
| map pixel은 곧 world 좌표다 | resolution, origin translation, origin yaw와 canvas y 반전이 필요하다 |
| heartbeat 하나면 충분하다 | Gateway lease와 agent authorization은 서로 다른 장애 경계를 감시한다 |
| systemd respawn이면 목표도 복구한다 | 재시작은 fail-closed IDLE과 잔존 목표 cancel로 시작한다 |
| startup 요청을 보냈으면 안전 확인이 끝났다 | IDLE과 cancel-all의 응답을 받아야 ready다 |
| 브라우저가 free cell을 골랐으니 안전하다 | Gateway와 agent가 실제 OccupancyGrid로 다시 검증한다 |
| navigation topic은 controller가 직접 발행한다 | Humble에서는 velocity smoother의 최종 출력이다 |

## 면접 모범 답변

“Nav2는 TB1에서 실행하지만 `/cmd_vel`을 직접 발행하지 않게 remap했습니다. Nav2 출력은
motion arbiter를 거치며, Gateway lease가 2초 안에 갱신되고 agent authorization이
0.5초 안에 갱신될 때만 watchdog 입력으로 전달됩니다. watchdog은 다시 0.5초 timeout과
0.05 m/s, 0.3 rad/s 상한을 적용하고 실제 `/cmd_vel`의 유일한 publisher입니다.
e-stop은 watchdog을 먼저 정지시킨 뒤 action과 lease를 취소하며, watchdog과 agent가
재시작해도 각각 WAITING_NEUTRAL, IDLE과 cancel-all 확인에서 시작합니다. Nav2 action
서버가 1초 동안 사라지면 custom goal도 FAILED로 닫아 stale future가 새 목표를 막지
않게 했습니다. 해제나 복구 뒤에는 새 명령과 새 권한을 받아야 하므로 이전 목표가 자동
재개되지 않습니다.”

## 복습 질문

1. origin yaw가 있는 OccupancyGrid에서 world point를 cell로 바꾸는 순서는 무엇인가?
2. 초기 위치 요청 전의 `/amcl_pose`를 READY 근거로 쓰면 안 되는 이유는 무엇인가?
3. 2초 lease와 0.5초 authorization이 각각 막는 장애는 무엇인가?
4. e-stop 때 watchdog 서비스가 action cancel보다 먼저여야 하는 이유는 무엇인가?
5. Nav2 최대 속도와 watchdog 최대 속도를 둘 다 제한하는 이유는 무엇인가?
6. agent 재시작 시 잔존 목표를 복구하지 않고 취소하는 이유는 무엇인가?
7. canvas y 반전을 world 회전과 별도 단계로 처리해야 하는 이유는 무엇인가?
8. Gateway가 확인한 command가 새 NavigationStatus에서 사라졌을 때 lease를 제거해야
   하는 이유는 무엇인가?
9. systemd respawn과 motion authorization 복구를 같은 사건으로 보면 안 되는 이유는
   무엇인가?
10. 수신 시각 기반 freshness가 송신 stamp 기반 계산보다 안전한 상황을 예로 들어라.
11. Nav2 action server가 발견돼도 lifecycle ACTIVE를 별도로 확인해야 하는 이유는
    무엇인가?
12. `/motion/navigation/cmd_vel`과 실제 `/cmd_vel`의 publisher가 각각 누구여야 하는가?

답은 [Phase 5 설계](../design/phase-5-tb1-navigation.md)와
[운영 절차](../setup/tb1-navigation.md)를 근거로 직접 설명한다.
