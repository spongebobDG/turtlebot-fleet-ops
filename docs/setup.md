# Phase 0 환경 조사 기록

조사일: 2026-07-15

상태: 진행 중

이 문서는 설치나 설정을 변경하기 전에 확인한 초기 환경을 기록한다. 비밀번호, Wi-Fi 정보, 정확한 IP 주소와 같은 민감한 값은 저장소에 기록하지 않는다.

## 로봇 환경

| 항목 | tb1 | tb2 |
| --- | --- | --- |
| hostname | `tb1` | `tb2` |
| 보드 | Raspberry Pi 4 Model B Rev 1.2 | Raspberry Pi 4 Model B Rev 1.2 |
| 아키텍처 | `aarch64` | `aarch64` |
| 메모리 | 3.7 GiB | 3.7 GiB |
| 스왑 | 없음 | 없음 |
| 루트 파일시스템 | 29 GiB, 11% 사용 | 15 GiB, 21% 사용 |
| Ubuntu | 22.04.5 LTS | 22.04.5 LTS |
| 커널 | `5.15.0-1061-raspi` | `5.15.0-1061-raspi` |
| 주 네트워크 | `wlan0`, 연결 확인 | `wlan0`, 연결 확인 |
| 시간대 | Asia/Seoul | Asia/Seoul |
| 시간 동기화 | NTP 활성, 동기화됨 | NTP 활성, 동기화됨 |
| ROS_DISTRO | 미설정 | 미설정 |
| ROS_DOMAIN_ID | 미설정, 기본값 0 후보 | 미설정, 기본값 0 후보 |
| 표준 ROS 2 설치 | 확인되지 않음 | 확인되지 않음 |
| TurtleBot 모델 | 미확인 | 미확인 |
| LiDAR 모델 | 미확인 | 미확인 |

두 로봇 모두 `ros2` 명령과 `/opt/ros` 표준 설치 경로가 확인되지 않았다. 따라서 현재 증거로는 ROS 2가 표준 APT 방식으로 설치되어 있지 않은 것으로 판단한다. 다른 경로의 수동 설치 여부는 아직 확인하지 않았다.

## USB 장치

| 장치 | tb1 | tb2 | 판단 |
| --- | --- | --- | --- |
| OpenCR | `/dev/ttyACM0` | `/dev/ttyACM0` | ROBOTIS OpenCR 장치 정보로 확인 |
| LiDAR 직렬 후보 | `/dev/ttyUSB0` | `/dev/ttyUSB0` | CP2102 USB-UART 변환기로 확인, LiDAR 모델은 확정 불가 |

OpenCR은 USB VID/PID `0483:5740`과 `ROBOTIS OpenCR Virtual ComPort` 정보로 확인했다. `/dev/ttyUSB0`은 VID/PID `10c4:ea60`의 Silicon Labs CP2102 장치이지만, 변환 칩 정보만으로 센서 모델을 추측하지 않는다.

## 관제 PC 환경

| 항목 | 조사 결과 |
| --- | --- |
| 호스트 운영체제 표시 | Windows 10 Pro, 64비트 |
| OS 빌드 | 26200 |
| CPU | Intel Core i9-13900, 24코어/32논리 프로세서 |
| 메모리 | 63.75 GiB |
| C 드라이브 | 952.94 GiB 중 767.94 GiB 여유 |
| Windows Python | 명령을 찾지 못함 |
| Windows Docker | 명령을 찾지 못함 |
| Windows ROS 2 | 명령을 찾지 못함 |
| WSL | `Ubuntu`, `Ubuntu-22.04`, 모두 WSL2 |
| 로봇 이름 해석 | tb1, tb2 모두 확인 |
| ICMP 통신 | tb1, tb2 모두 4회 응답 |
| SSH 포트 | tb1, tb2 모두 TCP 22 연결 성공 |

정확한 사설 IP는 저장소에 기록하지 않는다. Windows에서 로봇 hostname이 IPv4 및 링크 로컬 IPv6 주소로 해석되고, ping 지연은 1~4 ms 범위로 관찰됐다.

## WSL 1차 확인

| 배포판 | 확인된 Python | 기타 결과 |
| --- | --- | --- |
| `Ubuntu` | Python 3.14.4 | WSL 커널 `6.18.33.2`; OS 및 ROS 출력 불완전 |
| `Ubuntu-22.04` | Python 3.10.12 | ROS 2 Humble Desktop 및 Docker Desktop WSL 통합 완료 |

관제 개발환경은 `Ubuntu-22.04`로 선택했다. ROS 2 Humble의 C++/Python 노드 통신과 Docker Linux 컨테이너 실행을 검증했다. Python 3.14가 설치된 일반 `Ubuntu` 배포판은 이 프로젝트에 사용하지 않는다.

## 확인된 차이와 주의사항

- tb1과 tb2의 하드웨어, Ubuntu, 커널, OpenCR 및 직렬 장치 구성은 현재 조사 범위에서 동일하다.
- 저장장치는 tb1 약 32 GB, tb2 약 16 GB로 다르다. 이후 로그 보존량과 순환 정책에서 이 차이를 고려한다.
- 두 로봇 모두 스왑이 없다. 현재는 변경하지 않고, 실제 워크로드와 메모리 사용량을 측정한 뒤 판단한다.
- Windows에서 네트워크 연결은 확인됐지만 실제 SSH 인증 성공 여부는 별도로 확인해야 한다.
- ROS 2 DDS 통신을 시작하기 전에 WSL 내부에서 로봇까지의 이름 해석, ping 및 DDS 검색 가능 여부를 검증해야 한다.

## 남은 Phase 0 확인 항목

- [ ] 일반 `Ubuntu` 배포판의 정확한 OS 버전 확인 또는 제거 여부 결정
- [x] `Ubuntu-22.04`의 ROS 2 및 Docker 설치 상태 확인
- [x] 관제용 WSL 배포판을 `Ubuntu-22.04`로 선택
- [ ] WSL 내부에서 tb1, tb2 네트워크 연결 확인
- [ ] tb1, tb2 실제 SSH 인증 확인
- [ ] TurtleBot 모델을 제품 라벨 또는 사진으로 확인
- [ ] LiDAR 모델을 제품 라벨 또는 사진으로 확인
- [ ] 설치 전 백업 범위 결정
