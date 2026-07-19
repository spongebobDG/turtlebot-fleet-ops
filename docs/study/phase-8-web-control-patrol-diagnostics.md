# Phase 8 공부: Deadman 제어, 순찰 상태 머신, 프로필 전환, 설명 가능한 MLOps

## 1. 왜 목적지에 위치뿐 아니라 방향이 필요한가

2차원 navigation pose는 `(x, y, yaw)`다. `(x, y)`만 맞고 yaw가 틀리면 로봇은 목적지에
도달했어도 카메라·센서·적재 방향이 업무 요구와 다를 수 있다. 그래서 클릭은 위치를,
드래그 끝점은 로봇의 `base_link +X`가 향할 방향을 나타낸다.

지도 이미지의 위쪽과 ROS map의 +Y, OccupancyGrid origin yaw가 다를 수 있으므로 화면 각도를
그대로 ROS yaw로 보내면 안 된다. 화면 좌표를 map 좌표로 역변환한 뒤 다음 식을 사용한다.

```text
yaw = atan2(target_map_y - anchor_map_y,
            target_map_x - anchor_map_x)
```

## 2. 속도 평활화와 안전 제한은 다른 책임이다

controller가 10 Hz로 속도를 바꾸면 저속 TurtleBot에서는 짧게 끊기는 느낌이 날 수 있다.
velocity smoother는 사이 값을 20 Hz로 보간하고 가속도·감속도를 제한한다. 하지만 smoother는
안전 watchdog을 대체하지 않는다.

- smoother: 승차감과 actuator 입력의 연속성
- arbiter: MANUAL/NAVIGATION/IDLE 중 누가 명령권을 가지는지 결정
- watchdog: stale command, e-stop, 상한 위반 시 실제 `/cmd_vel`을 0으로 만듦

이처럼 서로 다른 실패 모드를 서로 다른 계층이 막아야 한 노드의 장애가 최종 안전장치를
우회하지 못한다.

## 3. Deadman control이란 무엇인가

Deadman control은 “한 번 눌러 시작”이 아니라 “계속 누르고 갱신되는 동안만 움직임 허용”이다.
브라우저의 pointer-up 요청만 믿으면 Wi-Fi 단절이나 탭 강제 종료 때 정지 요청이 전달되지
않는다. 그래서 로봇 로컬에 짧은 authorization timeout이 반드시 있어야 한다.

이 프로젝트의 시간 관계는 다음과 같다.

```text
브라우저 refresh: 0.10 s
TB1 manual authorization timeout: 0.35 s
arbiter authorization timeout: 0.50 s
watchdog command timeout: 최종 로컬 안전 계층
```

정상 경로에서는 release 즉시 정지하고, 통신이 끊어진 비정상 경로에서도 로봇 로컬 timeout이
정지시킨다.

## 4. 웨이포인트 순찰을 하나의 큰 action으로 만들지 않은 이유

각 지점을 개별 `NavigateRobot` action으로 실행하면 기존 lease, e-stop, feedback, cancel,
fault 기록을 그대로 재사용할 수 있다. 순찰 관리자는 순서와 반복만 책임진다. 이 구조에서는
어느 지점에서 실패했는지 명확하고 기존 단일 목표 안전 검증도 보존된다.

중요한 상태 전이는 다음과 같다.

```text
DRAFT -> READY -> ACTIVE -> SUCCEEDED
                     |----> CANCELED
                     |----> FAILED
```

프로세스 재시작 시 `ACTIVE`를 다시 실행하면 예상하지 못한 자동 출발이 된다. 따라서 잔존
순찰은 `FAILED`로 정리하고 작업자가 다시 명시적으로 실행해야 한다.

## 5. 매핑과 주행 프로필을 동시에 실행하면 안 되는 이유

SLAM과 AMCL은 모두 map 관련 TF와 상태를 다루지만 목적이 다르다. SLAM은 지도를 바꾸고,
AMCL은 고정 지도에서 로봇 pose를 추정한다. 둘을 같은 운영 프로필에서 무심코 실행하면 TF,
자원 사용량, 지도 소유권이 모호해진다.

- MAPPING은 지도 생성과 안전 수동 조종에 집중한다.
- NAVIGATION은 저장 지도를 읽고 localization과 경로 계획에 집중한다.
- 전환할 때 e-stop을 먼저 활성화해 launch 교체가 움직임을 만들지 않게 한다.

profile manager를 두 launch 밖에 둔 이유는 현재 launch를 중지하면서 전환 서비스를 제공하는
노드까지 같이 죽는 자기종료 문제를 피하기 위해서다.

## 6. ROS 2 로그 분석이 MLOps가 되는 조건

단순히 로그에서 `error` 문자열을 찾는 것은 규칙 기반 모니터링이다. MLOps가 되려면 데이터와
모델의 생명주기를 재현할 수 있어야 한다.

1. `/rosout` 원본을 변경 불가능한 JSONL로 수집한다.
2. 같은 window 규칙으로 학습 dataset을 만든다.
3. dataset hash, feature schema, candidate version을 기록한다.
4. gate를 통과한 candidate만 Production으로 승격한다.
5. live와 replay에 같은 inference를 적용한다.
6. incident에 모델 상태와 원본 증거를 함께 보여 준다.

