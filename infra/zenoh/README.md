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

WSL 관제 서비스:

```bash
systemctl --user daemon-reload
systemctl --user enable --now \
  fleet-control-zenoh.service \
  fleet-gateway.service
```

재부팅 뒤 로그인 전에도 TB1 사용자 서비스를 시작하려면 관리자 권한으로 한 번
`loginctl enable-linger dg`를 설정한다.

## 운영 확인

```bash
systemctl --user --no-pager status tb1-zenoh-bridge.service
systemctl --user --no-pager status fleet-control-zenoh.service
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/robots
```

장애 진단 순서는 다음과 같다.

1. 로봇의 Robot Agent가 상태를 발행하는지 확인한다.
2. 양쪽 Zenoh 브리지 프로세스와 TCP 7447 연결을 확인한다.
3. 양쪽 시스템 시각 차이가 500ms를 넘지 않는지 확인한다.
4. 모든 ROS 노드와 브리지의 `ROS_DISTRO`, `ROS_DOMAIN_ID`, RMW를 확인한다.
5. Gateway REST 상태와 systemd journal을 확인한다.

```bash
journalctl --user -u tb1-zenoh-bridge.service -n 100 --no-pager
journalctl --user -u fleet-control-zenoh.service -n 100 --no-pager
```
