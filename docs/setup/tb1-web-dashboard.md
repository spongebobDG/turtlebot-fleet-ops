# TB1 웹 관제 대시보드 운영 절차

## 목적

WSL에서 TB1 상태를 수신하고 `http://localhost:8000`에서 실시간 관제한다. 이 절차는
RobotStatus REST 조회, WebSocket 갱신, 비상정지, 통신 단절과 복구를 포함한다.

## 전제조건

- TB1에서 bringup, `safety_watchdog`, `robot_agent`가 실행 중이다.
- TB1과 WSL에 ROS 2 Humble과 `rmw_cyclonedds_cpp`가 설치돼 있다.
- 양쪽에 `zenoh-bridge-ros2dds` 1.9.0이 설치돼 있다.
- WSL 저장소에서 `fleet_gateway`를 빌드했다.
- TB1과 WSL의 시스템 시각 차이가 500ms 이내다.

## 1. Gateway 빌드와 테스트

WSL에서 실행한다.

```bash
cd ~/turtlebot-fleet-ops
source /opt/ros/humble/setup.bash

rosdep check \
  --from-paths control/fleet_gateway \
  --ignore-src \
  --rosdistro humble

colcon build \
  --base-paths interfaces control \
  --packages-up-to fleet_gateway \
  --symlink-install

source install/setup.bash

colcon test \
  --base-paths interfaces control \
  --packages-select fleet_gateway

colcon test-result --verbose
```

## 2. 임시 수동 실행

TB1에서:

```bash
cd ~/turtlebot-fleet-ops
export ROS_DISTRO=humble
export ROS_DOMAIN_ID=42
bash infra/zenoh/start-robot-bridge.sh
```

WSL 첫 번째 터미널에서:

```bash
cd ~/turtlebot-fleet-ops
export ROBOT_ADDRESS=tb1
export ROS_DOMAIN_ID=42
bash infra/zenoh/start-control-bridge.sh
```

WSL 두 번째 터미널에서:

```bash
cd ~/turtlebot-fleet-ops
export ROS_DOMAIN_ID=42
bash infra/zenoh/start-control-gateway.sh
```

## 3. 기본 상태 확인

PowerShell 또는 WSL에서 확인한다.

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/robots
```

기대 결과:

- `known_robots`는 1이다.
- `online_robots`는 1이다.
- `tb1.online`은 `true`다.
- heartbeat age는 보통 1초 미만이다.
- 배터리, odom, scan, CPU, 메모리와 Wi-Fi 값이 갱신된다.

브라우저에서 `http://localhost:8000`을 열고 다음을 확인한다.

- 상단 연결 상태가 실시간 연결이다.
- TB1 상태가 `OK` 또는 실제 fault 상태와 일치한다.
- 카드의 heartbeat와 센서 값이 갱신된다.
- 1280×720 이상의 화면에서는 로봇 상태, 지도 제어, 작업·고장·감사 로그가 페이지
  스크롤 없이 한 화면에 표시된다. 긴 기록만 각 카드 안에서 스크롤한다.
- 개발자 도구에 정적 파일 404나 WebSocket 오류가 없다.

목적지·수동 조종·순찰·매핑 프로필과 로그 원인 분석은
[Phase 8 운영 절차](tb1-web-patrol-mapping.md)를 따른다. 목적지와 웨이포인트에는 위치뿐 아니라
도착 방향이 필수이며, 수동 버튼은 누르고 있는 동안만 유효하다.

## 4. 비상정지 검증

로봇 주변을 비우고 바퀴가 움직이지 않는 상태에서 웹의 비상정지 버튼을 누른다.
API로 검증할 때는 다음 요청을 사용한다.

```bash
curl -X POST \
  -H 'Content-Type: application/json' \
  -d '{"engaged":true}' \
  http://127.0.0.1:8000/api/robots/tb1/estop
```

