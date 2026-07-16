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
11. DDS 토픽 상호 운용과 ROS 2 서비스 request/reply 호환성은 별도로 검증한다.
12. 개별 안전 명령 사이의 odom 자세도 영속 체크포인트로 이어서 검증해야 한다.

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
- 실차 운영 셸은 로봇 서비스와 같은 `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`를 사용한다.
- watchdog은 시작부터 e-stop 상태여야 하며, 서비스 응답과 상태 토픽을 함께 확인한다.
- 안전 방향은 단일 LaserScan 최대값이 아니라 여러 스캔의 sector 최소값으로 선택한다.
- 로봇을 들어 옮기거나 끌어 wheel odometry에 기록되지 않았다면 진행 중인 SLAM 지도와
  pose graph를 이어 쓰지 않는다.
- 바퀴가 구르며 odom과 SLAM이 수동 회전을 추적했더라도, 승인되지 않은 명령 간 자세
  변화는 다음 이동 전에 원인을 확인하고 체크포인트를 명시적으로 재등록한다.

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

### 토픽은 보이는데 e-stop 서비스가 시간 초과될 수 있는 이유는?

DDS 벤더가 일반 Topic 데이터를 상호 운용해도 ROS 2 Service의 request/reply 식별자 처리까지
같다고 보장할 수 없다. 이 프로젝트에서는 TB1 노드가 Cyclone DDS인데 원격 셸의 RMW가
설정되지 않아 endpoint와 `/cmd_vel`은 보였지만 e-stop 응답이 돌아오지 않았다. 모든 프로세스를
`rmw_cyclonedds_cpp`로 통일하고 서비스 왕복을 별도로 검증해야 한다.

### 왜 watchdog 시작 기본값을 e-stop으로 바꿨는가?

프로세스 재시작 직후 설정·통신·Publisher 상태가 아직 검증되지 않았기 때문이다. 안전 상태에서
시작하고, 운영자가 단독 입력 소유권과 최신 센서, 최종 0속도를 증명한 뒤 명시적으로 해제해야
단일 장애가 곧 이동 허가가 되는 것을 막을 수 있다. 이를 fail-closed 기본값이라고 설명한다.

### 왜 방향별 LiDAR 여유를 여러 스캔에서 계산하는가?

한 회전의 반사 누락, 임시 장애물이나 노이즈로 단일 sector 값이 실제보다 크게 나올 수 있기
때문이다. 이 프로젝트에서도 한 장의 스캔이 `-45°` 방향을 `1.452m`로 보였지만 실제 회전 뒤
정면 최소 여유는 `0.355m`였다. 여러 스캔에서 계산한 최소값이나 낮은 percentile을 사용하면
일시적인 큰 값보다 보수적으로 이동 방향을 고를 수 있다.

### 손으로 로봇을 옮기면 왜 SLAM을 재시작하는가?

wheel odometry는 모터 회전으로 계산되므로 들어서 옮긴 변위를 알지 못한다. SLAM은 odometry를
스캔 정합의 motion prior로 사용하므로 실제 sensor pose와 내부 pose가 달라져 지도 이중선이나
잘못된 loop closure가 생길 수 있다. 오염된 데이터를 보정해 쓰지 않고 현재 위치에서 새 map과
pose graph를 시작한다.

### 바퀴를 굴려 손으로 돌린 경우에도 지도를 무조건 폐기하는가?

무조건은 아니다. 바퀴 encoder가 회전을 기록하고 `map -> base`와 odom이 같은 자세로
연속 추적됐다면 SLAM의 motion prior가 끊긴 것은 아니다. 이 프로젝트의 수동 약 90도
회전도 odom에서 약 93도로 관측됐고 SLAM 자세와 일치했다. 다만 보호 명령 밖에서 일어난
움직임은 의도와 원인을 자동으로 알 수 없으므로 다음 명령은 영속 자세 체크포인트가
차단한다. 운영자가 e-stop, 실제 위치, 지도 연속성을 검토한 뒤 dry-run reset으로 새
기준을 승인하거나, 가능하면 처음부터 보호 회전 명령을 사용한다.

## 틀리기 쉬운 설명과 교정

