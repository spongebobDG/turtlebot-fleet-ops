# TB1 안전 수동주행 및 Watchdog 검증 절차

## 목표

TB1에 전달되는 모든 수동 속도 명령을 로봇 내부의 `safety_watchdog`이
검사하도록 만들고 다음 동작을 실제 로봇에서 검증한다.

- 최대 선속도와 각속도 제한
- 입력 명령이 끊긴 뒤 0.5초 이내 정지 명령 발행
- 비상정지 활성화 즉시 0 속도 발행
- 비상정지 해제 후 중립 명령을 받아야 재가동
- 조작기 종료 또는 네트워크 명령 중단 시 정지

현재 자동 검증까지 완료됐으며 실차 결과는 아직 기록하지 않았다.

## 왜 이 구조를 사용하는가

조작기, 웹 서버와 미래의 Fleet Manager가 실제 `/cmd_vel`에 직접 명령을
보내면 각 프로그램이 서로 다른 속도 제한과 timeout 정책을 가질 수 있다.
따라서 실제 모터 명령으로 들어가기 직전에 하나의 규칙 기반 안전 계층을 둔다.

```text
teleop / web / fleet command
             |
             v
    /safety/cmd_vel_in
             |
             v
      [safety_watchdog]
       - velocity clamp
       - command timeout
       - emergency stop
       - neutral re-arm
             |
             v
          /cmd_vel
             |
             v
      TurtleBot3 OpenCR
```

안전 관련 최종 판단은 LLM이나 원격 웹 서버가 아니라 TB1 내부에서 실행하는
규칙 기반 ROS 2 노드가 담당한다.

## 기본 파라미터

| 파라미터 | TB1 값 | 의미 |
| --- | ---: | --- |
| `input_topic` | `/safety/cmd_vel_in` | 검사를 받기 전 속도 명령 |
| `output_topic` | `/cmd_vel` | TurtleBot3에 전달되는 안전 명령 |
| `timeout_sec` | `0.5` | 마지막 명령의 유효 시간 |
| `max_linear_x` | `0.05 m/s` | 전진·후진 속도 절댓값 제한 |
| `max_angular_z` | `0.3 rad/s` | 회전 속도 절댓값 제한 |
| `neutral_epsilon` | `0.001` | 중립으로 인정할 속도 오차 |
| `publish_rate_hz` | `20 Hz` | 안전 출력 발행 주기 |

설정 파일은
`robot/safety_watchdog/config/tb1.yaml`에 있다.

## 반드시 지킬 물리 안전 조건

첫 시험을 시작하기 전에 다음을 직접 확인한다.

- [ ] TB1 주변 최소 1 m 이상의 빈 공간 확보
- [ ] 로봇을 바로 잡을 수 있는 위치에 작업자 대기
- [ ] 전원 스위치에 즉시 손이 닿는 상태
- [ ] 첫 속도 제한 시험은 바퀴를 바닥에서 띄우고 수행
- [ ] 바퀴와 케이블 주변에 손, 옷과 공구가 없는 상태
- [ ] 다른 터미널이나 프로그램이 `/cmd_vel`을 발행하지 않는 상태
- [ ] 배터리 전압이 비정상적으로 낮지 않은 상태

소프트웨어 비상정지는 물리적인 전원 차단 장치를 대체하지 않는다.

## 1. TB1에 소스 내려받기

TB1 SSH 터미널에서 실행한다.

```bash
cd ~

if [ ! -d ~/turtlebot-fleet-ops/.git ]; then
  git clone https://github.com/spongebobDG/turtlebot-fleet-ops.git
fi

cd ~/turtlebot-fleet-ops
git fetch origin
git switch feat/phase-2-safe-teleoperation
git pull --ff-only
git log -2 --oneline --decorate
```

이력에 다음 기능 커밋들이 포함되어 있어야 한다.

```text
4630820 fix: require neutral command after emergency stop
3626fd4 feat: add TurtleBot safety watchdog
```

