# 새 PC 주말 무로봇 개발 환경

대상: 로봇 없이 Windows 새 PC에서 코딩·테스트·웹 관제를 이어가는 개발자

권장 기준 저장소: GitHub

보조 산출물 저장소: Google Drive

## 핵심 원칙

- GitHub에는 코드, 설정, Markdown 문서와 작은 테스트 fixture를 저장한다.
- Google Drive에는 실차 영상, RViz 캡처, rosbag, 큰 지도 백업처럼 Git에 적합하지 않은
  산출물만 저장한다.
- Google Drive 동기화 폴더 안에서 Git working tree를 직접 사용하지 않는다. 동기화 도구가
  파일 잠금, 실행 권한과 줄바꿈을 바꿔 Git 상태를 오염시킬 수 있다.
- 무로봇 mock 결과는 소프트웨어 검증이고 실차 acceptance를 대신하지 않는다.

## 1. Windows 준비

저장소를 `C:\projects\turtlebot-fleet-ops`에 둔 현재 PC는 2026-07-18에 이 절차를
완료했다. 다른 Windows PC를 같은 상태로 만들 때는 관리자 PowerShell에서 첫 단계를
실행한다.

```powershell
cd C:\projects\turtlebot-fleet-ops
powershell -ExecutionPolicy Bypass -File scripts\control-pc\enable_wsl.ps1
```

Windows를 재부팅한 뒤 일반 PowerShell에서 종합 부트스트랩을 실행한다.

```powershell
cd C:\projects\turtlebot-fleet-ops
powershell -ExecutionPolicy Bypass -File scripts\control-pc\bootstrap_wsl.ps1 `
  -RobotAddress <TB1_LAN_NAME_OR_ADDRESS>
```

이 명령은 Ubuntu 22.04 WSL2와 `fleetops` 사용자, systemd, ROS 2 Humble Desktop,
CycloneDDS, Nav2, SLAM Toolbox, Zenoh 1.9.0, 워크스페이스와 관제 서비스를 준비한다.
저장소는 Drive 밖의 일반 로컬 경로에 clone한다.

```powershell
New-Item -ItemType Directory -Force C:\project | Out-Null
cd C:\project
git clone https://github.com/spongebobDG/turtlebot-fleet-ops.git
cd turtlebot-fleet-ops
git fetch --prune
git switch codex/phase-5-tb1-navigation
git pull --ff-only
```

`-RobotAddress`를 생략하면 이전 `output/control-pc-ready.txt`의 로컬 값을 재사용하고,
처음 실행이면 `tb1`을 사용한다. 실제 주소는 Git에 commit하지 않는다.

### Windows만으로 웹 화면 확인

WSL과 ROS 2를 준비하기 전에도 seeded preview로 지도, WARN, 작업, fault와 감사 패널을
확인할 수 있다. 이 경로는 ROS graph나 모터를 만들지 않는다.

```powershell
cd C:\projects\turtlebot-fleet-ops
python -m pip install fastapi uvicorn websockets
python infra/navigation/robotless_web_preview.py
```

브라우저에서 `http://127.0.0.1:18080`을 연다. `WEB_PORT`로 포트를 바꿀 수 있고
`FLEET_OPERATIONS_DB`를 지정하지 않으면 임시 디렉터리의 preview DB를 매 실행 초기화한다.
명시한 DB는 기본적으로 보존하며 의도적으로 초기화할 때만 `PREVIEW_RESET=1`을 함께 준다.
화면 확인 뒤 `Ctrl+C`로 종료한다. 이 preview의 online 상태는 ROS heartbeat 대신 한 시간
유효한 seeded snapshot이므로 통신 지연이나 freshness acceptance 증거로 쓰지 않는다.

## 2. WSL 자동 설치와 전체 검증

일반적인 Ubuntu 환경에서는 WSL Bash에서 다음 수동 경로도 사용할 수 있다.

```bash
cd /mnt/c/project/turtlebot-fleet-ops
bash scripts/weekend/bootstrap_ubuntu22.sh
bash scripts/weekend/verify_workspace.sh
```

