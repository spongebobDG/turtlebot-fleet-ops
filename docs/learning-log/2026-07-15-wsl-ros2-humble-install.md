# 학습 일지: WSL2 ROS 2 Humble 설치

날짜: 2026-07-15

단계: Phase 0 - 관제 개발환경 구성

진행 상태: 완료

## 오늘의 목표

`Ubuntu-22.04` WSL2에 ROS 2 Humble Desktop과 개발 도구를 설치하고 C++ talker와 Python listener의 통신을 검증한다.

## 왜 이 작업을 했는가

관제 PC가 로봇의 ROS 2 노드, 토픽, 서비스와 액션을 확인하고 이후 Fleet Gateway를 개발하려면 로봇과 호환되는 ROS 2 개발환경이 필요하다.

## 선택한 방향

- WSL 배포판: `Ubuntu-22.04`
- ROS 2 배포판: Humble
- 설치 변형: Desktop
- 설치 방법: ROS 공식 APT 저장소
- Python 기준: Ubuntu 22.04 기본 Python 3.10
- Docker 방향: ROS 설치 검증 후 Windows Docker Desktop과 WSL2 통합

## 진행할 활동

1. 작업 브랜치 이름을 `chore/phase-0-dev-environment`로 변경한다.
2. UTF-8 로케일과 Ubuntu Universe 저장소를 설정한다.
3. `ros2-apt-source` 패키지로 공식 ROS 저장소를 추가한다.
4. Ubuntu 패키지를 업데이트한다.
5. `ros-humble-desktop`과 `ros-dev-tools`를 설치한다.
6. `rosdep`을 초기화한다.
7. ROS 환경을 활성화하고 새 셸에서도 자동 적용되게 한다.
8. talker/listener 통신을 검증한다.

## 실제 결과

```text
ROS_DISTRO=humble
ros2=/opt/ros/humble/bin/ros2
ros-humble-desktop=install ok installed 0.10.0-1jammy.20260612.213429
ros-dev-tools=패키지 미설치
rosdep=0.26.0
```

확인된 ROS 2 패키지:

```text
ros2cli=OK
demo_nodes_cpp=OK
demo_nodes_py=OK
rviz2=OK
nav2_bringup=OK
slam_toolbox=OK
turtlebot3_bringup=OK
```

ROS 2 CLI, 데모 노드, 시각화, 내비게이션, SLAM과 TurtleBot3 bringup 패키지가 설치된 것을 확인했다. 설치된 Humble Desktop 패키지는 2026-06-12 Jammy 빌드다.

## 발생한 문제와 해결

### `ros-dev-tools` 메타패키지 미설치

`dpkg-query`에서 `ros-dev-tools`를 찾지 못했다. `rosdep`은 실행 가능하지만, 이것만으로 `colcon`, `vcs` 등 권장 개발 도구 구성이 모두 설치됐다고 판단하지 않는다.

해결 계획:

1. `ros-dev-tools`를 명시적으로 설치한다.
2. `colcon`, `vcs`와 `rosdep update`를 각각 실행해 검증한다.
3. talker/listener 통신까지 성공한 후 ROS 설치 단계를 완료로 변경한다.

### 보완 결과

`ros-dev-tools` 추가 설치, `colcon`, `vcs`, `rosdep update`, 새 터미널 환경 자동 적용과 talker/listener 통신이 모두 성공했다. 이 결과는 사용자가 직접 명령을 실행해 확인했다.

## 완료 체크리스트

- [x] 브랜치 이름 변경
- [x] ROS 2 Humble Desktop 설치 확인
- [x] 주요 ROS 2 패키지 설치 확인
- [x] `ros-dev-tools` 설치
- [x] `colcon`과 `vcs` 검증
- [x] `rosdep update` 검증
- [x] 환경 설정 자동 적용
- [x] C++ talker 실행
- [x] Python listener 수신

## 복습 문제와 정답

### 1. 왜 Python 3.14가 설치된 `Ubuntu` 대신 `Ubuntu-22.04`를 사용하는가?

정답: ROS 2 Humble 공식 Ubuntu 바이너리는 Jammy 22.04를 대상으로 하고, Jammy의 기본 Python 3.10 패키지와 함께 검증됐기 때문이다.

이유: 지원 대상이 아닌 최신 배포판과 Python을 사용하면 ROS 패키지 의존성이 맞지 않을 가능성이 커진다.

### 2. 왜 ROS 2를 소스에서 빌드하지 않고 APT로 설치하는가?

정답: 현재 목표는 ROS 2 자체 개발이 아니라 안정적인 로봇 관제 시스템 개발이므로 검증된 바이너리 패키지가 적합하다.

이유: APT 설치는 재현과 업데이트가 쉽고, 빌드 시간과 불필요한 문제 범위를 줄인다.

### 3. `source /opt/ros/humble/setup.bash`는 무엇을 하는가?

정답: 현재 셸이 ROS 2 실행 파일, 패키지와 라이브러리를 찾을 수 있도록 환경변수를 설정한다.

이유: ROS 2가 설치돼 있어도 설정 파일을 불러오지 않은 셸에서는 `ros2` 명령과 패키지를 찾지 못할 수 있다.

### 4. Talker/Listener 검증으로 무엇을 확인하는가?

정답: C++ 노드 실행, Python 노드 실행, DDS 노드 발견과 토픽 메시지 전달을 함께 확인한다.

이유: `ros2 --help`만으로는 실제 노드 간 통신이 동작하는지 확인할 수 없다.

### 5. ROS 2 설치 전에 `apt upgrade`를 수행하는 이유는 무엇인가?

정답: ROS 바이너리가 기대하는 최신 Ubuntu 의존성과 `systemd`, `udev` 관련 패키지 상태를 맞추기 위해서다.

이유: Ubuntu 22.04의 초기 패키지 상태에서 바로 ROS를 설치하면 중요한 시스템 패키지가 제거되거나 의존성 충돌이 발생할 수 있다고 공식 문서가 경고한다.

## 다음에 할 일

Windows에 Docker Desktop을 설치하고 `Ubuntu-22.04` WSL 통합을 활성화한 뒤 `hello-world` 컨테이너를 실행한다.

## 관련 커밋

설치와 검증 결과를 기록한 후 커밋한다.
