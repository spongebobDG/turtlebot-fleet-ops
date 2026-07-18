# 학습 일지: 현재 관제 PC 기준선 재조사

날짜: 2026-07-18

단계: 로봇 없는 개발 환경 재현

진행 상태: WSL2 Ubuntu 22.04·ROS 2 Humble·관제 서비스·전체 무로봇 검증 완료

## 재조사 이유

이전 Phase 0 문서는 다른 PC에서 측정한 64GB 메모리, WSL Ubuntu-22.04와 Docker 환경을
기록한다. 현재 작업 PC에 그 값을 그대로 적용하지 않고 새 기준선을 측정했다.

## 현재 측정값

| 항목 | 현재 결과 |
| --- | --- |
| 저장소 | `C:\projects\turtlebot-fleet-ops` |
| Windows | Windows 10 Pro 64-bit, 10.0.19045 |
| 메모리 | 17,108,664,320 bytes, 약 15.9GiB |
| Python | 3.12.10 |
| Git | 2.55.0.windows.2 |
| GitHub CLI | 2.96.0, `spongebobDG` 인증 완료 |
| Bash | Git for Windows Bash 사용 가능 |
| Node.js | Windows 24.18.0, 웹 JavaScript 구문 검사 통과 |
| Docker | PATH에서 찾지 못함 |
| Windows ROS 2·colcon | PATH에서 찾지 못함 |
| WSL | 2.7.10.0, Ubuntu-22.04 WSL2, kernel 6.18.33.2, systemd 활성 |
| WSL ROS | ROS 2 Humble Desktop, Nav2, SLAM Toolbox, CycloneDDS |
| Zenoh | `zenoh-bridge-ros2dds` 1.9.0 |

최초 조사 때는 BIOS SVM과 Windows WSL 기능이 꺼져 있어 ROS graph를 로컬에서 실행할 수
없었다. SVM 활성화, Windows 기능 설치와 재부팅 후 Ubuntu-22.04를 만들고 실제 Humble
graph까지 검증했다. GitHub Actions와 현재 PC의 두 계층 모두 `183 tests, 0 errors,
0 failures, 0 skipped`와 세 ROS smoke를 통과했다.

## 현재 PC에서 추가한 검증 도구

Windows Python에 pytest, FastAPI, uvicorn, WebSocket runtime, httpx, PyYAML, psutil과 정적
검사 도구를 설치했다. WSL에는 Humble Desktop과 프로젝트 의존성을 설치해 ROS 메시지
생성·action·launch도 현재 PC에서 직접 실행한다.

현재 로컬 결과:

- Gateway SQLite·FastAPI·task·registry·map: 39 passed, 1 Windows symlink skip
- navigation 지도 validator·model·motion 정책·pose checkpoint·운영 설정·Zenoh 계약: 62 passed
- watchdog policy: 15 passed
- Robot Agent model·system metrics: 30 passed
- 로컬 비ROS Python 합계: 146 passed, 1 skip
- Python AST, pycodestyle, pyflakes, Git Bash `bash -n`: 통과
- bundled Node.js `app.js --check`와 map 좌표 테스트 3개: 통과
- in-app browser: 실시간 WebSocket 연결, seeded 지도·WARN·fault·audit 표시, 작업
  `CREATED -> ACTIVE -> CANCELED` 조작과 console error 0개 확인
- WSL Humble: 5개 패키지, 183 passed, failure·skip 0
- robotless operations·Nav2 stack·Zenoh action smoke: 모두 통과
- Windows 로그인 자동 시작, WSL keepalive, Zenoh·Gateway systemd 서비스와
  `http://localhost:8000/api/health`: 통과

처음 설치한 pip `uvicorn`에는 WebSocket backend가 포함되지 않아 REST는 정상인데 화면이
`재연결 중`에 머물렀다. `websockets`를 명시적으로 설치해 해결했고 Windows preview 절차에도
같은 의존성을 기록했다. Ubuntu 22.04의
[`python3-uvicorn`](https://packages.ubuntu.com/jammy/python/python3-uvicorn)은
`python3-wsproto`에 의존하므로 ROS 배포 경로와 Windows pip 개발 경로를 구분한다.

## TB1 재연결 전 환경 준비 영향

Ubuntu 22.04 WSL2 설치·재부팅, Humble bootstrap, workspace build, Zenoh/Gateway baseline과
지속 실행 문제를 모두 해결했다. TB1 연결 당일에는 환경 구성 시간을 별도로 잡지 않고,
`test_tb1_connection.ps1 -RequireRobot`으로 실제 SSH·Zenoh 포트가 열린 것만 확인한다.
Docker는 현재 Phase 5 실차 경로의 필수 조건이 아니다.

남은 순수 실차 acceptance 예상은 `3시간 5분~4시간 35분`이다. 최대치에 재시험 buffer
40분을 더한 시험 창은 `5시간 15분`을 권장한다. TB1 인증, 실제 센서·모터, 물리 정지시간과
Raspberry Pi 자원 사용량은 로봇 없이는 확정할 수 없다.
