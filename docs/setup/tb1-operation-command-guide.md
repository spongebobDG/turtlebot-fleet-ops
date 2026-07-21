# TB1 구동 명령어와 일상 운영 가이드

## 1. 가장 중요한 결론

평상시에는 여러 `ros2 run` 또는 `ros2 launch` 명령을 터미널마다 직접 실행하지 않는다.
이 프로젝트는 필요한 ROS 2 명령을 `systemd` 서비스로 등록해 TB1과 관제 PC에서 자동 관리한다.

TB1 전원을 켠 뒤 관제 PC의 **PowerShell**에서 다음 명령 하나를 실행하는 것이 기본 절차다.

```powershell
cd C:\project\turtlebot-fleet-ops
powershell.exe -ExecutionPolicy Bypass -File .\scripts\control-pc\open_tb1_web_control.ps1
```

이 명령은 다음 작업을 수행한다.

1. WSL의 Zenoh 브리지, Fleet Gateway와 로그 MLOps 서비스를 시작한다.
2. `http://127.0.0.1:8000`을 연다.
3. TB1이 켜져 있으면 자동 연결하고, 꺼져 있으면 연결을 기다린다.
4. 로컬 로그 AI가 준비되지 않아도 웹 관제와 로봇 제어는 계속 실행한다.

브라우저를 자동으로 열고 싶지 않으면 다음처럼 실행한 뒤 Chrome에서 직접 접속한다.

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\control-pc\open_tb1_web_control.ps1 -NoBrowser
```

```text
http://localhost:8000
```

## 2. 명령을 실행하는 위치

| 위치 | 용도 | 기본 사용자·경로 |
| --- | --- | --- |
| Windows PowerShell | 웹 관제 시작, REST 상태 확인 | `C:\project\turtlebot-fleet-ops` |
| WSL Ubuntu 22.04 | Gateway, 관제 Zenoh, 로그 MLOps | 사용자 `fleetops`, `~/turtlebot-fleet-ops` |
| TB1 터미널 또는 SSH | 센서, watchdog, Robot Agent, 매핑, Nav2 | 사용자 `dg`, `~/turtlebot-fleet-ops` |

TB1에 SSH로 접속할 때는 호스트 별칭 또는 현재 LAN 주소를 사용한다. 주소와 비밀번호는 Git에
기록하지 않는다.

```powershell
ssh -i $HOME\.ssh\turtlebot_fleet_ops_ed25519 dg@<TB1_IP>
```

SSH 별칭 `tb1`을 설정했다면 다음처럼 사용할 수 있다.

```powershell
ssh tb1
```

## 3. 평상시 구동 순서

### 3.1 시작 전

1. TB1 주변과 예상 경로를 육안으로 확인한다.
2. 작업자가 로봇 전원과 웹의 비상정지에 접근할 수 있어야 한다.
3. TB1 전원을 켜고 약 30~90초 기다린다.
4. 관제 PC에서 1절의 `open_tb1_web_control.ps1`을 실행한다.
5. 웹에서 TB1이 `ONLINE`이고 배터리·LiDAR·odom 값이 갱신되는지 확인한다.

### 3.2 기존 지도에서 목적지 주행

1. 웹에서 `주행 모드` 또는 `NAVIGATION` 프로필을 선택한다.
2. TB1이나 Navigation 서비스를 새로 켠 뒤에는 `초기 위치`를 다시 설정한다.
3. `LiDAR로 현재 위치 찾기`를 누르고 정합률과 지도 내부 비율을 확인한다.
4. `초기 위치 적용`을 누른다.
5. 로봇 주변이 안전하면 `정지 해제`를 누른다.
6. `목적지` 모드에서 자유 공간의 위치부터 도착 시 로봇이 바라볼 방향으로 12px 이상 드래그한다.
7. `목적지 전송`을 누르고 남은 거리, recovery, LiDAR와 속도를 관찰한다.

현재 좁은 통로용 최소 LiDAR 기준은 `0.16m`다. TB1 footprint 반경 `0.14m`에 `0.02m`의
외곽 여유를 둔다. 주행 중 최소 거리가 `0.16m` 아래로 내려가면 활성 목표를 취소하고 정지한다.

### 3.3 새 지도 만들기

1. 웹에서 `새 지도` 또는 `MAPPING` 프로필을 선택한다.
2. 정지 해제 후 웹의 WASD 버튼이나 키보드로 천천히 이동한다.
3. 화면의 파란 TB1 화살표와 실시간 LiDAR·지도를 함께 확인한다.
4. 공간 전체를 그린 뒤 `지도 저장`을 누른다.
5. `주행 모드`로 전환한다.
6. LiDAR 자동 정렬과 초기 위치 적용을 다시 수행한 뒤 목적지를 보낸다.

`MAPPING`과 `NAVIGATION`은 동시에 실행되지 않는다. 프로필 전환 시 기존 모드를 정지한 뒤
새 모드를 시작하며, 전환 후 비상정지는 자동으로 해제되지 않는다.

### 3.4 수동 조종·순찰

- 수동 조종은 웹의 WASD를 누르고 있는 동안만 명령이 유지되는 deadman 방식이다.
- 브라우저가 닫히거나 명령이 끊기면 TB1 로컬 timeout으로 정지한다.
- 순찰점은 지도에서 위치와 도착 방향을 드래그해 2개 이상 등록한 뒤 순찰을 시작한다.
- 활성 목적지, 수동 세션과 순찰은 동시에 실행할 수 없다.

### 3.5 종료

1. 활성 목적지나 순찰을 취소한다.
2. 웹에서 `정지`를 눌러 `ESTOP`, `motion_armed=false`를 확인한다.
3. 로봇의 선속도와 각속도가 0인지 확인한다.
4. 그다음 TB1 전원을 끈다.

## 4. `ros2 run`, `ros2 launch`, `systemd`의 차이

### `ros2 run`

패키지 안의 실행 파일 하나를 실행한다.

```bash
ros2 run <패키지> <실행파일>
```

프로젝트 예시는 다음과 같다.

```bash
ros2 run navigation_agent profile_manager_node --ros-args \
  --params-file ~/turtlebot-fleet-ops/robot/navigation_agent/config/tb1.yaml