첫 스크립트는 Ubuntu 22.04를 확인하고 ROS 2 Humble, 개발 도구와 workspace 의존성을
설치한다. 두 번째 스크립트는 현재 ROS 2 패키지를 빌드하고 전체 테스트, Linux 줄바꿈,
systemd unit, 운영 smoke, 실제 Nav2 stack smoke와 서로 다른 DDS domain 사이의 Zenoh
action smoke를 수행한다. Windows 종합 부트스트랩은 이 경로를 호출한 뒤 관제 서비스를
설치·활성화한다.

정상 종료 표식:

```text
BOOTSTRAP_OK Ubuntu=22.04 ROS_DISTRO=humble
WEEKEND_WORKSPACE_VERIFY_OK ROS_DOMAIN_ID=142
CONTROL_PC_RUNTIME_OK
CONTROL_PC_READY
```

2026-07-18 현재 PC의 실제 결과는 `183 tests, 0 errors, 0 failures, 0 skipped`,
`ROBOTLESS_OPERATIONS_SMOKE_OK`, `Robotless TB1 navigation smoke test passed`,
`Robotless Zenoh navigation action smoke test passed`였다.

### 로그인 자동 시작과 연결 직전 점검

종합 부트스트랩은 Windows 사용자 로그인 시 아래 스크립트를 숨김 실행하도록 등록한다.
WSL은 마지막 Windows-side `wsl.exe` 클라이언트가 끝나면 systemd 서비스가 있어도 배포판을
종료할 수 있으므로, 스크립트는 숨김 keepalive 프로세스와 Zenoh·Gateway 서비스를 함께
관리한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\control-pc\start_control_stack.ps1
powershell -ExecutionPolicy Bypass -File scripts\control-pc\test_tb1_connection.ps1
```

두 번째 명령은 TB1이 없을 때 SSH와 Zenoh 포트만 WARN으로 남기고 PC 준비 상태를 판정한다.
TB1을 LAN에 연결한 뒤에는 두 포트도 필수로 바꾼다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\control-pc\test_tb1_connection.ps1 `
  -RequireRobot
```

Ethernet으로 최초 접속한 뒤 이동 시험 공간을 확보하려면 케이블을 먼저 뽑지 않는다.
TB1의 `wlan0`이 `DOWN`이거나 IPv4 주소가 없으면 SSH·Zenoh·Gateway가 함께 끊긴다. 다음
스크립트는 비밀번호를 화면과 명령 기록에 표시하지 않는 보안 입력으로 받고, 별도 권한
`0600` netplan 파일을 설치한다. Wi-Fi SSH를 확인한 뒤 관제 PC의 로컬 주소 표식과 WSL
Zenoh endpoint를 새 주소로 바꾼다. 기존 CycloneDDS 프로세스가 시작 때 선택한 유선
인터페이스를 유지할 수 있으므로 motion 프로필이 모두 inactive인 것도 확인한 뒤 bringup,
watchdog, agent와 robot-side Zenoh를 fail-closed 순서로 재시작한다. Gateway가 TB1의 새
heartbeat와 safety 상태를 다시 관찰할 때만 성공한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\control-pc\setup_tb1_wifi.ps1 `
  -Ssid <TB1_WIFI_SSID>
```

비밀번호는 매개변수나 채팅에 쓰지 않고 표시되지 않는 prompt에서만 입력한다. 성공 표식
`TB1_WIFI_SETUP_OK`를 본 다음 Ethernet을 뽑고 10초 기다린 뒤 아래 검사를 다시 통과해야
실차 절차를 계속한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\control-pc\test_tb1_connection.ps1 `
  -RequireRobot
```

## 3. 로봇 없는 웹 관제 실행

```bash
cd /mnt/c/project/turtlebot-fleet-ops
bash scripts/weekend/start_mock_stack.sh
```

Windows 브라우저에서 `http://localhost:8000`을 연다. mock은 다음 계약을 제공한다.

포트가 이미 사용 중이면 `WEB_PORT=18000 bash scripts/weekend/start_mock_stack.sh`처럼 다른
포트를 지정한다.

브라우저 확인 전 자동 smoke test도 실행할 수 있다.

```bash
bash scripts/weekend/smoke_test_mock.sh
```

정상 종료 표식은
`WEEKEND_MOCK_SMOKE_OK tasks=faults=audit final_estop=true`다.