| 틀린 설명 | 올바른 설명 |
| --- | --- |
| SLAM이 경로를 계획한다 | SLAM은 지도와 위치, Nav2 planner가 경로를 담당한다 |
| `/map`이 나오면 지도는 완성이다 | loop closure와 벽 정합 등 품질 검토가 필요하다 |
| Nav2가 켜지면 자동으로 현재 위치를 안다 | 저장 지도에서는 AMCL 초기 위치가 필요하다 |
| e-stop을 풀면 이전 Goal을 계속하면 된다 | 중립 재무장과 Goal 상태 정리가 먼저다 |
| `/cmd_vel` 값만 작으면 안전하다 | timeout, 단일 최종 Publisher, e-stop 경계가 함께 필요하다 |
| PGM만 있으면 지도를 재편집할 수 있다 | 매핑 재개에는 pose graph와 data도 보관해야 한다 |
| Topic이 보이면 Service도 된다 | RMW를 통일하고 request/response 왕복을 별도로 시험해야 한다 |
| 한 장의 LiDAR에서 먼 방향이면 안전하다 | 여러 스캔의 sector 최소값과 실제 guard를 통과해야 한다 |
| 손으로 옮겨도 SLAM이 알아서 처리한다 | 들어 옮긴 이동은 지도를 폐기한다. 바퀴로 굴린 이동도 odom·TF 연속성을 검증하고 명령 체크포인트를 다시 승인해야 한다 |

## 면접 모범 답변

### 30초 설명

> TB1에서 SLAM Toolbox로 2D 지도를 만들고, 저장 지도에서는 Map Server와 AMCL로
> 위치를 추정한 뒤 Nav2 `NavigateToPose`를 사용하도록 설계했습니다. Nav2 controller와
> recovery behavior의 모든 속도 출력은 `/safety/cmd_vel_in`으로 remap해 로봇 로컬
> watchdog가 속도 제한, 0.5초 timeout과 e-stop을 최종 집행합니다. 현재 패키지 설치,
> TF·센서 사전 점검과 robot workspace 전체 145개 자동 테스트까지 통과했고 실차 지도와
> Goal은 안전 구역에서 단계적으로 검증합니다.

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

### 8. `RMW_IMPLEMENTATION`을 명시하지 않은 셸을 실차 guard가 거부하는 이유는?

정답: Topic discovery나 데이터 수신이 성공해도 다른 RMW 조합의 ROS 2 Service 응답이
시간 초과될 수 있다. e-stop 해제·재적용의 성공을 확정할 수 없는 환경에서는 이동을 시작하면
안 되므로 node 생성 전에 fail-closed로 거부한다.

### 9. e-stop Bool 상태 토픽에 transient-local QoS를 사용한 이유는?

정답: 검사 도구나 guard가 watchdog보다 늦게 시작해도 마지막 e-stop 상태를 즉시 받아
서비스 응답과 실제 상태를 대조할 수 있게 하기 위해서다. watchdog은 2Hz heartbeat도
발행해 late-joiner 전달과 상태 발행 liveness를 함께 확인할 수 있게 했다.

### 10. ROS 통합 테스트가 병렬 CI에서만 간헐적으로 실패한 원인은?

정답: 서로 다른 패키지의 테스트가 같은 ROS domain과 절대 service 이름을 공유해 client가
다른 패키지의 가짜 서버 응답을 받을 수 있었기 때문이다. 테스트 전용 고유 service 이름으로
graph를 격리해 해결했다.

### 11. 지도 파일이 열리면 바로 Nav2에 사용해도 되는가?

정답: 아니다. YAML이 참조하는 PGM과 해상도·원점·임계값이 일관되어야 하고, 이미지에
충분한 known cell이 있어야 한다. 자동 검사는 파일 구조와 최소 관측량을 확인하지만 벽의
이중선, 끊김, loop closure와 실제 공간 일치 여부는 RViz와 현장 관찰로 따로 검토해야 한다.

### 12. 360도 LiDAR 로봇을 제자리 회전했는데 known cell이 늘지 않을 수 있는 이유는?