ros2 run navigation_agent validate_map \
  ~/.local/share/turtlebot-fleet-ops/maps/tb1/map.yaml \
  --min-known-cells 100 \
  --min-known-ratio 0.01 \
  --require-pose-graph
```

### `ros2 launch`

여러 ROS 노드와 설정을 한 번에 실행한다. Nav2, AMCL, motion arbiter처럼 여러 구성요소가 필요한
경우 사용한다.

```bash
ros2 launch <패키지> <launch 파일> [인수:=값]
```

프로젝트 예시는 다음과 같다.

```bash
ros2 launch turtlebot3_bringup robot.launch.py
ros2 launch safety_watchdog safety_watchdog.launch.py
ros2 launch robot_agent robot_agent.launch.py
ros2 launch navigation_agent tb1_mapping.launch.py
ros2 launch navigation_agent tb1_navigation.launch.py \
  map:=$HOME/.local/share/turtlebot-fleet-ops/maps/tb1/map.yaml
ros2 launch fleet_gateway fleet_gateway.launch.py
```

### `systemd --user`

위의 `ros2 run`과 `ros2 launch`를 로그인과 무관하게 실행하고, 장애 시 재시작하며, 로그를
`journalctl`로 관리한다. **실차 평상시 운영에서는 이 방식이 권장된다.**

예를 들어 다음 서비스 내부에서 실제 ROS 명령을 실행한다.

| 서비스 | 내부에서 실행하는 핵심 명령 |
| --- | --- |
| `tb1-bringup.service` | `ros2 launch turtlebot3_bringup robot.launch.py` |
| `tb1-safety-watchdog.service` | `ros2 launch safety_watchdog safety_watchdog.launch.py` |
| `tb1-robot-agent.service` | `ros2 launch robot_agent robot_agent.launch.py` |
| `tb1-profile-manager.service` | `ros2 run navigation_agent profile_manager_node ...` |
| `tb1-mapping.service` | `ros2 launch navigation_agent tb1_mapping.launch.py` |
| `tb1-navigation.service` | `ros2 launch navigation_agent tb1_navigation.launch.py ...` |
| `fleet-gateway.service` | `ros2 launch fleet_gateway fleet_gateway.launch.py` |

## 5. 서비스 상태 확인 명령

### 관제 PC의 WSL 서비스

PowerShell에서 실행한다.

```powershell
wsl.exe -d Ubuntu-22.04 -u fleetops -- systemctl --user is-active `
  fleet-control-zenoh.service fleet-gateway.service fleet-log-mlops.service
```