## 2. TB1에서 빌드와 자동 테스트

이 단계는 로봇을 움직이지 않는다.

```bash
cd ~/turtlebot-fleet-ops

source /opt/ros/humble/setup.bash

rosdep check \
  --from-paths robot \
  --ignore-src \
  --rosdistro humble

colcon build \
  --base-paths robot \
  --packages-select safety_watchdog \
  --symlink-install

source install/setup.bash

ROS_DOMAIN_ID=142 colcon test \
  --packages-select safety_watchdog \
  --event-handlers console_direct+

colcon test-result --verbose
```

`ROS_DOMAIN_ID=142`는 테스트 메시지를 실제 TB1 bringup 도메인 42와 분리하기
위한 값이다. 242처럼 너무 큰 값은 기본 DDS 포트 계산 범위를 벗어날 수 있다.

정상 기준:

```text
Summary: 1 package finished
Summary: 13 tests, 0 errors, 0 failures, 0 skipped
```

`SelectableGroups dict interface is deprecated` 경고는 Humble에 설치된 lint 도구의
의존성 경고다. 현재 작성한 안전 로직의 테스트 실패는 아니며 별도 업그레이드
과제로 남긴다.

## 3. Bringup과 Watchdog 실행

여기부터는 터미널을 나눠 사용한다. 첫 실차 시험 전에는 바퀴를 띄운다.

### 터미널 A: TurtleBot3 bringup

기존 TB1 bringup을 실행한다.

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash

export ROS_DOMAIN_ID=42
export TURTLEBOT3_MODEL=burger
export LDS_MODEL=LDS-02

ros2 launch turtlebot3_bringup robot.launch.py
```

### 터미널 B: Safety Watchdog

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash
export ROS_DOMAIN_ID=42

ros2 launch safety_watchdog safety_watchdog.launch.py
```

정상 시작 로그에는 제한값과 timeout이 표시된다.

```text
Safety watchdog ready: ... timeout=0.500s,
max_linear_x=0.050m/s, max_angular_z=0.300rad/s
Command timeout; publishing zero velocity
```

시작 직후 명령이 없으므로 `TIMEOUT` 상태에서 0 속도를 발행하는 것이 정상이다.

### 터미널 C: 연결 구조 확인

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash
export ROS_DOMAIN_ID=42

ros2 node info /safety_watchdog
ros2 topic info /safety/cmd_vel_in --verbose
ros2 topic info /cmd_vel --verbose
ros2 service type /safety_watchdog/set_estop
ros2 param dump /safety_watchdog
```

검증 기준:

- `/safety_watchdog` 노드가 존재한다.
- `/safety/cmd_vel_in`에 watchdog Subscriber가 존재한다.
- `/cmd_vel`에 watchdog Publisher가 존재한다.
- `set_estop` 서비스 형식이 `std_srvs/srv/SetBool`이다.
- 위 표의 TB1 파라미터가 실제 출력과 일치한다.
- watchdog 외의 예상하지 않은 `/cmd_vel` Publisher가 있으면 시험을 중단한다.

## 4. 명령이 없을 때 정지 출력 확인

터미널 C에서 실행한다.

```bash
timeout 2 ros2 topic echo /cmd_vel
echo "ZERO_ECHO_EXIT=$?"
```

2초 동안 반복해서 다음 값이 보여야 한다.

```yaml
linear:
  x: 0.0
angular:
  z: 0.0
```

`ZERO_ECHO_EXIT=124`는 `timeout`이 2초 뒤 구독 명령을 종료했다는 뜻이므로
예상 결과다.

## 5. 속도 제한 시험

바퀴를 바닥에서 띄운 상태에서 수행한다.

터미널 C에서 안전 출력 관찰을 계속한다.

```bash
ros2 topic echo /cmd_vel
```

새 터미널 D에서 제한을 초과하는 시험 입력을 1초 동안 보낸다.

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash
export ROS_DOMAIN_ID=42

timeout 1 ros2 topic pub -r 10 \
  /safety/cmd_vel_in \
  geometry_msgs/msg/Twist \
  "{linear: {x: 1.0}, angular: {z: 2.0}}"

echo "LIMIT_INPUT_EXIT=$?"
```