정답: 로봇의 진행 방향은 바뀌어도 LiDAR는 회전 전부터 주변 360도를 이미 관측했을 수 있기
때문이다. 제자리 회전은 자세와 스캔 정합 검증에는 유용하지만, 새 공간을 보려면 안전한 새
방향으로 실제 위치를 이동해 센서 시점을 바꿔야 한다.

### 13. 저장 전 지도는 unknown인데 재로드 후 free가 될 수 있는 이유는?

정답: Humble trinary Map Saver는 unknown을 회색 205로 쓰지만 기본 YAML
`free_thresh=0.25`에서는 이 밝기의 점유확률 약 0.196이 free 조건에 들어갈 수 있다.
저장 시 `--free 0.196`을 명시하고, live map과 round-trip map의 unknown cell 수를 비교해
정보 손실을 검사해야 한다.

### 14. 각 보호 이동은 성공했는데 왜 명령 간 자세 체크포인트가 필요한가?

정답: 한 프로세스는 자기 실행 중의 이동만 검증하며 다음 프로세스가 시작될 때까지 사람이
밀거나 돌린 변화, 부분 실패, odom 재시작을 기억하지 못한다. 마지막 성공 자세를 로봇별
상태 파일에 원자적으로 저장하고 다음 실행 전에 3cm·5도 한계로 비교해야 실행 사이의
안전 공백을 막을 수 있다. 이동 직전 `motion_in_progress`를 기록하고 성공한 종점만
완료 처리하면 작은 부분 실패와 강제 종료도 놓치지 않는다. 기준 재등록은 e-stop dry-run과
운영자 원인 확인 뒤에만 한다.

## 보지 않고 다시 말할 체크리스트

- [ ] `map -> odom -> base -> scan` TF 책임을 설명할 수 있다.
- [ ] SLAM, AMCL, planner, controller, costmap 역할을 구분할 수 있다.
- [ ] Topic·Service·Action 중 `NavigateToPose`가 Action인 이유를 말할 수 있다.
- [ ] Nav2 속도가 watchdog로 들어가는 토픽 경로를 그릴 수 있다.
- [ ] 지도 네 파일의 용도 차이를 설명할 수 있다.
- [ ] 첫 Goal 전 안전 확인 순서를 말할 수 있다.
- [ ] Topic 성공과 Service 성공이 별개일 수 있는 이유를 말할 수 있다.
- [ ] fail-closed 시작과 transient-local e-stop 상태의 목적을 설명할 수 있다.
- [ ] 단일 스캔보다 시간 구간의 보수적 clearance가 필요한 이유를 말할 수 있다.
- [ ] 들어 옮긴 재배치와 odom이 추적한 바퀴 회전을 구분해 설명할 수 있다.
- [ ] 명령 간 자세 체크포인트의 저장·차단·재등록 정책을 설명할 수 있다.
- [ ] 병렬 ROS 통합 테스트의 graph 격리 방법을 설명할 수 있다.
- [ ] 지도 자동 검사가 보장하는 것과 보장하지 않는 것을 구분할 수 있다.
- [ ] 제자리 회전과 위치 이동이 지도 관측 범위에 미치는 차이를 설명할 수 있다.
- [ ] trinary unknown marker와 free threshold의 round-trip 문제를 설명할 수 있다.

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

저장 지도에 관해서는 다음 문장도 기억한다.

> 파일을 읽을 수 있다는 것은 좋은 지도라는 뜻이 아니다. 구조 검사는 자동화하고 공간
> 형상과 loop closure는 시각·현장 증거로 따로 검증한다.

> 360도 LiDAR에서 방향 전환과 새 공간 관측은 같은 말이 아니다. 지도 범위를 늘리려면
> 센서의 위치가 바뀌어야 한다.

> 저장 명령의 성공은 의미 보존의 증거가 아니다. 저장한 지도를 다시 읽어 unknown·free·
> occupied cell 수가 보존되는지 확인해야 한다.

> 안전한 명령 여러 개가 자동으로 안전한 연속 작업이 되는 것은 아니다. 마지막 성공 자세를
> 다음 명령의 시작 자세와 비교해야 명령 사이의 수동 이동도 발견할 수 있다.
