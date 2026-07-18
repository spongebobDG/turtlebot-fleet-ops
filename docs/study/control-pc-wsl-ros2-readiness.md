# 관제 PC WSL2·ROS 2 지속 실행과 검증 계층

## 왜 이 주제를 알아야 하는가

TB1이 안전하게 동작하려면 로봇 코드만 맞아서는 부족하다. 관제 PC가 재부팅 뒤 WSL을
시작하고, ROS 2와 Zenoh·Gateway를 같은 설정으로 올리며, 로봇이 없을 때와 있을 때의
실패를 구분해야 한다. 이 문서는 “설치됐다”와 “실차 시험에 사용할 수 있다” 사이의 차이를
설명한다.

## 핵심 개념

### 1. Windows, WSL VM, Linux systemd는 서로 다른 수명주기다

systemd의 `active`는 현재 Linux 사용자 manager 안에서 프로세스가 실행 중이라는 뜻이다.
Windows가 WSL 배포판 자체를 계속 유지한다는 보장은 아니다. 현재 PC에서는 마지막
Windows-side `wsl.exe`가 끝난 뒤 Ubuntu가 멈추고 Gateway도 사라지는 현상을 직접
확인했다.

이 프로젝트는 Windows 로그인 스크립트가 다음 두 역할을 함께 수행한다.

1. 숨김 `wsl.exe` keepalive 프로세스로 배포판을 유지한다.
2. Linux systemd 사용자 서비스로 Zenoh와 Gateway를 시작·복구한다.

둘을 분리하면 Windows는 VM 수명주기를, systemd는 Linux 프로세스 수명주기를 담당한다.

### 2. ROS 2 환경은 distro, domain, RMW를 함께 고정해야 한다

- distro: ROS 2 Humble
- production domain: 42
- isolated test domain: 142, Zenoh smoke는 160·161
- RMW: `rmw_cyclonedds_cpp`

같은 토픽 이름이어도 domain이 다르면 DDS 발견이 분리된다. 반대로 자동 테스트를 실차와
같은 domain 42에서 실행하면 fixture 명령이 로봇 graph와 연결될 위험이 있다. RMW를
명시하지 않으면 Fast DDS와 CycloneDDS가 섞여 서비스·action 발견이 불안정해질 수 있다.

### 3. 준비 상태는 계층별로 증명한다

| 계층 | 확인하는 것 | 이 프로젝트의 증거 |
| --- | --- | --- |
| 정적 검사 | 구문, 줄바꿈, unit 계약 | PowerShell parser, Node check, ShellCheck, unit validator |
| 패키지 | 의존성과 API 정책 | rosdep, 183개 단위·통합 테스트 |
| ROS graph | launch, lifecycle, Action, 토픽 경계 | robotless Nav2 smoke |
| bridge | DDS 격리 상태의 원격 action 전달 | Zenoh domain 160↔161 smoke |
| 운영 | 재시작, health, 로봇 부재 판정 | systemd, keepalive, preflight |
| 실차 | 센서·모터·물리 시간·자원 | TB1 연결 뒤 acceptance |

아래 계층이 통과해도 위 계층을 자동으로 증명하지 않는다. 예를 들어 unit test 성공은 WSL
로그인 뒤 Gateway가 계속 살아 있는지 알려주지 않고, robotless Nav2 성공은 바퀴 미끄러짐과
LiDAR 정합을 알려주지 않는다.

### 4. health와 connectivity는 다르다

`http://localhost:8000/api/health` 성공은 Gateway 프로세스와 Windows↔WSL 포트 전달이
살아 있다는 증거다. TB1 SSH 22번과 Zenoh 7447번 포트 성공은 로봇 LAN 경로가 열렸다는
증거다. SSH 인증, ROS 메시지 freshness, 실제 모터 정지는 그 다음 검사다.

따라서 로봇 부재 시 포트 실패는 WARN이고, `-RequireRobot` 모드에서는 FAIL이다. 같은
스크립트가 시험 단계에 따라 판정 기준을 강화한다.

### 5. 로컬 설정과 저장소 설정을 분리한다

ROS launch, systemd unit, bridge allowlist처럼 재현해야 하는 설정은 Git에 둔다. 실제 TB1
주소, 인증 정보와 runtime marker는 로컬 권한 제한 파일 또는 무시되는 `output/`에 둔다.
이 분리는 자동화의 재현성과 운영 비밀 보호를 동시에 만족시킨다.

## 흔히 하는 틀린 설명