모델은 “평소와 다르다”를 잘 찾고, 원인 규칙은 “어떤 계층을 먼저 볼지”를 설명한다. 둘을
결합하되 제어권을 주지 않는 것이 현재 프로젝트의 안전 경계다.

## 7. 자주 헷갈리는 질문

### Q. 20 Hz로 보내면 로봇 속도가 더 빨라지는가?

아니다. 갱신 빈도와 속도 크기는 별개다. 최대 선속도는 계속 `0.05 m/s`, 최대 각속도는
`0.3 rad/s`이며 smoother는 그 사이 변화만 더 촘촘하게 만든다.

### Q. 브라우저가 멈추면 DELETE 요청을 못 보내는데 왜 정지하는가?

TB1 로컬 authorization이 0.35초마다 갱신되지 않으면 0을 출력하고 MANUAL 권한을 반납하기
때문이다. 네트워크의 “정지 메시지 전달”이 아니라 “계속된 허가의 부재”로 정지한다.

### Q. 순찰 중 한 지점이 실패하면 다음 지점으로 넘어가도 되는가?

현재 안전 정책에서는 안 된다. 예상 경로를 벗어났거나 localization·장애물 문제가 있을 수
있으므로 전체 순찰을 실패 처리하고 사람이 원인을 확인한다.

### Q. 이상 탐지 모델이 원인을 확정하는가?

아니다. 모델 점수와 규칙 confidence는 조사 우선순위다. 확정 근거는 ROS 상태, TF, 센서,
systemd, 원본 로그와 현장 관찰이다.

### Q. 왜 실제 지도 파일을 Git에 넣지 않는가?

지도는 현장 정보이고 자주 바뀌며 binary 산출물도 포함한다. Git에는 생성·검증 절차와 설정만
두고 실제 지도와 pose graph는 로봇의 운영 데이터 경로에 보관한다.

## 8. Nav2가 non-zero 속도를 내도 로봇이 움직이지 않을 수 있는 이유

계획 경로가 존재하고 `/cmd_vel`에 0이 아닌 값이 보인다는 사실만으로 바퀴가 실제로 움직였다고
판단할 수 없다. 모터·감속기·바닥 마찰에는 구동 임계값이 있고, 그보다 작은 명령은 소프트웨어
계층을 모두 통과해도 실제 pose 변화를 만들지 못한다.

DWB의 최소 속도는 controller plugin의 `min_speed_xy`, `min_speed_theta`가 결정한다.
`min_rotational_vel`은 behavior server에서 사용하는 이름이므로 이를 설정했다고 DWB의 가장 작은
회전 샘플이 커지는 것은 아니다. 이 둘을 혼동하면 다음과 같은 현상이 생긴다.

```text
path 생성 -> DWB의 아주 작은 회전 명령 -> smoother/arbiter/watchdog 통과
          -> 바퀴 정지 -> progress checker timeout
```

진단할 때는 한 토픽만 보지 않고 raw controller, smoother, arbiter, watchdog, 최종 `/cmd_vel`,
odometry를 같은 시간 창에서 비교한다. 최소 속도는 실측 deadband보다 작지 않게 정하되 최대
속도 상한과 watchdog은 그대로 유지한다. 제자리 회전이 필요하다면 `min_vel_x`는 0으로 두고
속도 벡터의 최소 크기인 `min_speed_xy`만 설정한다.

Humble처럼 배포판 전환기에 노드 이름이 바뀐 설정은 실제 parameter dump로 확인해야 한다.
TurtleBot3 기준 파일의 `recoveries_server` 섹션을 현재 `behavior_server` 실행 파일에 넘기면 노드
이름이 일치하지 않아 기본 회전 속도가 남을 수 있다. 이때 downstream smoother가 최종 상한은
지켜도 raw recovery가 급격히 상승하고, authorization이 늦게 열리면 이미 상승한 값을 arbiter가
받아 체감상 갑작스러운 회전이 될 수 있다.

BT action acknowledgement timeout과 fleet lease timeout도 구분해야 한다. 전자는 같은 로봇 안의
Nav2 서버가 부하 중 요청을 받았는지 기다리는 시간이고, 후자는 관제가 계속 운전을 허가하는지
판단하는 안전 시간이다. 전자만 2초로 늘리면 느린 planner를 불필요한 recovery로 바꾸지 않으면서
통신 단절 시 lease 취소와 watchdog 정지는 그대로 유지할 수 있다.

## 9. 실차 검증 전에 설명할 수 있어야 하는 것

- 화면 드래그 방향이 `base_link +X` yaw로 바뀌는 과정
- smoother, arbiter, watchdog의 책임 차이
- deadman이 통신 단절에도 fail-safe인 이유
- 순찰 재시작 시 자동 재개하지 않는 이유
- MAPPING과 NAVIGATION의 상호 배타성
- MLOps 모델 상태와 원인 규칙이 안전 제어와 분리된 이유
- `/cmd_vel` non-zero와 실제 odometry 변화를 함께 봐야 하는 이유
