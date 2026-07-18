# 학습 일지: 현재 PC를 TB1 관제 환경으로 준비

날짜: 2026-07-18

단계: Phase 5·6 실차 연결 전 무로봇 준비

진행 상태: 관제 PC 준비와 전체 무로봇 검증 완료, TB1 실차 acceptance 대기

## 오늘의 목표

TB1이 없는 동안 Windows PC에 필요한 환경을 모두 구성해, 나중에 전원과 LAN을 연결하면
다른 개발 환경을 다시 만들지 않고 실차 사전점검부터 시작할 수 있게 한다.

## 구성한 환경

- Windows 10 build 19045, BIOS SVM 활성
- WSL 2.7.10.0, Ubuntu-22.04, kernel 6.18.33.2, systemd
- Linux 사용자 `fleetops`와 passwordless sudo
- ROS 2 Humble Desktop, Nav2, SLAM Toolbox, CycloneDDS
- 저장소의 robot·control workspace와 ROS 의존성
- Zenoh ROS2DDS bridge 1.9.0
- `fleet-control-zenoh.service`, `fleet-gateway.service`
- Windows Node.js 24.18.0
- Windows 로그인 시 관제 스택 자동 시작

실제 TB1 주소는 로컬 `output/control-pc-ready.txt`와 WSL의 권한 제한 설정 파일에만
저장하고 Git에는 넣지 않는다.

## 자동화한 명령

처음 Windows 기능을 켤 때는 관리자 PowerShell에서 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\control-pc\enable_wsl.ps1
```

재부팅 뒤 종합 설치·빌드·검증은 일반 PowerShell에서 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\control-pc\bootstrap_wsl.ps1 `
  -RobotAddress <TB1_LAN_NAME_OR_ADDRESS>
```

로그인 자동 시작 또는 수동 복구:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\control-pc\start_control_stack.ps1
```

TB1이 없을 때와 연결된 뒤의 사전점검:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\control-pc\test_tb1_connection.ps1
powershell -ExecutionPolicy Bypass -File scripts\control-pc\test_tb1_connection.ps1 `
  -RequireRobot
```

## 실제 검증 결과

최종 종합 부트스트랩은 약 3분 동안 실행됐고 다음 결과로 끝났다.

```text
Summary: 183 tests, 0 errors, 0 failures, 0 skipped
SYSTEMD_UNIT_VALIDATION_OK units=6
ROBOTLESS_OPERATIONS_SMOKE_OK
Robotless TB1 navigation smoke test passed
Robotless Zenoh navigation action smoke test passed
WEEKEND_WORKSPACE_VERIFY_OK ROS_DOMAIN_ID=142
CONTROL_PC_PREFLIGHT_OK
CONTROL_PC_RUNTIME_OK
CONTROL_PC_READY
```

Nav2 smoke에서 실제 Humble 노드를 실행해 다음을 확인했다.

- HTTP 초기 위치, Goal 성공, 명시적 취소와 e-stop 후 자동 재개 없음
- `/cmd_vel` publisher는 `safety_watchdog` 하나
- controller 출력은 velocity smoother와 arbiter·watchdog 경로를 통과
- 최대 선속도 `0.05 m/s`, 최대 각속도 `0.3 rad/s`, 마지막 명령 0

Zenoh smoke는 robot domain 160과 control domain 161을 분리하고 bridge TCP 경로만으로
목표·feedback·result·cancel·lease·status를 왕복했다.

TB1 미연결 사전점검에서는 관제 LAN, keepalive, Gateway, Ubuntu, ROS overlay, 명령 도구,
CycloneDDS와 두 systemd 서비스를 모두 PASS로 판정했다. SSH와 Zenoh 로봇 포트는 의도한
WARN이었다.

## 발생한 문제와 해결

### 1. Windows 복사본의 CRLF가 Bash 실행을 깨뜨림

`.gitattributes`로 Linux 실행 파일을 LF로 고정하고 WSL 복사 단계에서 디렉터리·파일·셸
스크립트 권한을 정규화했다.

### 2. 깨끗한 Ubuntu에서 `python3-requests`가 빠짐

Gateway 테스트가 사용하는 의존성을 `package.xml`의 `test_depend`로 선언해 rosdep이
새 환경에서도 설치하게 했다.

### 3. Ubuntu 기본 Node.js 12가 최신 웹 문법을 해석하지 못함

운영 경로에는 Node가 필요하지 않다. Windows Node.js 24를 웹 구문 검사의 권위 있는
경로로 사용하고, WSL 검증은 지원 버전일 때만 선택적으로 실행한다.

### 4. systemd 기본 target 순환 의존성

`WantedBy=default.target`인 사용자 unit에서 `After=default.target`를 제거하고 unit 검증
스크립트에 회귀 검사를 추가했다.

### 5. 운영 Gateway와 무로봇 smoke가 같은 8000 포트를 사용

종합 검증 전에 운영 서비스를 정지하고 격리 smoke가 끝난 뒤 다시 enable·start하도록
순서를 고정했다. WSL 부팅의 enabled unit와 stop이 경합하는 한 차례 실패도 확인해,
운영 smoke는 18081, Nav2 smoke는 18082를 기본으로 사용하도록 포트까지 분리했다.

### 6. systemd 서비스가 active인데 WSL이 종료됨

WSL은 마지막 Windows-side `wsl.exe` 클라이언트가 끝나면 사용자 systemd 서비스가 있어도
배포판을 멈출 수 있었다. 로그인 스크립트가 숨김 `wsl.exe sleep infinity` 프로세스를
유지하게 하고, 30초 이상 뒤에도 Windows `localhost:8000` health가 응답하는지 확인했다.

### 7. 오프라인 포트 검사 지연

Windows `Test-NetConnection` 대신 2초 제한의 `TcpClient` 연결 검사를 사용해 TB1이 없을
때도 사전점검이 빠르게 끝나게 했다.

## 배운 점

1. 설치 완료, 서비스 active, 외부에서 사용 가능은 서로 다른 검증 항목이다.
2. 새 PC에서는 CI 통과만 믿지 말고 깨끗한 rosdep과 실제 로컬 graph를 실행해야 누락된
   의존성과 줄바꿈·권한 문제를 찾을 수 있다.
3. WSL의 systemd는 Linux 서비스 수명주기를 관리하지만 Windows가 배포판 VM을 유지한다는
   뜻은 아니다.
4. 로봇 없는 smoke는 ROS graph와 안전 계약을 강하게 검증하지만 실제 센서 정합, 모터,
   LAN 단절 시간과 Raspberry Pi 자원 측정을 대신하지 않는다.

## 남은 실차 범위와 시간

환경 재구성은 끝났다. TB1 연결 뒤 남은 예상은 `3시간 5분~4시간 35분`이고, 재시험 여유
40분을 포함해 `5시간 15분` 시험 창을 권장한다.

- TB1 SSH·Zenoh 필수 사전점검과 배포
- 지도·pose graph 저장, AMCL READY와 LiDAR 정합
- 저속 목표 도달·취소·WARN·중복 거부
- e-stop, lease 단절과 네 프로세스 장애 주입
- `/cmd_vel` 단일 publisher와 실제 정지시간
- 10분 CPU·메모리 측정과 증거 문서화

이 항목이 실제 로그로 채워질 때만 Phase 5·6과 TB1 MVP를 완료로 바꾼다.
