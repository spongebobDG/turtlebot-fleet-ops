# Safety Watchdog

TurtleBot에 전달되는 속도 명령 앞에 두는 규칙 기반 안전 계층이다.

```text
teleop / fleet command
        |
        v
/safety/cmd_vel_in
        |
        v
[safety_watchdog]
  - 속도 제한
  - 0.5초 timeout
  - emergency stop
        |
        v
     /cmd_vel
        |
        v
 TurtleBot3 base
```

## 기본 정책

- 선속도 절댓값을 `0.05 m/s` 이하로 제한한다.
- 각속도 절댓값을 `0.3 rad/s` 이하로 제한한다.
- 새 명령이 `0.5초` 동안 없으면 0 속도를 발행한다.
- 비상정지가 활성화되면 입력 명령을 무시하고 0 속도를 발행한다.
- 비상정지를 해제한 뒤 중립(0 속도) 명령을 받아야 다시 움직인다.
- 프로세스 시작·재시작도 `WAITING_NEUTRAL`에서 시작한다.
- `NaN`과 무한대 입력은 0으로 바꾼다.
- 차동구동에 필요한 `linear.x`와 `angular.z`만 전달한다.
- `/fleet/safety_status`로 watchdog mode, e-stop과 motion-armed 상태를 발행한다.

이 노드는 물리적인 비상정지 장치를 대체하지 않는다. 실차 시험 중에는 항상
로봇 전원 스위치에 접근할 수 있어야 한다.

## 빌드

ROS 2 Humble 환경에서 저장소 루트를 기준으로 실행한다.

```bash
source /opt/ros/humble/setup.bash
colcon build \
  --base-paths robot \
  --packages-select safety_watchdog \
  --symlink-install
source install/setup.bash
```

## 실행

```bash
ros2 launch safety_watchdog safety_watchdog.launch.py
```

조작기나 명령 발행자는 실제 `/cmd_vel`이 아니라 안전 입력으로 보낸다.

```bash
ros2 run turtlebot3_teleop teleop_keyboard \
  --ros-args \
  -r cmd_vel:=/safety/cmd_vel_in
```

Phase 5의 motion arbiter가 실행 중이면 teleop을 `/safety/cmd_vel_in`에 직접 연결하지
않고 `/motion/manual/cmd_vel`에 연결한다. arbiter의 MANUAL mode가 선택한 입력만
watchdog으로 전달한다.

비상정지 활성화:

```bash
ros2 service call \
  /safety_watchdog/set_estop \
  std_srvs/srv/SetBool \
  "{data: true}"
```

비상정지 해제:

```bash
ros2 service call \
  /safety_watchdog/set_estop \
  std_srvs/srv/SetBool \
  "{data: false}"
```

해제 직후에는 계속 들어오는 비영 속도 명령도 무시한다. 조작기에서 이동 키를
놓아 중립 명령을 한 번 보낸 뒤에만 새로운 이동 명령이 허용된다.