입력은 `1.0 m/s`, `2.0 rad/s`지만 `/cmd_vel` 출력은 다음 값을 넘으면 안 된다.

```yaml
linear:
  x: 0.05
angular:
  z: 0.3
```

입력 프로세스가 종료된 뒤 0.5초 이내에 출력이 다시 0이 되어야 한다.

## 6. 저속 직진·회전·정지 시험

속도 제한 시험을 통과한 후 넓은 바닥에서 수행한다.

전진:

```bash
timeout 1 ros2 topic pub -r 10 \
  /safety/cmd_vel_in \
  geometry_msgs/msg/Twist \
  "{linear: {x: 0.03}, angular: {z: 0.0}}"
```

제자리 회전:

```bash
timeout 1 ros2 topic pub -r 10 \
  /safety/cmd_vel_in \
  geometry_msgs/msg/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.2}}"
```

명시적 정지:

```bash
ros2 topic pub --once \
  /safety/cmd_vel_in \
  geometry_msgs/msg/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.0}}"
```

각 시험 후 `/odom`의 위치 또는 방향 변화와 `/cmd_vel`의 0 복귀를 확인한다.

## 7. 비상정지와 중립 재무장 시험

비상정지 활성화:

```bash
ros2 service call \
  /safety_watchdog/set_estop \
  std_srvs/srv/SetBool \
  "{data: true}"
```

정상 응답:

```text
success: true
message: Emergency stop activated
```

비상정지 중에는 비영 속도 입력을 보내도 `/cmd_vel`이 계속 0이어야 한다.

비상정지 해제:

```bash
ros2 service call \
  /safety_watchdog/set_estop \
  std_srvs/srv/SetBool \
  "{data: false}"
```

해제 후 바로 비영 명령을 보내도 움직이지 않아야 한다. 다음 중립 명령을 먼저
보낸 뒤에만 새로운 이동 명령을 허용한다.

```bash
ros2 topic pub --once \
  /safety/cmd_vel_in \
  geometry_msgs/msg/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.0}}"
```

## 완료 체크리스트

- [x] WSL Humble `colcon build` 성공
- [x] WSL 격리 도메인에서 자동 테스트 13개 통과
- [x] `rosdep check` 통과
- [x] TB1에서 패키지 build와 자동 테스트 통과
- [x] 시작 직후 0 속도 출력 확인
- [x] 속도 clamp 확인
- [x] 입력 종료 뒤 timeout 정지 확인
- [x] 저속 직진과 정지 확인
- [x] 저속 회전과 정지 확인
- [x] 비상정지 중 입력 차단 확인
- [x] 비상정지 해제 후 중립 재무장 확인
- [x] 측정 결과와 발생한 문제를 학습 일지에 기록
- [x] keyboard teleop remap과 정지 확인

## 문제가 발생하면 확인할 순서

1. `ROS_DOMAIN_ID=42`가 모든 실차 터미널에서 같은지 확인한다.
2. `/safety_watchdog` 노드 존재 여부를 확인한다.
3. `/safety/cmd_vel_in` Publisher와 Subscriber 수를 확인한다.
4. `/cmd_vel`에 예상하지 않은 Publisher가 있는지 확인한다.
5. watchdog 로그에서 `ACTIVE`, `TIMEOUT`, `ESTOP`, `WAITING_NEUTRAL` 전환을 확인한다.
6. `/odom`이 변하지 않으면 TurtleBot3 bringup과 OpenCR 연결을 확인한다.
7. 예상하지 않은 움직임이 있으면 소프트웨어 조사보다 먼저 전원을 차단한다.
