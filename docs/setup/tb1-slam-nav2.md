# TB1 SLAM과 Nav2 운영 절차

이 문서는 TB1 한 대의 지도 작성과 저장 지도 기반 자율주행을 재현한다. 이동 명령이
포함된 절차는 바닥의 안전한 실습 구역, 충분한 여유 공간과 즉시 e-stop 가능한 상태에서만
수행한다.

## 1. 무이동 사전 점검

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash
export ROS_DOMAIN_ID=42
export TURTLEBOT3_MODEL=burger
export LDS_MODEL=LDS-02

systemctl --user is-active \
  tb1-bringup \
  tb1-safety-watchdog \
  tb1-robot-agent \
  tb1-zenoh-bridge

ros2 topic echo /scan --once --qos-reliability best_effort
ros2 topic echo /odom --once
timeout 5 ros2 run tf2_ros tf2_echo odom base_footprint
timeout 5 ros2 run tf2_ros tf2_echo base_link base_scan
ros2 topic echo /cmd_vel --once
```

정상 기준:

- 네 서비스가 모두 `active`
- `/scan`, `/odom` 메시지 수신
- 두 TF가 초기 대기 뒤 출력
- `/cmd_vel`의 선속도와 각속도가 모두 0

## 2. 패키지 빌드와 테스트

```bash
cd ~/turtlebot-fleet-ops
source /opt/ros/humble/setup.bash

rosdep check \
  --from-paths robot \
  --ignore-src \
  --rosdistro humble \
  --skip-keys ament_python

colcon build \
  --base-paths robot \
  --packages-select fleet_navigation \
  --symlink-install

source install/setup.bash
ROS_DOMAIN_ID=142 colcon test \
  --packages-select fleet_navigation
colcon test-result --verbose
```

## 3. SLAM 무이동 시작 검증

로봇을 움직이지 않은 상태에서 먼저 실행한다.

```bash
ros2 launch fleet_navigation slam.launch.py
```

다른 SSH 터미널에서 확인한다.

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash
export ROS_DOMAIN_ID=42

ros2 node info /slam_toolbox
ros2 topic info /scan_normalized --verbose
ros2 topic echo /scan_normalized --once --qos-reliability best_effort
ros2 topic echo /map --once --qos-durability transient_local
timeout 5 ros2 run tf2_ros tf2_echo map odom
ros2 topic info /cmd_vel --verbose
```

`/scan_normalized`는 매번 360개이고 0~359도, 1도 간격이어야 한다. SLAM은 지도를
만들 뿐 속도 명령을 발행하지 않는다. 이 시점의 `/cmd_vel` Publisher는 watchdog
하나여야 하고 값은 0이어야 한다. `zenoh_bridge_ros2dds`가 `/cmd_vel` Publisher로
보이면 양쪽 allow-list 적용 상태를 먼저 확인한다.

## 4. 저속 수동 매핑

다음 물리 조건을 사용자가 직접 확인한 뒤 진행한다.

- 로봇을 바닥에 놓고 전후좌우 최소 1m 확보
- 케이블과 낙하 위험 제거
- LDS-02 GPIO 임시 점퍼 고정 상태 확인
- e-stop 명령을 즉시 실행할 별도 터미널 준비
- 사람 한 명이 로봇을 계속 시야 안에 둠

teleop 출력은 반드시 안전 입력으로 remap한다.

```bash
ros2 run turtlebot3_teleop teleop_keyboard \
  --ros-args \
  -r /cmd_vel:=/safety/cmd_vel_in
```

벽과 코너를 LiDAR가 여러 각도에서 보도록 천천히 한 바퀴를 만들고 출발 위치로
돌아와 loop closure를 확인한다. 급회전과 로봇을 손으로 들어 옮기는 행동은 피한다.

긴급 정지:

```bash
ros2 service call \
  /safety_watchdog/set_estop \
  std_srvs/srv/SetBool \
  "{data: true}"
```

## 5. 지도와 pose graph 저장

```bash
cd ~/turtlebot-fleet-ops/robot/fleet_navigation/maps

ros2 run nav2_map_server map_saver_cli \
  -f "$PWD/tb1_lab"

ros2 service call \
  /slam_toolbox/serialize_map \
  slam_toolbox/srv/SerializePoseGraph \
  "{filename: '$PWD/tb1_lab'}"

ls -lh tb1_lab.*
grep -E '^(image|resolution|origin|negate|occupied_thresh|free_thresh):' \
  tb1_lab.yaml
```

RViz에서 벽의 이중선, 끊긴 벽, 비정상적인 회전과 출발·종료 구간의 어긋남을 확인한다.
품질 검토를 통과하지 못한 지도는 Nav2 입력으로 사용하지 않는다.

## 6. 저장 지도 기반 Nav2 시작

SLAM 프로세스를 종료한 뒤에만 실행한다.

```bash
ros2 launch fleet_navigation navigation.launch.py \
  map:=$HOME/turtlebot-fleet-ops/robot/fleet_navigation/maps/tb1_lab.yaml
```

다른 터미널에서 lifecycle과 안전 경계를 확인한다.

```bash
ros2 lifecycle get /map_server
ros2 lifecycle get /amcl
ros2 lifecycle get /controller_server
ros2 action info /navigate_to_pose
ros2 topic info /cmd_vel --verbose
ros2 topic info /safety/cmd_vel_in --verbose
```

AMCL 초기 위치를 설정한 뒤, 실제 지도에서 장애물이 없는 0.2~0.5m 이내의 첫 Goal을
선택한다. 정확한 좌표는 RViz와 현재 지도를 보고 정하며 문서 예시 값을 그대로 보내지
않는다.

```bash
ros2 action send_goal \
  /navigate_to_pose \
  nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: X, y: Y}, orientation: {w: 1.0}}}}" \
  --feedback
```

## 7. 실패 시 확인 순서

1. `/scan`, `/scan_normalized`, `/odom`의 실제 메시지가 최신인가
2. `map -> odom -> base_footprint -> base_link -> base_scan` TF가 이어지는가
3. Map Server·AMCL·Nav2 lifecycle이 `active`인가
4. AMCL 초기 위치를 지정했는가
5. global/local costmap에 센서 장애물이 나타나는가
6. `/safety/cmd_vel_in` Publisher와 watchdog 구독이 연결됐는가
7. e-stop 또는 중립 재무장 대기 상태인가
8. Goal이 지도 장애물 내부나 unknown 영역에 있지 않은가
9. `/cmd_vel` Publisher가 watchdog 하나뿐인가

패키지 설치가 끝나지 않은 상태에서 `dpkg` 잠금을 강제로 지우지 않는다. 먼저
`pgrep -af 'apt-get|dpkg'`, `/var/log/dpkg.log`, I/O 증가 여부로 실제 진행을 확인한다.