| 틀린 설명 | 올바른 설명 |
| --- | --- |
| systemd unit가 active면 WSL도 계속 실행된다 | Linux 서비스 상태와 Windows의 WSL VM 유지 여부를 따로 확인한다 |
| CI가 통과했으니 새 PC 의존성도 완전하다 | 깨끗한 PC의 rosdep·줄바꿈·권한·실제 graph를 다시 검증한다 |
| Gateway health가 되면 로봇도 online이다 | health는 관제 프로세스, 로봇 online은 SSH·Zenoh·heartbeat의 별도 조건이다 |
| mock Nav2 성공은 실차 주행 성공이다 | launch·Action·안전 경계 증거이며 센서·모터·물리 시간은 실차로 측정한다 |
| private LAN 주소를 코드 기본값으로 넣어야 자동화된다 | 첫 실행 인수와 로컬 설정 파일로 주입하고 Git에는 일반 이름만 둔다 |

## 30초 설명

> 관제 PC는 WSL2 Ubuntu 22.04에 ROS 2 Humble, CycloneDDS, Zenoh와 Gateway를 설치했습니다.
> Windows 로그인 시 숨김 WSL keepalive와 systemd 서비스를 함께 시작해 재부팅 뒤에도
> 대시보드가 유지됩니다. 183개 테스트와 Nav2·Zenoh smoke로 소프트웨어 경계를 검증했고,
> TB1 연결 뒤에는 `-RequireRobot` preflight부터 센서·모터 acceptance를 진행합니다.

## 1분 설명

> 새 PC 준비를 설치, ROS graph, bridge, 운영 지속성의 네 계층으로 나눴습니다. Humble
> workspace의 183개 테스트 뒤 실제 Nav2 stack으로 Goal 성공·취소·e-stop·속도 제한과
> `/cmd_vel` 단일 publisher를 검사했습니다. 별도 DDS domain 160과 161 사이에서는 Zenoh
> bridge만으로 Action과 lease가 왕복하는지 확인했습니다. 운영 검증 중 systemd 서비스가
> active여도 마지막 Windows WSL client가 끝나면 배포판이 멈추는 문제를 발견해 로그인
> keepalive를 추가했습니다. 이제 로봇 없는 검사는 SSH·Zenoh만 WARN으로 남고, 연결 뒤
> `-RequireRobot`에서 이를 FAIL 조건으로 바꿉니다. 따라서 PC 환경은 준비됐지만 실차 센서,
> 물리 정지시간과 자원 사용량은 완료라고 과장하지 않습니다.

## 실무형 질문과 모범 답변

### 1. 왜 Gateway를 Windows 서비스로 직접 실행하지 않았는가?

ROS 2 Humble과 프로젝트 overlay가 Ubuntu 22.04를 기준으로 검증되어 있기 때문이다.
Windows는 로그인과 WSL VM 수명주기를 담당하고, ROS 프로세스는 같은 Linux 환경에서
systemd로 관리해 개발·CI·운영 차이를 줄였다.

### 2. keepalive가 죽으면 안전 문제가 생기는가?

관제 lease가 끊기며 TB1 로컬 navigation agent가 2초 만료로 목표를 취소하고, arbiter의
0.5초 authorization 만료와 watchdog이 실제 `/cmd_vel` 정지를 담당한다. keepalive는
가용성 장치이고 최종 안전 경계는 로봇 로컬에 남는다.

### 3. 왜 실제 로봇 domain과 테스트 domain을 분리하는가?

자동 테스트의 가짜 센서와 명령이 실제 로봇 graph에서 발견되는 것을 막기 위해서다.
domain 142는 일반 robotless 통합 테스트, 160·161은 Zenoh가 서로 다른 DDS graph 사이를
정말 전달하는지 확인하는 데 사용한다.

### 4. 로봇 연결 직후 무엇을 가장 먼저 확인하는가?

`test_tb1_connection.ps1 -RequireRobot`으로 관제 LAN, keepalive, Gateway, WSL ROS 환경,
TB1 SSH와 Zenoh 포트를 확인한다. 그 다음 `/cmd_vel` publisher가 watchdog 하나인지 확인하고
초기에는 바퀴를 띄우거나 전원 스위치에 접근 가능한 빈 공간에서 시험한다.

## 보지 않고 다시 해볼 체크리스트

- Windows·WSL·systemd의 수명주기를 구분해 설명할 수 있다.
- domain 42, 142, 160·161을 쓰는 이유를 설명할 수 있다.
- health, TCP connectivity, ROS heartbeat, 물리 정지의 차이를 말할 수 있다.
- `start_control_stack.ps1`과 `test_tb1_connection.ps1 -RequireRobot`의 역할을 설명할 수 있다.
- robotless smoke가 증명하는 것과 증명하지 못하는 것을 구분할 수 있다.

## 아직 실차로 확인할 것

- SSH 인증과 TB1 배포 revision
- 실제 Zenoh LAN 경로와 2초 lease 만료
- 지도·LiDAR 정합, AMCL READY와 Nav2 도달
- e-stop 후 2.5초 이내 물리 0속도와 자동 무재개
- navigation agent·Nav2·arbiter·watchdog 장애 복구
- 10분 CPU·메모리 측정
