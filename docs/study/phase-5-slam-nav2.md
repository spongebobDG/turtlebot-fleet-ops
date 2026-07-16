# Phase 5: SLAM, Localization과 안전 Nav2

## 이번 Phase에서 반드시 알아야 할 것

1. SLAM은 지도 작성과 위치 추정을 함께 하고, AMCL은 저장 지도에서 위치만 추정한다.
2. Nav2는 `map -> odom -> base` TF와 최신 `/scan`, `/odom` 없이는 동작할 수 없다.
3. Topic은 연속 데이터, Service는 짧은 요청, Action은 취소·feedback이 필요한 장시간 작업이다.
4. Global planner는 큰 경로, local controller는 실제 속도 명령을 계산한다.
5. Global/local costmap은 지도와 센서 장애물을 주행 가능한 비용으로 바꾼다.
6. Nav2 lifecycle `active`와 프로세스가 단순히 살아 있는 것은 다르다.
7. Nav2 속도도 최종 모터 전에 로봇 로컬 watchdog를 통과해야 한다.
8. 지도 PGM·YAML과 SLAM pose graph는 목적이 다른 산출물이다.
9. LaserScan은 배열 길이와 각도 메타데이터가 일관돼야 한다.
10. 분산 브리지에서도 최종 `/cmd_vel` 권한은 로봇 로컬 watchdog 하나로 제한한다.

## 오늘 꼭 기억해야 할 것

```text
map -> odom        : SLAM 또는 AMCL 중 하나만 담당
odom -> base       : 바퀴 odometry
base -> base_scan  : 로봇 고정 구조

NavigateToPose Goal
-> planner
-> controller
-> velocity smoother
-> safety_watchdog
-> turtlebot3_node
```

- 지도 작성 중 SLAM과 AMCL을 함께 켜지 않는다.
- `/cmd_vel` Publisher가 있다는 사실보다 누가 최종 Publisher인지 확인한다.
- `NavigateToPose`는 목적지 작업이므로 Action이 맞다.
- e-stop은 Goal 취소와 다르다. 정지 후 Goal 상태도 명시적으로 정리해야 한다.
- 첫 실차 Goal은 지도에서 확인한 짧고 장애물 없는 좌표만 사용한다.
- 지도 품질이 나쁘면 planner 튜닝 전에 매핑·TF·odometry부터 바로잡는다.
- 가변 LiDAR 배열은 index를 자르지 말고 실제 각도로 고정 격자에 재투영한다.
- Zenoh에는 모든 인터페이스를 열지 않고 필요한 방향의 allow-list를 둔다.

## 개념을 쉽게 설명하는 정답

### SLAM과 AMCL은 무엇이 다른가?

SLAM은 처음 가는 공간에서 방 구조를 그리면서 지도 안의 내 위치도 동시에 추정한다.
AMCL은 이미 완성된 지도를 책상 위에 펼쳐 놓고 LiDAR 모양을 대조해 현재 위치를 찾는다.
따라서 지도 작성 때는 SLAM, 운영 주행 때는 Map Server와 AMCL을 사용한다.

### `map`과 `odom` 좌표계가 왜 둘 다 필요한가?

`odom`은 바퀴 회전량을 적분하므로 짧은 이동은 부드럽지만 시간이 지나면 오차가
누적된다. `map`은 지도 기준으로 장기 위치가 어긋나지 않게 보정하지만 값이 순간적으로
수정될 수 있다. `map -> odom` 보정과 `odom -> base`의 부드러운 이동을 합쳐 두 장점을
사용한다.

### Costmap은 단순한 지도인가?

아니다. 정적 지도, LiDAR의 현재 장애물, 로봇 크기와 안전 여유를 합쳐 각 셀의 이동
비용을 만든 데이터다. Global costmap은 전체 경로에, local costmap은 가까운 동적
장애물 회피와 속도 계산에 사용한다.

### Planner와 Controller의 차이는?

Planner는 현재 위치에서 목적지까지 어느 길로 갈지 경로를 만든다. Controller는 그
경로와 가까운 장애물을 보고 지금 순간의 선속도·각속도를 계산한다. 길 찾기와 핸들·가속
조작의 차이라고 설명할 수 있다.

### ROS 2 Action을 사용하는 이유는?

자율주행은 몇 초에서 몇 분이 걸리고 중간 진행률, 취소, 최종 성공·실패가 필요하다.
Service처럼 한 번의 짧은 응답으로 모델링하면 timeout과 취소 상태가 모호해진다.
`NavigateToPose` Action은 Goal, feedback, result, cancel을 표준 계약으로 제공한다.

### Lifecycle node는 왜 필요한가?

