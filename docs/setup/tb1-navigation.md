# TB1 매핑·Nav2·웹 목적지 운영 및 검증

이 절차는 TB1 한 대를 빈 실습 공간에서 저속으로 검증한다. 작업자는 시험 내내
전원 스위치에 손이 닿는 위치에 있어야 한다. 아래 체크박스는 실제 측정 뒤에만
완료로 바꾼다.

저장소 자동 검증 기준선은 Draft PR #7의 Ubuntu 22.04 ROS 2 Humble 실행이다. 5개
패키지 빌드와 격리 domain 142의 87개 테스트가 오류·실패·skip 없이 통과했다. 이 결과는
실차의 센서 정합, 정지시간 또는 자원 사용량을 대신하지 않는다.

## 1. 전제 조건

- TB1: Ubuntu 22.04, ROS 2 Humble, domain 42, CycloneDDS
- 관제 WSL과 TB1: Zenoh 1.9.0 브리지 및 Phase 4 Gateway
- `tb1-bringup`, `tb1-safety-watchdog`, `tb1-robot-agent` 정상
- TurtleBot3 Burger Nav2와 SLAM Toolbox 설치
- 바닥이 평평하고 사람·장애물이 없는 시험 공간

TB1에서 저장소를 빌드한다.

```bash
cd ~/turtlebot-fleet-ops
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
rosdep install --from-paths robot control --ignore-src -r -y
colcon build --base-paths robot control --symlink-install
source install/setup.bash
```

## 2. 공통 안전 확인

```bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 topic info /cmd_vel --verbose
ros2 topic echo /fleet/safety_status --once
```

정상 운용에서 `/cmd_vel` publisher의 node name은 `/safety_watchdog` 하나여야 한다.
Nav2, teleop 또는 arbiter가 직접 보이면 시험을 중단한다.

## 3. 매핑 프로필

수동 실행 시 기존 navigation 프로필을 먼저 정지한다.

```bash
systemctl --user stop tb1-navigation.service 2>/dev/null || true
ros2 launch navigation_agent tb1_mapping.launch.py
```

다른 TB1 터미널에서 teleop을 manual 입력으로 연결한다.

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 run turtlebot3_teleop teleop_keyboard \
  --ros-args -r cmd_vel:=/motion/manual/cmd_vel
```

아주 천천히 공간 외곽과 주요 장애물을 관측한다. 지도 loop closure가 안정된 뒤
저장한다.

```bash
cd ~/turtlebot-fleet-ops
infra/navigation/save-tb1-map.sh
ls -lh ~/.local/share/turtlebot-fleet-ops/maps/tb1/
```

최소한 `map.yaml`, map image, SLAM Toolbox pose graph 파일이 있어야 한다. 이 디렉터리는
저장소 밖이며 실제 공간 지도는 commit하지 않는다.

## 4. 주행 프로필

매핑 프로필과 teleop을 완전히 끝낸 뒤 실행한다.

```bash
systemctl --user stop tb1-mapping.service 2>/dev/null || true
cd ~/turtlebot-fleet-ops
infra/navigation/start-tb1-navigation.sh
```

다음 graph를 확인한다.

```bash
ros2 action info /navigate_to_pose
ros2 action info /tb1/navigation/navigate
ros2 service type /tb1/navigation/set_initial_pose
ros2 service type /tb1/navigation/set_motion_mode
ros2 topic info /motion/navigation/cmd_vel --verbose
ros2 topic info /safety/cmd_vel_in --verbose
ros2 topic info /cmd_vel --verbose
ros2 topic echo /fleet/navigation_status
```

처음에는 `LOCALIZING` 또는 `UNAVAILABLE`이 정상이다. 웹에서 초기 위치를 지정하고
그 이후의 새 `/amcl_pose`가 들어와야 `READY`가 된다.

## 5. 웹 초기 위치와 목적지

관제 PC에서 기존 Gateway와 Zenoh 브리지를 실행하고 `http://localhost:8000`을 연다.

1. 지도에서 `초기 위치` 모드를 선택한다.
2. 로봇 위치를 클릭하고 진행 방향으로 드래그한다.
3. `초기 위치 적용`을 누른다.
4. `READY`가 된 뒤 LiDAR 점과 지도 벽이 맞는지 확인한다.
5. `목적지` 모드에서 가까운 자유 셀을 클릭·드래그한다.
6. `목적지 전송` 후 거리, 경과시간, 예상시간, recovery와 lease age를 관찰한다.

WARN 로봇은 첫 요청이 409로 거부되고 fault 목록 확인 dialog가 나온다. 작업자가
확인한 경우에만 두 번째 요청이 `confirm_warnings=true`로 전송된다. 새 목표는 기존
목표를 자동 교체하지 않는다.