- `tb1` 상태 heartbeat, 배터리, odom, LiDAR·시스템·Wi-Fi 예제 값
- 기본 활성 상태의 mock e-stop과 RobotStatus·NavigationStatus·SafetyStatus
- OccupancyGrid, 초기 위치와 e-stop 서비스
- `/tb1/navigation/navigate` custom Action과 Gateway lease
- 작업 생성·실행·성공·취소·실패·재시도와 SQLite 감사 기록
- Goal 실행 중 위치, 남은 거리와 lease age feedback
- deadman manual session, 0.35초 로컬 timeout과 속도 상한
- MAPPING/NAVIGATION 프로필, 지도 저장 서비스와 MappingStatus
- 방향을 포함한 웨이포인트 순찰 생성·실행·취소
- ROS 2 로그 incident의 원인·증거·권장 조치 API

테스트 규칙:

| 입력 | mock 결과 |
| --- | --- |
| e-stop 해제·초기 위치 뒤 `x=0.5` | 약 2초 뒤 성공 |
| `x>=1.5` | 30초 실행해 cancel·lease 연습 가능 |
| `x<0.0` | 수락 뒤 abort되어 retry 연습 가능 |
| 실행 중 e-stop 적용 | Goal abort |

mock 프로세스는 OpenCR, LiDAR, `/cmd_vel`을 사용하지 않는다. 화면과 API에 나타난 성공은
웹·ROS Action 수명주기 검증이며 실제 주행 성공으로 기록하지 않는다.

Phase 8 실차 대기 항목과 3~4시간 예상 절차는
[웹 수동 조종·순찰·매핑 운영 문서](tb1-web-patrol-mapping.md)에 정리돼 있다.

## 4. 기기 간 Git 인수인계

작업 시작:

```bash
git fetch --prune
git switch codex/phase-5-tb1-navigation
git pull --ff-only
git status
```

작업 종료:

```bash
bash scripts/weekend/verify_workspace.sh
git diff --check
git status
git add <검토한 파일>
git commit -m "feat: describe the completed unit"
git push
```

한 기기에서 push하지 않은 변경은 다른 기기에서 보이지 않는다. 기기를 바꾸기 전에는 항상
clean working tree와 원격 동기화를 확인한다. 같은 브랜치를 두 PC에서 동시에 수정하지 않는다.

## 5. Google Drive 권장 구조

```text
Google Drive/
└── TurtleBot-Fleet-Ops-Artifacts/
    ├── 2026-07-16-field-mapping/
    │   ├── videos/
    │   ├── screenshots/
    │   └── notes.txt
    ├── maps-backup/
    └── rosbags/
```

파일 이름에는 날짜, 로봇 ID와 목적을 넣는다. Drive 링크가 외부 공개인지 확인하고 비밀번호,
토큰, Wi-Fi 정보와 사설 IP가 포함된 터미널 캡처는 업로드하지 않는다. 코드 문서에는 필요한
경우 Drive 파일 이름과 SHA-256만 기록하고 개인 공유 링크는 공개 저장소에 넣지 않는다.

## 6. 로봇 없이 구현·검증하는 범위

현재 자동 경로는 TB1 로그·장애 이벤트, 단일 작업 상태 머신, 웹 작업·고장·감사 UI,
mock REST·WebSocket·Action, 실제 Humble Nav2 graph, Zenoh action 전달과 systemd 설정
validation까지 포함한다. 새 변경은 `verify_workspace.sh`와 CI를 모두 통과시킨다.

로봇이 돌아온 뒤에만 하는 작업:

- loop closure 실차 이동과 지도 품질 판정
- 지도 저장 뒤 AMCL 수렴
- 실제 Nav2 Goal, e-stop, 충돌 여유와 복구 acceptance
- 임시 LDS-02 GPIO 점퍼의 진동 내구성 판단

## 다음 PC로 넘기기 전 체크리스트

- [ ] 현재 작업 브랜치를 pull했다.
- [ ] bootstrap이 `BOOTSTRAP_OK`와 `CONTROL_PC_READY`로 끝났다.
- [ ] 전체 검증이 `WEEKEND_WORKSPACE_VERIFY_OK`로 끝났다.
- [ ] `test_tb1_connection.ps1`이 PC 항목을 모두 PASS로 판정했다.
- [ ] mock 대시보드에서 tb1 online과 기본 e-stop 활성 상태를 확인했다.
- [ ] GitHub 인증과 push 권한을 확인했다.
- [ ] Drive 폴더와 Git working tree를 분리했다.