Map Server, AMCL, planner 같은 노드는 프로세스가 떠 있어도 설정이나 의존 데이터가
준비되지 않으면 일을 시작하면 안 된다. Lifecycle은 unconfigured, inactive, active,
finalized 상태 전이를 통해 준비와 실행을 분리하고 여러 Nav2 노드를 순서 있게 활성화한다.

### watchdog 앞에 Nav2 속도 제한도 두는 이유는?

Nav2 제한은 planner와 controller가 현실적인 궤적을 만들도록 돕고, watchdog 제한은
어떤 생산자나 설정 실수가 있어도 모터 직전에서 안전 상한을 강제한다. 둘은 중복 낭비가
아니라 정상 제어 품질과 독립 안전 경계라는 서로 다른 책임이다.

### `/scan` Publisher가 있는데 SLAM이 실패할 수 있는 이유는?

ROS graph는 타입과 endpoint 연결만 보여 준다. `ranges` 길이와
`angle_min/max/increment`가 서로 맞지 않거나 회전마다 형상이 바뀌면 SLAM 소비자는
메시지를 거부할 수 있다. 이 프로젝트에서는 100회 측정 후 각도 기준 360-bin 정규화로
해결했다.

### 왜 Zenoh에서 `/cmd_vel`을 허용하지 않는가?

브리지 프록시가 최종 모터 토픽을 발행하면 로컬 watchdog 외의 두 번째 권한이 생긴다.
관제 속도는 `/safety/cmd_vel_in`까지만 허용하고 clamp, timeout, e-stop과 중립 재무장을
통과한 watchdog 출력만 `/cmd_vel`로 보낸다.

## 틀리기 쉬운 설명과 교정

| 틀린 설명 | 올바른 설명 |
| --- | --- |
| SLAM이 경로를 계획한다 | SLAM은 지도와 위치, Nav2 planner가 경로를 담당한다 |
| `/map`이 나오면 지도는 완성이다 | loop closure와 벽 정합 등 품질 검토가 필요하다 |
| Nav2가 켜지면 자동으로 현재 위치를 안다 | 저장 지도에서는 AMCL 초기 위치가 필요하다 |
| e-stop을 풀면 이전 Goal을 계속하면 된다 | 중립 재무장과 Goal 상태 정리가 먼저다 |
| `/cmd_vel` 값만 작으면 안전하다 | timeout, 단일 최종 Publisher, e-stop 경계가 함께 필요하다 |
| PGM만 있으면 지도를 재편집할 수 있다 | 매핑 재개에는 pose graph와 data도 보관해야 한다 |

## 면접 모범 답변

### 30초 설명

> TB1에서 SLAM Toolbox로 2D 지도를 만들고, 저장 지도에서는 Map Server와 AMCL로
> 위치를 추정한 뒤 Nav2 `NavigateToPose`를 사용하도록 설계했습니다. Nav2 controller와
> recovery behavior의 모든 속도 출력은 `/safety/cmd_vel_in`으로 remap해 로봇 로컬
> watchdog가 속도 제한, 0.5초 timeout과 e-stop을 최종 집행합니다. 현재 패키지 설치,
> TF·센서 사전 점검과 72개 자동 테스트까지 통과했고 실차 지도와 Goal은 안전 구역에서
> 단계적으로 검증합니다.

### 1분 설명

> 자율주행을 한 번에 웹에 연결하지 않고 네 단계로 나눴습니다. 먼저 `/scan`, `/odom`,
> `odom -> base_footprint -> base_scan` TF를 확인하고 SLAM Toolbox로 지도를 만듭니다.
> 지도 PGM·YAML과 재매핑용 pose graph를 함께 저장한 뒤 SLAM을 끄고 Map Server와
> AMCL로 `map -> odom`을 담당하게 합니다. Nav2는 global planner로 경로를 만들고 DWB
> controller와 velocity smoother로 속도를 계산합니다. 기본 launch를 그대로 쓰면
> watchdog를 우회할 수 있어 non-composed launch를 소유하고 최종 출력을 안전 입력으로
> remap했습니다. 터미널 Goal의 성공·취소·실패·e-stop을 먼저 검증한 뒤 FastAPI Action
> Client와 WebSocket feedback을 추가할 계획입니다.

### “왜 기본 TurtleBot3 launch를 그대로 쓰지 않았나요?”

> 기존 시스템에서는 watchdog만 최종 `/cmd_vel` Publisher여야 합니다. Humble Nav2
> 기본 navigation launch는 velocity smoother 출력을 `/cmd_vel`로 remap하므로 그대로
> 실행하면 안전 경계를 우회하거나 Publisher가 둘이 될 수 있습니다. 그래서 upstream
> 파라미터를 기준으로 프로젝트 전용 설정 패키지를 만들고 controller, smoother,
> behavior의 토픽 경계를 명시했습니다. 합성 실행보다 프로세스별 로그와 장애 격리가 쉬운
> non-composed 방식을 첫 실차 기준선으로 선택했습니다.

