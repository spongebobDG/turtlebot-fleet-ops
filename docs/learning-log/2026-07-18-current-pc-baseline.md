# 학습 일지: 현재 관제 PC 기준선 재조사

날짜: 2026-07-18

단계: 로봇 없는 개발 환경 재현

진행 상태: Windows 비ROS 테스트 가능, ROS 2 Humble 실행은 GitHub CI 사용

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
| Node.js | PATH에서는 없지만 Codex bundled Node로 웹 구문·좌표 테스트 가능 |
| Docker | PATH에서 찾지 못함 |
| Windows ROS 2·colcon | PATH에서 찾지 못함 |
| WSL | inbox 명령은 있으나 `--status`가 최신 형식으로 동작하지 않았고 설치된 Ubuntu 증거 없음 |

WSL이 없다고 단정하기보다 현재 명령으로 배포판과 Humble 실행을 확인하지 못한 상태로
기록한다. 따라서 ROS graph 테스트는 Ubuntu 22.04 GitHub Actions를 권위 있는 증거로 사용한다.
최종 robotless 기준선은
[Actions run 29601662765](https://github.com/spongebobDG/turtlebot-fleet-ops/actions/runs/29601662765)의
`183 tests, 0 errors, 0 failures, 0 skipped`와 세 ROS smoke 통과다.

## 현재 PC에서 추가한 검증 도구

Windows Python에 pytest, FastAPI, uvicorn, WebSocket runtime, httpx, PyYAML, psutil과 정적
검사 도구를 설치했다. 이 도구로 SQLite·REST·정책 테스트와 ROS-free 웹 preview를 실행하고
ROS 메시지 생성·action·launch는 CI에서 실행한다.

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

처음 설치한 pip `uvicorn`에는 WebSocket backend가 포함되지 않아 REST는 정상인데 화면이
`재연결 중`에 머물렀다. `websockets`를 명시적으로 설치해 해결했고 Windows preview 절차에도
같은 의존성을 기록했다. Ubuntu 22.04의
[`python3-uvicorn`](https://packages.ubuntu.com/jammy/python/python3-uvicorn)은
`python3-wsproto`에 의존하므로 ROS 배포 경로와 Windows pip 개발 경로를 구분한다.

## TB1 재연결 전 환경 준비 영향

이 PC를 실제 관제 PC로 사용하려면 Ubuntu 22.04 WSL2 설치·재부팅 가능성, Humble bootstrap,
workspace build와 Zenoh/Gateway baseline 확인에 약 45~90분을 별도로 잡는다. Docker는 현재
Phase 5 실차 경로의 필수 조건이 아니므로 설치 시간에 포함하지 않는다.

환경 준비와 실차 acceptance를 합친 예상은 3시간 50분~6시간 5분이며, 재부팅·재시험
buffer 40분을 포함한 시험 창은 6시간 45분을 권장한다. 실제 WSL 상태나 TB1 접속이 더 빨리
복구되면 준비 시간은 줄어든다.
