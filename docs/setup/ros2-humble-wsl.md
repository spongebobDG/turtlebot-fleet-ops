# WSL2 ROS 2 Humble 설치 런북

대상: Windows 관제 PC의 `Ubuntu-22.04` WSL2

설치 방식: ROS 공식 APT 저장소와 Debian 패키지

설치 패키지: `ros-humble-desktop`, `ros-dev-tools`

상태: 완료

## 결정

- 관제 개발환경은 `Ubuntu-22.04` WSL2로 고정한다.
- ROS 2 배포판은 로봇과 동일하게 사용할 Humble로 고정한다.
- 관제 PC에는 RViz, 데모와 개발 도구가 필요한 `desktop` 변형을 설치한다.
- `Ubuntu` WSL 배포판은 이 프로젝트의 ROS 개발에 사용하지 않는다.
- Docker는 WSL 내부에 Docker Engine을 중복 설치하지 않고 Windows Docker Desktop의 WSL2 통합을 사용한다.

ROS 2 Humble의 공식 바이너리 대상은 Ubuntu Jammy 22.04의 amd64와 arm64이다.

## 현재 확인 결과

2026-07-15에 다음 결과를 확인했다.

| 항목 | 결과 |
| --- | --- |
| `ROS_DISTRO` | `humble` |
| `ros2` 실행 경로 | `/opt/ros/humble/bin/ros2` |
| `ros-humble-desktop` | 설치됨, `0.10.0-1jammy.20260612.213429` |
| `ros-dev-tools` | 초기 확인에서 누락, 추가 설치 성공 |
| `colcon`, `vcs` | 실행 검증 성공 |
| `rosdep` | 버전 `0.26.0`, 갱신 성공 |
| `ros2cli` | 확인 |
| `demo_nodes_cpp` | 확인 |
| `demo_nodes_py` | 확인 |
| `rviz2` | 확인 |
| `nav2_bringup` | 확인 |
| `slam_toolbox` | 확인 |
| `turtlebot3_bringup` | 확인 |

초기 확인에서 누락된 `ros-dev-tools`를 명시적으로 설치했고 `colcon`, `vcs`, `rosdep update`를 검증했다. 새 WSL 터미널의 환경 자동 적용과 C++ talker/Python listener 간 DDS 토픽 통신도 성공했다.

## 1. 작업 브랜치 이름 변경

설치까지 수행하도록 작업 범위가 넓어졌으므로 PowerShell에서 브랜치 이름을 변경한다.

```powershell
cd C:\project\turtlebot-fleet-ops
git branch -m chore/phase-0-dev-environment
git branch --show-current
```

정상 결과:

```text
chore/phase-0-dev-environment
```

## 2. Ubuntu-22.04 실행

PowerShell에서 실행한다.

```powershell
wsl.exe -d Ubuntu-22.04
```

이후 명령은 모두 WSL의 Bash에서 실행한다.

## 3. UTF-8 로케일과 필수 도구 설치

```bash
sudo apt update
sudo apt install -y locales software-properties-common curl
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8
sudo add-apt-repository -y universe
locale
```

`locale` 출력의 `LANG`과 `LC_ALL`에서 `en_US.UTF-8`을 확인한다.

## 4. ROS 2 공식 APT 저장소 추가

```bash
export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F 'tag_name' | awk -F'"' '{print $4}')
echo "ROS_APT_SOURCE_VERSION=${ROS_APT_SOURCE_VERSION}"
```

버전 값이 비어 있지 않을 때만 계속한다.

```bash
curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo ${UBUNTU_CODENAME:-${VERSION_CODENAME}})_all.deb"
test -s /tmp/ros2-apt-source.deb && echo "ros2 apt source download: OK"
sudo dpkg -i /tmp/ros2-apt-source.deb
```

정상 결과에 `ros2 apt source download: OK`와 `Setting up ros2-apt-source`가 포함된다.

## 5. 시스템 업데이트와 ROS 2 설치

Ubuntu 22.04에서는 ROS 2 설치 전에 `systemd`와 `udev` 관련 패키지를 포함한 시스템 업데이트가 중요하다.

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ros-humble-desktop ros-dev-tools
```

의존성 오류가 발생하면 패키지를 임의로 다운그레이드하지 않고 전체 오류를 기록한다.

## 6. rosdep 초기화

```bash
sudo rosdep init
rosdep update
```

이미 초기화됐다는 메시지가 나오면 오류 원문을 기록하고 `rosdep update` 결과를 확인한다.

## 7. 현재 셸에서 ROS 2 활성화

```bash
source /opt/ros/humble/setup.bash
echo "ROS_DISTRO=${ROS_DISTRO}"
command -v ros2
ros2 --help >/dev/null && echo "ros2 command: OK"
```

정상 결과:

```text
ROS_DISTRO=humble
/opt/ros/humble/bin/ros2
ros2 command: OK
```

## 8. 새 터미널 자동 활성화

동일한 설정 줄이 중복되지 않도록 확인한 뒤 `.bashrc`에 추가한다.

```bash
grep -qxF 'source /opt/ros/humble/setup.bash' ~/.bashrc || echo 'source /opt/ros/humble/setup.bash' >> ~/.bashrc
tail -n 5 ~/.bashrc
```

## 9. Talker/Listener 통신 검증

첫 번째 `Ubuntu-22.04` 터미널:

```bash
source /opt/ros/humble/setup.bash
ros2 run demo_nodes_cpp talker
```

두 번째 `Ubuntu-22.04` 터미널:

```bash
source /opt/ros/humble/setup.bash
ros2 run demo_nodes_py listener
```

정상이라면 talker에 `Publishing`, listener에 `I heard`가 반복 출력된다. 확인 후 각 터미널에서 `Ctrl+C`로 종료한다.

## 완료 기준

- [x] `ROS_DISTRO=humble`이 출력된다.
- [x] `ros2` 경로가 `/opt/ros/humble/bin/ros2`로 확인된다.
- [x] `ros-dev-tools` 메타패키지가 설치된다.
- [x] `colcon`, `vcs`, `rosdep update`가 정상 동작한다.
- [x] 새 WSL 터미널에서도 `ros2` 명령을 사용할 수 있다.
- [x] C++ talker가 메시지를 발행한다.
- [x] Python listener가 메시지를 수신한다.
- [x] 설치 또는 검증 중 발생한 오류를 학습 일지에 기록했다.

## 공식 참고 자료

- [ROS 2 Humble Ubuntu deb 설치 소스](https://github.com/ros2/ros2_documentation/blob/humble/source/Installation/Ubuntu-Install-Debs.rst)
- [ROS 2 APT 저장소 설정 소스](https://github.com/ros2/ros2_documentation/blob/humble/source/Installation/_Apt-Repositories.rst)
- [ROS 2 환경 설정](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Configuring-ROS2-Environment.html)
- [Docker Desktop WSL2 백엔드](https://docs.docker.com/desktop/features/wsl/)