### “네트워크가 끊기면 로봇은 어떻게 되나요?”

> Nav2와 watchdog는 TB1에서 로컬 실행하므로 단기 네트워크 단절이 로컬 센서 기반 안전을
> 제거하지 않습니다. 웹에서 새 Goal이나 취소 feedback은 끊길 수 있지만 watchdog는
> 입력이 0.5초 이상 갱신되지 않으면 0 속도를 발행합니다. 이후 Goal 상태와 통신 장애를
> Gateway가 기록하고, 자동 재개는 하지 않는 정책으로 확장합니다.

## 복습 문제와 정답

### 1. SLAM과 AMCL을 동시에 실행하면 안 되는 핵심 이유는?

정답: 둘 다 `map -> odom` TF의 권한을 가지면 동일 변환 Publisher가 충돌해 위치가
튀거나 Nav2가 잘못된 좌표를 사용할 수 있기 때문이다.

### 2. `odom`만으로 장시간 주행하면 왜 부족한가?

정답: 바퀴 미끄러짐과 측정 오차를 계속 적분하므로 시간이 지날수록 지도 기준 위치가
드리프트하기 때문이다.

### 3. Nav2 Goal이 Service가 아니라 Action인 이유는?

정답: 장시간 실행, 중간 feedback, 취소와 성공·실패 result가 필요하기 때문이다.

### 4. controller와 velocity smoother의 출력 제한을 낮췄는데 watchdog가 또 필요한가?

정답: Nav2 제한은 정상 궤적 품질을 위한 설정이고 watchdog는 다른 Publisher, 잘못된
설정, stale 입력과 e-stop까지 모터 직전에서 독립적으로 막는 안전 경계이기 때문이다.

### 5. 지도 저장 때 YAML과 pose graph를 모두 보관하는 이유는?

정답: YAML·PGM은 Map Server와 AMCL 주행용이고, pose graph·data는 SLAM 제약과 스캔
정보를 보존해 나중에 매핑을 이어서 수정하기 위해서다.

### 6. 가변 길이 LaserScan을 단순 padding하지 않은 이유는?

정답: 시작·끝 각도도 변해 같은 index가 다른 물리 방향을 뜻할 수 있으므로, 각 샘플을
실제 각도로 계산해 고정 격자에 배치해야 지도 왜곡을 막을 수 있기 때문이다.

### 7. `/cmd_vel` 값이 0이어도 Zenoh Publisher를 제거한 이유는?

정답: 현재 값과 발행 권한은 다르며, 미래에 비영 값을 낼 수 있는 최종 Publisher를
watchdog 하나로 제한해야 안전 정책을 우회할 경로가 없어지기 때문이다.

## 보지 않고 다시 말할 체크리스트

- [ ] `map -> odom -> base -> scan` TF 책임을 설명할 수 있다.
- [ ] SLAM, AMCL, planner, controller, costmap 역할을 구분할 수 있다.
- [ ] Topic·Service·Action 중 `NavigateToPose`가 Action인 이유를 말할 수 있다.
- [ ] Nav2 속도가 watchdog로 들어가는 토픽 경로를 그릴 수 있다.
- [ ] 지도 네 파일의 용도 차이를 설명할 수 있다.
- [ ] 첫 Goal 전 안전 확인 순서를 말할 수 있다.

## 아직 실차로 검증하지 않은 것

- 이동 매핑 중 SLAM Toolbox의 TB1 CPU·메모리 부하와 `/map` 품질
- 실제 공간의 loop closure와 지도 품질
- AMCL 수렴과 local/global costmap
- `NavigateToPose` 성공·취소·실패·e-stop 상호작용
- Zenoh를 통과하는 Action Goal·feedback·cancel

## 필수 Incident 복습

실차 매핑 중 e-stop이 upstream 잔류 명령을 가리는 문제와 잘못된 회전량 누적 방식을
발견했다. 원인·증거·폐기 판단·fail-closed 모션 가드·면접 모범 답변은
[TB1 잔류 텔레옵 명령 Incident와 모션 가드](../learning-log/2026-07-16-tb1-residual-teleop-command-incident.md)에
정리했다.

오늘 반드시 기억할 문장은 다음과 같다.

> e-stop 중 최종 출력이 0이라는 사실은 원시 입력이 중립이라는 증거가 아니다. 해제 전에는
> 입력 값과 Publisher 소유권을 함께 검증해야 한다.
