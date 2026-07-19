# Zenoh ROS 2 DDS 브리지 운영

## 도입 이유

관제 PC는 Windows의 WSL2 안에서 실행되고 로봇은 물리 LAN에 있다. 이 환경에서는
Windows·Hyper-V·WSL 네트워크 경계를 통과하는 DDS UDP discovery와 동적 포트를
안정적으로 운영하기 어렵다. 이 프로젝트는 각 ROS 2 호스트에
`zenoh-bridge-ros2dds`를 하나씩 두고, 관제 측 브리지가 로봇의 TCP 7447 포트로
연결하는 구조를 사용한다.

```text
TB1 ROS 2 <-- local DDS --> TB1 Zenoh bridge
                                  ^
                                  | TCP 7447
                                  v
WSL ROS 2 <-- loopback DDS --> control Zenoh bridge
          |
          `--> fleet_gateway --> HTTP/WebSocket --> browser
```

로봇과 관제 호스트 사이의 DDS 직접 통신을 막아 중복·루프를 방지한다. WSL에서는
`cyclonedds-localhost.xml`로 DDS를 loopback에만 묶고, 두 브리지는 Zenoh TCP로만
연결한다.

## 고정 버전과 무결성

현재 검증 버전은 `1.9.0`이다.

| 아키텍처 | SHA-256 |
| --- | --- |
| x86_64 | `91aa0d569fffd57e7ebb1a591b97789891c543b1ff0a1658413ce6cbbba34a9e` |
| aarch64 | `e3eb1fd4459e4b877653419b1c25eaf92418d70fe53ee767eca005f1a19443dc` |

설치 스크립트는 아키텍처를 판별하고 GitHub Release 파일의 해시를 검증한 뒤
`~/.local/opt`에 설치한다.

```bash
bash infra/zenoh/install-standalone.sh
~/.local/bin/zenoh-bridge-ros2dds --version
```

새 버전으로 올릴 때는 두 아키텍처 파일의 해시를 다시 검증하고 스크립트의 버전과
해시를 함께 변경한다.

## 로봇 없는 action 전달 검증

workspace를 Humble로 빌드한 뒤 다음 smoke를 실행한다.

```bash
bash infra/navigation/run-robotless-zenoh-action-smoke.sh
```

이 smoke는 서로 다른 robot/control DDS domain 사이에서 `NavigateRobot` action·lease·상태뿐
아니라 Phase 8의 manual, operating-profile, map-save 서비스와 `MappingStatus`도 왕복시킨다.

script는 robot domain 160과 control domain 161을 분리하고 두 Zenoh bridge를 loopback
TCP로만 연결한다. `NavigateRobot`의 goal·feedback·성공 result·cancel과
`NavigationLease`·`NavigationStatus`가 모두 bridge를 통과해야 성공한다. 이 검증은
실제 LAN 단절 시간과 모터 정지시간을 측정하지 않으므로 실차 lease 장애 주입을
대체하지 않는다.

## 로봇 측 실행

TB1의 ROS 노드와 브리지는 같은 `ROS_DOMAIN_ID`를 사용한다. 서비스까지 안정적으로
브리징하려면 ROS 노드도 `rmw_cyclonedds_cpp`로 실행한다. 브리지 프로세스에는
`ROS_DISTRO=humble`을 반드시 전달한다. 이 값이 없으면 다른 배포판의 GID 형식을
가정해 서비스와 ROS graph가 비정상 동작할 수 있다.

```bash
export ROS_DISTRO=humble
export ROS_DOMAIN_ID=42
bash infra/zenoh/start-robot-bridge.sh
```

## 관제 측 실행

```bash
export ROBOT_ADDRESS=tb1
export ROS_DISTRO=humble
export ROS_DOMAIN_ID=42
bash infra/zenoh/start-control-bridge.sh
```

다른 터미널에서 Gateway를 실행한다.

```bash
bash infra/zenoh/start-control-gateway.sh
```

## systemd 사용자 서비스

`infra/systemd/user`에는 TB1 런타임과 WSL 관제 스택의 사용자 서비스 단위가 있다.
로컬 환경 파일은 저장소 밖에 둔다.

WSL 최소 설치본에는 사용자 systemd 버스가 없을 수 있다. 다음 패키지를 설치하고
사용자 서비스를 로그인 전에도 유지하도록 linger를 활성화한다.

```bash
sudo apt update
sudo apt install -y dbus-user-session
sudo loginctl enable-linger "$USER"
```

설치 직후 사용자 버스가 아직 없다면 WSL을 한 번 종료했다 다시 시작한다.

```powershell
wsl.exe --shutdown
```

```bash
mkdir -p ~/.config/systemd/user ~/.config/turtlebot-fleet-ops
cp infra/systemd/user/*.service ~/.config/systemd/user/
cp infra/systemd/control.env.example \
  ~/.config/turtlebot-fleet-ops/control.env
```

관제 환경에서는 `control.env`의 `ROBOT_ADDRESS`를 실제 로컬 이름 또는 주소로
바꾼다. 정확한 사설 주소는 Git에 커밋하지 않는다.

TB1 서비스:

```bash
systemctl --user daemon-reload
systemctl --user enable --now \
  tb1-bringup.service \
  tb1-safety-watchdog.service \
  tb1-robot-agent.service \
  tb1-zenoh-bridge.service
```

Phase 5에서는 매핑과 주행 프로필 중 하나만 추가로 실행한다. 두 unit은 상호
`Conflicts=`이므로 동시에 active가 되면 안 된다.

```bash
systemctl --user enable --now tb1-navigation.service
systemctl --user is-active tb1-mapping.service
```

WSL 관제 서비스:

```bash
systemctl --user daemon-reload
systemctl --user enable --now \
  fleet-control-zenoh.service \
  fleet-gateway.service
```

재부팅 뒤 로그인 전에도 사용자 서비스를 시작하려면 각 장비에서 관리자 권한으로
한 번 `loginctl enable-linger <사용자>`를 설정한다.

## 운영 확인

```bash
systemctl --user --no-pager status tb1-zenoh-bridge.service
systemctl --user --no-pager status fleet-control-zenoh.service
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/robots
curl http://127.0.0.1:8000/api/robots/tb1/map
```

`active`만 보고 복구 완료로 판단하지 않는다. ROS 2 discovery와 Zenoh endpoint
재등록에는 시간이 더 필요할 수 있으므로 새 PID와 REST의 `online=true`를 함께
확인한다. 고정된 짧은 `sleep`보다 제한 시간 안에서 조건을 반복 확인하는 방식이
안정적이다.

장애 진단 순서는 다음과 같다.

1. 로봇의 Robot Agent가 상태를 발행하는지 확인한다.
2. 양쪽 Zenoh 브리지 프로세스와 TCP 7447 연결을 확인한다.
3. 양쪽 시스템 시각 차이가 500ms를 넘지 않는지 확인한다.
4. 모든 ROS 노드와 브리지의 `ROS_DISTRO`, `ROS_DOMAIN_ID`, RMW를 확인한다.
5. Gateway REST 상태, navigation/safety freshness와 systemd journal을 확인한다.
6. 활성 목표가 있었다면 `/fleet/navigation_lease`와
   `/fleet/navigation_status`의 `LEASE_EXPIRED`를 확인한다.

```bash
journalctl --user -u tb1-zenoh-bridge.service -n 100 --no-pager
journalctl --user -u fleet-control-zenoh.service -n 100 --no-pager
```
