# TB1 Robot Agent 배포 및 검증 절차

## 목표

TB1의 `/battery_state`, `/odom`, `/scan`과 Raspberry Pi 자원을 집계해
`/fleet/robot_status`를 1 Hz로 발행하고, 실제 source가 끊겼을 때 stale fault로
전환되는지 확인한다.

이 절차는 상태 관측만 수행하며 모터 명령을 발행하지 않는다.

## 성공 기준

정상 bringup 중 한 상태 메시지에서 다음을 확인한다.

- `robot_id: tb1`, `hostname: tb1`
- `level: 0`
- battery/odom/scan의 received·fresh·valid가 모두 `true`
- `fault_codes: []`
- `scan_valid_points`가 0보다 큼
- CPU, memory, disk 값이 0~100 범위
- 상태 발행 주기가 약 1 Hz

## 1. 최종 main과 기능 브랜치 받기

Phase 2 watchdog을 실행 중이라면 해당 터미널에서 `Ctrl+C`로 먼저 종료한다.

```bash
cd ~/turtlebot-fleet-ops

git fetch --prune
git switch main
git pull --ff-only

source /opt/ros/humble/setup.bash

colcon build \
  --base-paths robot \
  --packages-select safety_watchdog \
  --symlink-install

ROS_DOMAIN_ID=142 colcon test \
  --base-paths robot \
  --packages-select safety_watchdog \
  --event-handlers console_cohesion+

colcon test-result --verbose
git log -1 --oneline --decorate
```

Phase 2 최종 성공 기준은 `18 tests, 0 errors, 0 failures`와 main 커밋
`9c0003a`다.

그 다음 Phase 3 브랜치를 받는다.

```bash
git fetch origin
git switch feat/phase-3-robot-agent
git pull --ff-only
```

## 2. 의존성 확인

```bash
source /opt/ros/humble/setup.bash

ros2 pkg prefix rosidl_default_generators
ros2 pkg prefix sensor_msgs
ros2 pkg prefix nav_msgs

python3 -m pip show psutil
```

`psutil`만 없을 때 설치한다.

```bash
sudo apt update
sudo apt install -y python3-psutil
```

이미 표시되면 다시 설치하지 않는다.

## 3. 빌드와 자동 테스트

```bash
cd ~/turtlebot-fleet-ops
source /opt/ros/humble/setup.bash

colcon build \
  --base-paths robot \
  --packages-up-to robot_agent \
  --symlink-install

source install/setup.bash

ROS_DOMAIN_ID=143 colcon test \
  --base-paths robot \
  --packages-select robot_agent \
  --event-handlers console_cohesion+

colcon test-result \
  --test-result-base build/robot_agent \
  --verbose
```

성공 기준은 Robot Agent `29 passed`, 오류와 실패 0개다. lint의
`SelectableGroups` deprecation warning은 Humble 도구 의존성 경고이며 실패가 아니다.

## 4. TB1 bringup 확인

기존 bringup 터미널에서 다음 환경을 사용한다.

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=42
export TURTLEBOT3_MODEL=burger
export LDS_MODEL=LDS-02

ros2 launch turtlebot3_bringup robot.launch.py
```

다른 터미널에서 source가 실제로 흐르는지 먼저 확인한다.

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=42

timeout 5 ros2 topic echo /battery_state --once
timeout 5 ros2 topic echo /odom --once
timeout 5 ros2 topic echo /scan --once \
  --qos-reliability best_effort
```

세 명령이 모두 실제 메시지를 받아야 한다.

## 5. Robot Agent 실행

새 터미널에서 실행한다.

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash
export ROS_DOMAIN_ID=42

ros2 launch robot_agent robot_agent.launch.py
```

시작 로그에는 robot ID, 출력 topic과 1 Hz 주기가 표시된다.

## 6. 구조화된 상태 확인

새 터미널에서 실행한다.

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash
export ROS_DOMAIN_ID=42

echo "=== AGENT NODE ==="
ros2 node info /robot_agent

echo "=== STATUS ENDPOINTS ==="
ros2 topic info /fleet/robot_status --verbose

echo "=== ONE STATUS ==="
timeout 8 ros2 topic echo /fleet/robot_status --once
echo "STATUS_ECHO_EXIT=$?"

echo "=== STATUS RATE ==="
timeout 6 ros2 topic hz /fleet/robot_status
echo "STATUS_HZ_EXIT=$?"
```

`topic hz`의 종료 코드 124는 6초 측정 제한이 끝났다는 뜻이므로 rate가 출력됐다면
실패가 아니다.

## 7. Stale 전환 시험

로봇을 평평한 바닥에 정지시키고 주변을 확보한다. Robot Agent는 계속 둔 채 bringup
터미널만 `Ctrl+C`로 종료한다. 6초 후 상태를 확인한다.

```bash
sleep 6
ros2 topic echo /fleet/robot_status --once
```

예상 결과:

- `level: 2`
- `ODOM_STALE` 또는 `ODOM_NOT_RECEIVED`
- `SCAN_STALE` 또는 `SCAN_NOT_RECEIVED`
- battery도 5초 이후 `BATTERY_STALE`

시험 후 bringup을 다시 시작하고 fault가 사라져 `level: 0`으로 복구되는지 확인한다.

## 문제 확인 순서

1. source topic에서 실제 메시지가 나오는가?
2. Robot Agent와 bringup의 `ROS_DOMAIN_ID`가 같은가?
3. `/scan` 구독 QoS가 BEST_EFFORT인가?
4. `source ~/turtlebot-fleet-ops/install/setup.bash`를 실행했는가?
5. `ros2 param dump /robot_agent`의 topic과 timeout이 예상과 같은가?
6. `ros2 topic info --verbose`에서 Publisher와 Subscriber가 연결됐는가?

## 현재 검증 체크리스트

- [x] WSL build 성공
- [x] Robot Agent 자동 테스트 29개 통과
- [x] custom interface 생성 확인
- [x] launch 시작과 초기 missing fault 확인
- [ ] TB1에서 정상 RobotStatus 확인
- [ ] TB1에서 약 1 Hz 확인
- [ ] source 종료 후 stale fault 확인
- [ ] bringup 재시작 후 OK 복구 확인