정상 기대값은 세 줄 모두 `active`다.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/robots
```

로그 확인:

```powershell
wsl.exe -d Ubuntu-22.04 -u fleetops -- journalctl --user `
  -u fleet-gateway.service -n 100 --no-pager
```

### TB1 서비스

TB1 SSH 터미널에서 실행한다.

```bash
systemctl --user is-active \
  tb1-network-ready.service \
  tb1-bringup.service \
  tb1-safety-watchdog.service \
  tb1-robot-agent.service \
  tb1-profile-manager.service \
  tb1-zenoh-bridge.service
```

현재 운전 프로필 확인:

```bash
systemctl --user is-active tb1-mapping.service tb1-navigation.service
```

기대값은 다음 중 하나다.

- IDLE: 둘 다 `inactive`
- 지도 작성: mapping만 `active`
- 저장 지도 주행: navigation만 `active`

최근 로그:

```bash
journalctl --user -u tb1-navigation.service -n 100 --no-pager
journalctl --user -u tb1-robot-agent.service -n 100 --no-pager
journalctl --user -u tb1-zenoh-bridge.service -n 100 --no-pager
```

## 6. 개발·진단을 위해 ROS 명령을 직접 실행하는 방법

직접 실행은 개발이나 장애 분석 때만 사용한다. 같은 노드를 systemd와 터미널에서 동시에
실행하면 토픽·서비스·action 이름과 `/cmd_vel` 소유권이 충돌한다.

### 6.1 공통 환경

TB1 터미널에서:

```bash
cd ~/turtlebot-fleet-ops
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash

export ROS_DISTRO=humble
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export TURTLEBOT3_MODEL=burger
```

WSL 터미널에서는 `turtlebot3_ws` 대신 프로젝트 overlay만 불러온다.

```bash
cd ~/turtlebot-fleet-ops
source /opt/ros/humble/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

### 6.2 Nav2 직접 실행

먼저 웹에서 비상정지를 건다. 그다음 TB1에서 자동 프로필 관리와 기존 navigation·mapping을
중지한다.

```bash
systemctl --user stop \
  tb1-profile-manager.service \
  tb1-navigation.service \
  tb1-mapping.service
```

환경을 source한 같은 터미널에서 실행한다.

```bash
ros2 launch navigation_agent tb1_navigation.launch.py \
  map:=$HOME/.local/share/turtlebot-fleet-ops/maps/tb1/map.yaml
```

종료는 `Ctrl+C`다. 직접 실행을 끝낸 뒤 서비스 운영으로 복구한다.

```bash
systemctl --user start tb1-profile-manager.service
systemctl --user start tb1-navigation.service
```

Navigation을 다시 시작하면 이전 AMCL 위치를 재사용하지 않는다. 웹에서 LiDAR 자동 정렬과 초기
위치 적용을 다시 수행하고, 그동안 비상정지를 유지한다.

### 6.3 SLAM 매핑 직접 실행

```bash
systemctl --user stop \
  tb1-profile-manager.service \
  tb1-navigation.service \
  tb1-mapping.service

ros2 launch navigation_agent tb1_mapping.launch.py
```

지도 저장은 프로젝트 스크립트를 사용하는 것이 권장된다.

```bash
bash ~/turtlebot-fleet-ops/infra/navigation/save-tb1-map.sh
```

종료 후 서비스 운영으로 복구한다.

```bash
systemctl --user start tb1-profile-manager.service
```

웹에서 `NAVIGATION` 프로필을 선택하고 초기 위치를 다시 설정한다.

### 6.4 Gateway 직접 실행

WSL에서 기존 Gateway만 중지하고 관제 Zenoh 브리지는 유지한다.

```bash
systemctl --user stop fleet-gateway.service

cd ~/turtlebot-fleet-ops
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file://$HOME/turtlebot-fleet-ops/infra/zenoh/cyclonedds-localhost.xml