직접 API를 확인할 때는 다음 형태를 사용한다.

```bash
curl http://localhost:8000/api/robots/tb1/map
curl -X PUT http://localhost:8000/api/robots/tb1/localization/initial-pose \
  -H 'content-type: application/json' \
  -d '{"x":0.0,"y":0.0,"yaw":0.0}'
curl -X POST http://localhost:8000/api/robots/tb1/navigation/goals \
  -H 'content-type: application/json' \
  -d '{"x":0.5,"y":0.0,"yaw":0.0,"confirm_warnings":false}'
```

좌표는 실제 지도의 자유 셀 값으로 바꾼다. 지도 밖, unknown, occupied는 422여야 한다.

## 6. systemd 프로필 설치

```bash
mkdir -p ~/.config/systemd/user
cp infra/systemd/user/tb1-mapping.service ~/.config/systemd/user/
cp infra/systemd/user/tb1-navigation.service ~/.config/systemd/user/
systemctl --user daemon-reload
```

둘 중 하나만 enable한다.

```bash
systemctl --user enable --now tb1-navigation.service
systemctl --user status tb1-navigation.service
systemctl --user is-active tb1-mapping.service
```

두 번째 명령은 `active`, 세 번째 명령은 `inactive`여야 한다. 프로필 전환은 다음처럼
명시적으로 수행한다.

```bash
systemctl --user stop tb1-navigation.service
systemctl --user start tb1-mapping.service
```

## 7. 실차 완료 체크리스트

### 지도와 위치추정

- [ ] 안전 teleop으로 지도와 pose graph 저장
- [ ] 저장 지도 프로필로 재시작
- [ ] 웹 초기 위치 적용 뒤 `READY`
- [ ] 지도와 LiDAR 정합을 스크린샷 또는 rosbag으로 기록

### 기본 주행

- [ ] 가까운 목표를 `0.05 m/s`, `0.3 rad/s` 이하로 도달
- [ ] 활성 목표 명시적 취소와 정지
- [ ] WARN 확인 전 409, 확인 후 목표 접수
- [ ] 중복 목표 409
- [ ] `/cmd_vel` publisher가 watchdog 하나뿐

속도 상한은 동시에 기록한다.

```bash
ros2 topic echo /motion/navigation/cmd_vel
ros2 topic echo /cmd_vel
```

### e-stop

- [ ] 주행 중 e-stop 직후 `/cmd_vel` 0
- [ ] 활성 command와 Gateway lease 제거
- [ ] 해제 직후 `WAITING_NEUTRAL`
- [ ] IDLE 0으로 재무장한 뒤에도 이전 목표 자동 재출발 없음

### 통신 단절

주행 중 Gateway 또는 WSL Zenoh 브리지를 하나만 정지하고 시간을 기록한다.

```bash
date --iso-8601=ns
systemctl --user stop fleet-gateway.service
ros2 topic echo /fleet/navigation_status
ros2 topic echo /cmd_vel
```

- [ ] 2초 후 `LEASE_EXPIRED`
- [ ] 단절 시작 2.5초 이내 `/cmd_vel=0`
- [ ] 복구 뒤 이전 목표 자동 재개 없음

### 프로세스 장애

각 시험은 한 번에 하나의 PID만 종료하고 systemd의 새 `MainPID`를 기록한다.

- [ ] `navigation_agent` 종료: authorization 0.5초 만료와 0 출력
- [ ] agent 재시작: 남은 Nav2 목표 취소, IDLE 시작
- [ ] Nav2 종료: 안전 정지, 1초 부재 뒤 `FAILED`, systemd 복구
- [ ] arbiter 종료: watchdog timeout 정지와 respawn
- [ ] watchdog 종료: 재시작 후 `WAITING_NEUTRAL`, 활성 목표 취소와 자동 재출발 없음

### 자원 사용량

10분 주행 동안 10초 간격으로 기록한다.

```bash
pidstat -r -u -p ALL 10 60
free -h
journalctl --user -u tb1-navigation.service --since '-15 min'
```

- [ ] CPU 90% 경고가 지속되지 않음
- [ ] 메모리 90% 경고가 지속되지 않음
- [ ] 평균, 최대, 경고 지속시간을 학습 일지에 기록

## 8. 결과 기록 형식

각 시험에 시작 시각, 종료 시각, 실행 명령, command ID, 기대값, 실제값, 관련
`journalctl` 구간과 판정을 남긴다. 미실행 항목은 `미확인`으로 둔다. 모든 항목과
로그가 채워지기 전에는 Phase 5를 완료로 바꾸지 않는다.
