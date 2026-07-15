# 학습 일지: Phase 0 환경 조사

날짜: 2026-07-15

단계: Phase 0 - 환경 조사와 백업 준비

진행 상태: 1차 조사 완료, 추가 확인 필요

## 오늘의 목표

tb1, tb2와 관제 PC의 실제 환경을 변경 없이 조사하고, ROS 2 개발을 시작하기 전에 확인해야 할 차이와 미확인 항목을 찾는다.

## 진행한 활동

- tb1과 tb2의 Raspberry Pi 모델, CPU 아키텍처, 메모리, 저장장치, Ubuntu 및 커널 버전을 확인했다.
- 두 로봇의 hostname, Wi-Fi 연결, 라우팅, 시간대와 NTP 동기화 상태를 확인했다.
- `ROS_DISTRO`, `ROS_DOMAIN_ID`, `ros2` 명령 및 `/opt/ros` 경로로 ROS 2의 표준 설치 여부를 조사했다.
- `lsusb`, 직렬 장치 파일과 `udevadm` 정보로 OpenCR 및 LiDAR 연결 후보를 조사했다.
- 관제 PC의 운영체제, CPU, 메모리, 디스크, Python, Docker, ROS 2 및 WSL 상태를 확인했다.
- Windows에서 tb1과 tb2의 hostname 해석, ping 응답과 SSH 포트 연결을 확인했다.
- WSL의 `Ubuntu` 및 `Ubuntu-22.04` 배포판에서 Python 버전과 일부 환경 정보를 확인했다.

## 배운 점 / 메모

- 환경변수 `ROS_DISTRO`가 비어 있는 것만으로 ROS 2 미설치를 단정할 수 없다. 이번에는 `ros2` 명령과 `/opt/ros` 표준 경로도 함께 확인해 판단 근거를 보강했다.
- `/dev/ttyACM0`이라는 이름만 보지 않고 USB 제조사와 모델 정보를 확인해야 장치 역할을 더 신뢰성 있게 판단할 수 있다.
- CP2102는 LiDAR 자체의 모델명이 아니라 USB-UART 변환 칩이므로, LiDAR 제품 라벨을 별도로 확인해야 한다.
- Windows에서 TCP 22 포트가 열린 것은 SSH 서버까지 접근 가능하다는 뜻이지만, 사용자 인증 성공까지 증명하지는 않는다.
- 동일한 Raspberry Pi와 운영체제를 사용하더라도 저장장치 용량처럼 운영 정책에 영향을 주는 차이가 존재할 수 있다.
- 로봇의 정확한 IP와 Wi-Fi 정보는 운영에는 필요하지만 공개 저장소 문서에는 남기지 않는다.

## 발생한 문제와 해결

### PowerShell ping 옵션 불일치

처음 사용한 `Test-Connection -TargetName`은 현재 Windows PowerShell에서 지원되지 않아 오류가 발생했다. `-ComputerName` 옵션으로 수정한 뒤 tb1과 tb2에서 각각 4회 응답을 확인했다.

### WSL 조사 출력 불완전

두 WSL 배포판 모두 Python 버전은 확인했지만 `OS=` 값이 비어 있었고 ROS 이후 출력이 완전하지 않았다. 출력되지 않은 값을 추측하지 않고 미확인 상태로 남겼다. 다음 조사에서는 명령을 더 짧게 나누어 실행한다.

### LiDAR 모델 식별 제한

직렬 장치에서 Silicon Labs CP2102를 확인했지만 실제 LiDAR 모델은 알아낼 수 없었다. 제품 라벨이나 사진으로 확인하기 전까지 모델명을 확정하지 않는다.

## 현재 결론

- tb1과 tb2는 Raspberry Pi 4, Ubuntu 22.04.5 LTS 기반이며 네트워크와 시간 동기화가 정상이다.
- 두 로봇에서 OpenCR은 인식되지만 표준 ROS 2 설치는 확인되지 않았다.
- 관제 PC의 하드웨어 자원은 충분하며 Windows에서 두 로봇까지의 기본 네트워크 연결이 정상이다.
- ROS 2 Humble 관제 환경 후보는 `Ubuntu-22.04` WSL2이지만, 설치 상태와 로봇 통신을 확인한 뒤 최종 선택한다.

## 다음에 할 일

1. WSL 명령을 짧게 나누어 두 배포판의 OS, ROS 2와 Docker 상태를 다시 확인한다.
2. 관제용 WSL 배포판을 하나로 결정한다.
3. WSL 내부에서 tb1과 tb2의 ping 및 SSH를 확인한다.
4. TurtleBot과 LiDAR 모델을 제품 라벨 또는 사진으로 확인한다.
5. 설치 전에 백업할 설정과 장치 정보를 결정한다.