ros2 launch fleet_gateway fleet_gateway.launch.py
```

`Ctrl+C`로 종료한 뒤 서비스로 복구한다.

```bash
systemctl --user start fleet-gateway.service
```

## 7. 자주 사용하는 ROS 2 진단 명령

다음 명령은 TB1에서 공통 환경을 source한 뒤 실행한다.

```bash
ros2 node list
ros2 topic list
ros2 service list
ros2 action list
```

센서와 속도 한 번 확인:

```bash
ros2 topic echo /scan --once --qos-reliability best_effort
ros2 topic echo /odom --once
ros2 topic echo /battery_state --once
ros2 topic echo /cmd_vel --once
```

주기 확인:

```bash
ros2 topic hz /scan --qos-reliability best_effort
ros2 topic hz /odom
```

TF 확인:

```bash
ros2 run tf2_ros tf2_echo map base_footprint
ros2 run tf2_ros tf2_echo odom base_footprint
ros2 run tf2_ros tf2_monitor base_scan odom
```

현재 프로젝트의 주요 상태 토픽:

```bash
ros2 topic echo /fleet/robot_status --once
ros2 topic echo /fleet/navigation_status --once
ros2 topic echo /fleet/safety_status --once
ros2 topic echo /fleet/mapping_status --once
```

## 8. 장애 상황별 복구

### 웹이 열리지 않을 때

PowerShell에서 관제 시작 명령을 다시 실행한다.

```powershell
cd C:\project\turtlebot-fleet-ops
powershell.exe -ExecutionPolicy Bypass -File .\scripts\control-pc\start_control_stack.ps1
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

### 웹은 열리지만 TB1이 OFFLINE일 때

1. TB1 전원과 Wi-Fi 주소를 확인한다.
2. TB1의 핵심 서비스와 Zenoh bridge 상태를 확인한다.
3. 관제 PC의 Zenoh 경로가 오래된 경우 관제 bridge만 재시작한다.

```powershell
wsl.exe -d Ubuntu-22.04 -u fleetops -- systemctl --user restart `
  fleet-control-zenoh.service
```

### 목적지 전송이 거부될 때

다음을 순서대로 확인한다.

1. 프로필이 `NAVIGATION`인지 확인한다.
2. `nav2_ready`, `localization_ready`, `safety_ready`가 모두 true인지 확인한다.
3. 비상정지가 해제되고 `motion_armed=true`인지 확인한다.
4. LiDAR 최소 거리가 `0.16m` 이상인지 확인한다.
5. 지도에서 목적지 위치와 방향을 드래그했는지 확인한다.
6. 활성 목적지·수동 세션·순찰이 이미 존재하지 않는지 확인한다.

```powershell
$tb1=(Invoke-RestMethod http://127.0.0.1:8000/api/robots).robots |
  Where-Object robot_id -eq 'tb1'
$tb1.navigation
$tb1.safety
$tb1.scan
```

### Navigation 서비스 재시작 뒤 UNAVAILABLE일 때

AMCL과 Nav2 lifecycle 활성화에는 시간이 필요하다. 30~60초 동안 로그를 확인한다.

```bash
journalctl --user -u tb1-navigation.service --since '2 minutes ago' --no-pager
```

`amcl: Activating`과 `Managed nodes are active`가 확인된 뒤 웹에서 초기 위치를 다시 적용한다.
목표를 반복해서 누르거나 안전 기준을 임의로 우회하지 않는다.

## 9. 금지하거나 주의할 명령

- 서비스가 실행 중인데 같은 `ros2 run` 또는 `ros2 launch`를 추가로 실행하지 않는다.
- `ros2 topic pub /cmd_vel ...`로 watchdog을 우회하지 않는다.
- 실차에서 `turtlebot3_teleop`을 안전 경로와 병렬로 실행하지 않는다.
- `MAPPING`과 `NAVIGATION`을 동시에 실행하지 않는다.
- 초기 위치 없이 목적지를 보내지 않는다.
- 활성 목적지가 있는데 새 목표로 덮어쓰려 하지 않는다. 먼저 취소한다.
- 로봇을 손으로 옮기기 전에는 비상정지를 걸고, 옮긴 뒤 초기 위치를 다시 설정한다.
- 로봇이 움직이는 동안 서비스 재시작이나 배포를 하지 않는다.

## 10. 관련 문서

- [웹 수동 조종·순찰·매핑 운영](tb1-web-patrol-mapping.md)
- [매핑·Nav2 운영 및 검증](tb1-navigation.md)
- [웹 관제 대시보드 운영](tb1-web-dashboard.md)
- [작업·감사·재부팅 복구](tb1-operations.md)
- [ROS 2 로그 MLOps 운영](ros2-log-mlops.md)
