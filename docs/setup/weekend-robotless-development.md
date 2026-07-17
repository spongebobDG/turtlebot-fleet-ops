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

관리자 PowerShell에서 Ubuntu 22.04 WSL2가 없다면 설치한다.

```powershell
wsl --install -d Ubuntu-22.04
```

재부팅이 요구되면 재부팅하고 Ubuntu 사용자 계정을 만든다. Git 저장소는 Drive 밖의 일반
로컬 경로에 clone한다.

```powershell
New-Item -ItemType Directory -Force C:\project | Out-Null
cd C:\project
git clone https://github.com/spongebobDG/turtlebot-fleet-ops.git
cd turtlebot-fleet-ops
git fetch --prune
git switch codex/phase-5-tb1-navigation
git pull --ff-only
wsl -d Ubuntu-22.04
```

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

WSL Bash에서 Windows clone 경로로 이동한다.

```bash
cd /mnt/c/project/turtlebot-fleet-ops
bash scripts/weekend/bootstrap_ubuntu22.sh
bash scripts/weekend/verify_workspace.sh
```

첫 스크립트는 Ubuntu 22.04를 확인하고 ROS 2 Humble, 개발 도구와 workspace 의존성을
설치한다. 두 번째 스크립트는 현재 5개 패키지를 빌드하고 전체 테스트, Linux 줄바꿈,
systemd unit, JavaScript 구문과 TB1 작업·고장 mock smoke를 수행한다.

정상 종료 표식:

```text
BOOTSTRAP_OK Ubuntu=22.04 ROS_DISTRO=humble
WEEKEND_WORKSPACE_VERIFY_OK ROS_DOMAIN_ID=142
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

테스트 규칙:

| 입력 | mock 결과 |
| --- | --- |
| e-stop 해제·초기 위치 뒤 `x=0.5` | 약 2초 뒤 성공 |
| `x>=1.5` | 30초 실행해 cancel·lease 연습 가능 |
| `x<0.0` | 수락 뒤 abort되어 retry 연습 가능 |
| 실행 중 e-stop 적용 | Goal abort |

mock 프로세스는 OpenCR, LiDAR, `/cmd_vel`을 사용하지 않는다. 화면과 API에 나타난 성공은
웹·ROS Action 수명주기 검증이며 실제 주행 성공으로 기록하지 않는다.

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
mock REST·WebSocket·Action과 systemd 설정 validation까지 포함한다. 새 변경은
`verify_workspace.sh`와 CI를 모두 통과시킨다.

로봇이 돌아온 뒤에만 하는 작업:

- loop closure 실차 이동과 지도 품질 판정
- 지도 저장 뒤 AMCL 수렴
- 실제 Nav2 Goal, e-stop, 충돌 여유와 복구 acceptance
- 임시 LDS-02 GPIO 점퍼의 진동 내구성 판단

## 다음 PC로 넘기기 전 체크리스트

- [ ] 현재 작업 브랜치를 pull했다.
- [ ] bootstrap이 `BOOTSTRAP_OK`로 끝났다.
- [ ] 전체 검증이 `WEEKEND_WORKSPACE_VERIFY_OK`로 끝났다.
- [ ] mock 대시보드에서 tb1 online과 기본 e-stop 활성 상태를 확인했다.
- [ ] GitHub 인증과 push 권한을 확인했다.
- [ ] Drive 폴더와 Git working tree를 분리했다.