TB1에서 0 속도를 확인한다.

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 topic echo /cmd_vel --once
```

해제 응답에 `waiting for a neutral command`가 포함되는지 확인한다. 해제 직후 기존의
비중립 명령이 남아 있어도 로봇은 움직이면 안 된다.

## 5. 오프라인 안전 검증

로봇의 로컬 watchdog은 유지한 채 Zenoh 브리지만 중단한다.

```bash
systemctl --user stop tb1-zenoh-bridge.service
```

3초가 지난 후 `GET /api/robots/tb1`에서 `online=false`인지 확인한다. 이 상태에서
비상정지 해제를 요청하면 HTTP 409와 다음 메시지가 나와야 한다.

```text
Cannot release emergency stop while robot is offline
```

브리지를 복구한다.

```bash
systemctl --user start tb1-zenoh-bridge.service
```

`online=true`로 돌아온 후 비상정지를 해제하고 중립 명령을 보내 재무장한다.

감사 로그에는 단절과 복구가 한 번씩 기록돼야 한다.

```text
ROBOT_OFFLINE  로봇 heartbeat가 끊겼습니다 (전원·네트워크·Agent 중단 가능)
ROBOT_ONLINE   로봇 heartbeat가 복구되었습니다
```

Gateway는 heartbeat 침묵만 볼 수 있으므로 전원 차단, 네트워크 단절, Robot Agent 중단을
서로 확정해서 구분하지 않는다. 원인은 TB1의 `journalctl`과 네트워크 상태를 함께 확인한다.

## 6. 갑작스러운 종료와 기록 해석

| 종료한 대상 | 동작과 웹 기록 |
| --- | --- |
| 브라우저 탭 또는 새로고침 | navigation 목표는 Gateway lease가 계속되므로 자동 취소되지 않는다. 반면 Phase 8 deadman 수동 명령은 TB1 로컬 authorization이 0.35초에 만료되어 정지한다. navigation은 종료 전 목표 취소 또는 비상정지를 사용한다. |
| TB1 전원·Agent·통신 경로 | 마지막 heartbeat가 3초를 넘으면 `ROBOT_OFFLINE`, 복구되면 `ROBOT_ONLINE`이 기록된다. 원인 자체는 메시지만으로 구분하지 못한다. |
| Zenoh 또는 Gateway | TB1에서 2초 lease가 만료돼 목표를 취소하고 정지한다. Gateway 재시작 뒤 비종료 작업은 `TASK_FAILED`와 `Fleet Gateway restarted; prior task will not resume`으로 닫힌다. |
| 관제 PC 전원 | 꺼진 프로세스는 그 순간 중앙 로그를 쓸 수 없다. TB1 로컬 로그에는 lease 만료가 남고, 관제 복구 뒤 남은 작업은 실패 처리되며 자동 재개되지 않는다. |

웹의 Audit Events는 작업과 상태 전이 기록이다. ROS 2와 systemd의 원시 로그는 다음처럼
별도로 확인한다.

```bash
journalctl --user -u fleet-gateway.service -n 100 --no-pager
ssh tb1 'journalctl --user -u tb1-navigation.service -n 100 --no-pager'
```

## 7. systemd 운영

자세한 설치는 [Zenoh 브리지 운영 문서](../../infra/zenoh/README.md)를 따른다.

WSL 최소 설치본이면 먼저 사용자 systemd 버스를 설치하고 linger를 활성화한다.

```bash
sudo apt update
sudo apt install -y dbus-user-session
sudo loginctl enable-linger "$USER"
```

```bash
systemctl --user --no-pager status \
  fleet-control-zenoh.service \
  fleet-gateway.service

journalctl --user -u fleet-gateway.service -n 100 --no-pager
```

프로세스 장애 복구를 검증할 때는 다음 세 가지를 모두 확인한다.

1. systemd의 `MainPID`가 새 값으로 바뀐다.
2. `/api/robots/tb1`이 일시적인 offline 뒤 `online=true`로 복귀한다.
3. `/cmd_vel`이 계속 0인지 확인한다.

`RestartSec` 뒤에도 ROS 2 discovery와 Zenoh 경로 재등록 시간이 필요하므로 5초 같은
고정 대기만으로 실패를 단정하지 않는다. 최대 대기 시간을 정하고 기능 상태를
반복 확인한다.

## 자주 발생하는 문제

### 상태 토픽은 보이지만 서비스가 시간 초과됨

다음을 확인한다.

```bash
echo "$ROS_DISTRO"
echo "$ROS_DOMAIN_ID"
echo "$RMW_IMPLEMENTATION"
```

모든 ROS 노드는 Humble, domain 42, `rmw_cyclonedds_cpp`를 사용해야 한다. 해결 과정은
[Zenoh 서비스 시간 초과 사례](../case-studies/zenoh-service-timeout-rmw-mismatch.md)에
정리돼 있다.

### Zenoh 로그에서 timestamp가 500ms를 초과함

WSL 시계를 Windows 호스트에 다시 맞춘 후 관제 브리지를 재시작한다.

```bash
sudo hwclock -s
```

TB1은 NTP 동기화 상태를 확인한다.

```bash
timedatectl status
```

### 화면은 열리지만 CSS가 적용되지 않음

```bash
curl -I http://127.0.0.1:8000/static/styles.css
```

HTTP 200과 `text/css`가 나와야 한다. colcon의 `--symlink-install`에서도 정적 파일을
제공하도록 Gateway는 허용된 경로를 `FileResponse`로 반환한다.
