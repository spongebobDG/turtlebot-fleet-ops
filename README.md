# TurtleBot Fleet Ops

ROS 2 기반 TurtleBot 웹 관제·운영 학습 프로젝트다. 현재 MVP는 `tb1` 한 대에 집중해
bringup, 상태 수집, 안전 제어, 웹 관제, 자율주행, 작업과 장애 복구를 끝에서 끝까지
완성한다. TB2와 다중 로봇 할당은 현재 범위에서 제외하고 후속 확장으로만 남긴다.

> 현재 상태: TB1 단일 로봇 MVP 실차 수용 시험 완료, Draft PR 검토 전. Phase 5의 지도·AMCL·
> 웹 목표·안전 장애 시험과 Phase 6의 작업 성공·취소·재시도·프로세스 복구·재부팅 무재개를
> 2026-07-19 TB1에서 검증했다. 최신 회귀 기준은 관제 PC 격리 Humble 191개와 TB1의 현재
> 소스 패키지에 한정한 144개 테스트다. TB2와 자동 작업 할당은 완료 범위에 포함하지 않는다.

## 프로젝트 목표

- `tb1`의 ROS 2 상태를 실시간으로 수집한다.
- 웹에서 로봇 상태, 위치, 배터리와 장애를 관제한다.
- Nav2 목적지와 작업을 로봇에 전달한다.
- 단일 로봇 작업의 생성·실행·취소·실패·재시도를 추적한다.
- 센서, 통신, 프로세스와 주행 장애를 근거 데이터로 진단한다.
- 모든 과정에서 실행 결과, 실패 원인과 기술적 의사결정을 문서화한다.

## 현재 구성

| 구분 | 구성 |
| --- | --- |
| 현재 대상 | TurtleBot3 Burger 1대 (`tb1`) |
| 현재 범위 밖 | TB2 실차, 다중 로봇 할당·재할당 |
| SBC | Raspberry Pi 4, Ubuntu 22.04 |
| 로봇 미들웨어 | ROS 2 Humble |
| LiDAR | LDS-02 |
| 제어 보드 | OpenCR |
| 관제 개발환경 | Windows, WSL2 Ubuntu 22.04 |
| 컨테이너 | 현재 실차 경로에서 미사용, Docker 미설치 |
| 개발 방식 | GitHub Flow, 작업 브랜치, Draft PR, squash merge |

정확한 사설 IP, Wi-Fi 정보, 비밀번호와 토큰은 저장소에 기록하지 않는다.

## 단계별 진행 상태

| 단계 | 목표 | 상태 |
| --- | --- | --- |
| Phase 0 | 환경 조사, ROS 2·Docker·GitHub 개발환경 준비 | 완료 |
| Phase 1 | TB1 단독 bringup, OpenCR·LiDAR·주요 토픽 검증 | 완료, 설정 일반화 필요 |
| Phase 2 | TB1 저속 수동 제어, 정지와 watchdog | 완료 |
| Phase 3 | TB1 Robot Agent와 상태 메시지 | 완료 |
| Phase 4 | 단일 로봇 웹 관제 | 완료, `main` 병합 |
| Phase 5 | TB1 SLAM·AMCL·Nav2와 웹 목적지 제어 | 완료, TB1 실차 수용 시험 및 제한사항 기록 |
| Phase 6 | TB1 로그·장애 감지·단일 작업 수명주기 | 완료, TB1 terminal·프로세스 복구·재부팅 수용 시험 기록 |

완료 표시는 실제 검증한 범위에만 사용한다. Phase 1의 `/scan` 수신은 확인했지만 정확한 발행 주기는 아직 기록하지 못했다.

## 현재 아키텍처

```text
LDS-02 ── UART ──> Raspberry Pi ── ld08_driver ──> /scan
OpenCR ── USB ───> Raspberry Pi ── turtlebot3_node ──> /odom, /battery_state
                                      │
                                      └── ROS 2 DDS, domain 42
                                               │
                         robot_agent ──> /fleet/robot_status
                                               │
                                      TB1 Zenoh bridge
                                               │ TCP 7447
                                      WSL Zenoh bridge
                                               │ loopback DDS
                                      Fleet Gateway ──> Web Dashboard
                                               │ action + lease
                                      navigation_agent
                                               │
                     Nav2 ──> motion_arbiter ──> watchdog policy
                                                        │
                                              C++ watchdog guard ──> /cmd_vel
```

현재 TB1 MVP 목표 구조:

```text
[tb1 Robot Agent] ── ROS 2 / Fleet Gateway ── FastAPI ── Web Dashboard
                                           │
                                           ├── Single-Robot Task Manager
                                           ├── Safety / Fault Manager
                                           └── Logs / Metrics / Incident Analysis
```

## 대표 검증 결과

Phase 1에서 `/scan` Publisher는 존재하지만 메시지가 나오지 않는 장애를 조사했다.

- 드라이버의 CP2102 읽기 카운터가 5초 동안 증가하지 않았다.
- 흐름 제어 설정과 관계없이 `/dev/ttyUSB0` 원시 입력이 시간 초과됐다.
- LDS-02 TX 선의 커넥터 이탈을 발견했다.
- Raspberry Pi GPIO15 UART 우회 경로에서 5초 동안 44,105바이트를 수신했다.
- LDS-02 패킷 헤더 `54 2c`를 940회 확인했다.
- 드라이버가 `/dev/serial0`을 사용하도록 수정한 후 `/scan` 수신을 복구했다.

상세 사례: [LDS-02 `/scan` 데이터 복구](docs/case-studies/lds02-scan-data-recovery.md)

Phase 5 실차 수용 시험에서는 다음을 확인했다.

- 58×96, 0.05 m/cell 지도와 pose graph를 로봇 로컬 저장소 밖 디렉터리에 저장했다.
- 초기 위치 이후 AMCL과 수치 정합 오차 4.4 cm를 확인하고 짧은 목표를 recovery 없이 도달했다.
- Nav2·arbiter·최종 출력에서 각각 `0.05 m/s`, `0.3 rad/s` 상한을 지켰다.
- `/cmd_vel` Publisher는 C++ `/safety_watchdog` 하나뿐이었다.
- e-stop, Zenoh 단절, agent·Nav2·arbiter·watchdog 장애에서 목표를 폐기하고 자동 재출발하지 않았다.
- 10분 표본의 CPU는 평균 69.14%, 최대 85.20%, 메모리는 평균 20.63%, 최대 20.70%로
  90% 경고가 지속되지 않았다.

낮은 장애물이 LiDAR 평면 아래에 있어 검출되지 않은 현장 사례와, 큰 방향 전환을 반복한
목표에서 recovery 후 stale 취소된 관찰은 운영 제한으로 남겼다. 상세 측정과 판정은
[Phase 5 TB1 실차 수용 시험 일지](docs/learning-log/2026-07-19-phase-5-tb1-navigation-acceptance.md)에 있다.

Phase 6 실차 수용 시험에서는 task 생성과 실행을 분리한 운영 경로를 확인했다.

- 생성 후 취소, 성공, 실행 중 취소와 retry attempt 성공이 SQLite·REST·NavigationStatus에서
  같은 terminal 상태로 남았다.
- Gateway 재시작과 navigation agent 강제 종료 중인 작업은 `FAILED`로 닫혔고 자동 재개되지 않았다.
- TB1 재부팅 뒤 Wi-Fi 준비를 기다린 후 ROS·Zenoh가 자동 시작됐으며 관제 서비스를 재시작하지
  않아도 online heartbeat가 복구됐다.
- 재부팅 전후 활성 목표와 활성 작업은 0개였고 최종 `/cmd_vel`은 0이었다.

상세 측정과 테스트 수치 감사는
[Phase 6 TB1 작업·복구 실차 수용 시험 일지](docs/learning-log/2026-07-19-phase-6-tb1-operations-acceptance.md)에 있다.

## 문서 안내

### 처음 보는 사람

- [Phase 1 대표 장애 해결 사례](docs/case-studies/lds02-scan-data-recovery.md)
- [TB1 Bringup 운영 절차](docs/setup/tb1-bringup.md)
- [TB1 안전 수동주행 및 Watchdog 검증 절차](docs/setup/tb1-safe-teleoperation.md)
- [TB1 Robot Agent 배포 및 검증 절차](docs/setup/tb1-robot-agent.md)
- [TB1 웹 관제 대시보드 운영 절차](docs/setup/tb1-web-dashboard.md)
- [TB1 매핑·Nav2·웹 목적지 운영 및 검증](docs/setup/tb1-navigation.md)
- [TB1 작업·감사·재부팅 복구 운영 및 검증](docs/setup/tb1-operations.md)
- [로봇 없는 TB1 개발·mock 검증](docs/setup/weekend-robotless-development.md)
- [Zenoh ROS 2 DDS 브리지 운영](infra/zenoh/README.md)
- [Git 작업 흐름](docs/git-workflow.md)

### 공부와 면접 준비

- [공부 문서 운영 방식](docs/study/README.md)
- [Phase 1 필수 개념과 모범 답변](docs/study/phase-1-tb1-bringup.md)
- [Phase 2 안전 제어 필수 개념과 모범 답변](docs/study/phase-2-safe-teleoperation.md)
- [Phase 3 Robot Agent 필수 개념과 모범 답변](docs/study/phase-3-robot-agent.md)
- [Phase 4 웹 Fleet Gateway 필수 개념과 모범 답변](docs/study/phase-4-web-fleet-gateway.md)
- [Phase 5 로컬 Nav2·좌표·lease 안전 필수 개념](docs/study/phase-5-tb1-navigation.md)
- [관제 PC WSL2·ROS 2 지속 실행과 검증 계층](docs/study/control-pc-wsl-ros2-readiness.md)
- [비상정지 중립 재무장 설계 사례](docs/case-studies/safety-watchdog-neutral-rearm.md)
- [Robot Agent stale 감지·복구 사례](docs/case-studies/robot-agent-stale-recovery.md)
- [Zenoh 서비스 시간 초과와 RMW 혼용 사례](docs/case-studies/zenoh-service-timeout-rmw-mismatch.md)
- [Phase 3 Robot Agent 설계](docs/design/phase-3-robot-agent.md)
- [Phase 4 Fleet Gateway 설계](docs/design/phase-4-tb1-web-dashboard.md)
- [Phase 5 TB1 Nav2와 웹 목적지 설계](docs/design/phase-5-tb1-navigation.md)
- [Phase 6 TB1 작업·고장·감사 설계](docs/design/phase-6-tb1-operations.md)
- [Phase 6 작업 상태 머신·운영 기록 공부](docs/study/phase-6-tb1-operations.md)
- [현재 TB1 단일 로봇 MVP 범위와 완료 조건](docs/design/project-scope.md)
- [SLAM Toolbox 가변 스캔 정규화 사례](docs/case-studies/slam-toolbox-variable-scan-normalization.md)

### 실제 작업 이력

- [학습 일지 목록](docs/learning-log/README.md)
- [Phase 1 TB1 Bringup 학습 일지](docs/learning-log/2026-07-15-phase-1-tb1-bringup-and-lds02-gpio-uart.md)
- [Phase 2 TB1 Safety Watchdog 학습 일지](docs/learning-log/2026-07-15-phase-2-tb1-watchdog-deployment.md)
- [Phase 3 Robot Agent 구현 일지](docs/learning-log/2026-07-16-phase-3-robot-agent-implementation.md)
- [Phase 3 TB1 Robot Agent 실차 검증 일지](docs/learning-log/2026-07-16-phase-3-tb1-robot-agent-validation.md)
- [Phase 4 TB1 웹 관제와 Zenoh 통신 일지](docs/learning-log/2026-07-16-phase-4-web-dashboard-and-zenoh.md)
- [Phase 5 TB1 Nav2 구현 일지](docs/learning-log/2026-07-17-phase-5-tb1-navigation-implementation.md)
- [TB1 단일 로봇 MVP 범위 결정 일지](docs/learning-log/2026-07-16-single-robot-mvp-scope-decision.md)
- [로봇 없는 개발 인수인계 일지](docs/learning-log/2026-07-16-weekend-robotless-handoff.md)
- [TB1 로봇 없는 운영 기능 일지](docs/learning-log/2026-07-18-tb1-robotless-operations.md)
- [현재 PC TB1 관제 준비 완료 일지](docs/learning-log/2026-07-18-control-pc-readiness.md)
- [TB1 acceptance 배포와 정지 상태 사전검증 일지](docs/learning-log/2026-07-18-tb1-acceptance-deployment.md)
- [Phase 5 TB1 실차 수용 시험 완료 일지](docs/learning-log/2026-07-19-phase-5-tb1-navigation-acceptance.md)
- [Phase 6 TB1 작업·복구 실차 수용 시험 완료 일지](docs/learning-log/2026-07-19-phase-6-tb1-operations-acceptance.md)

## 개발 원칙

1. TB1의 수직 기능과 운영 증거를 먼저 완성하고 TB2는 현재 완료 조건에 포함하지 않는다.
2. 토픽 이름이 아니라 실제 메시지와 측정값으로 성공을 판정한다.
3. 안전 관련 최종 정지는 로봇 내부의 규칙 기반 노드가 담당한다.
4. 로봇별 차이는 코드 하드코딩이 아니라 설정으로 분리한다.
5. 실행하지 않은 기능과 측정하지 않은 성능을 완료라고 기록하지 않는다.
6. 실패 로그와 해결 과정도 포트폴리오 증거로 남긴다.

## Git 작업 방식

```text
main 최신화
→ 목적별 작업 브랜치
→ 구현과 직접 검증
→ 운영 문서·학습 문서 작성
→ 작은 커밋
→ 원격 push
→ Draft PR
→ 자체 리뷰
→ squash merge
```

`main`에는 PR을 통해 검증된 단위만 반영한다. `main`은 프로젝트가 완전히 끝난 뒤 한 번 사용하는 브랜치가 아니라 현재 통합 가능한 기준선이다.

## 다음 작업

1. 저상 장애물 LiDAR 사각을 운영 전 점검표에 유지하고, 반복 큰 방향 전환의
   recovery·stale 현상은 costmap과 controller tuning 후보로 추적한다.
2. Draft PR의 최종 회귀 CI와 자체 리뷰를 확인한 뒤 현재 브랜치를 `main`에 squash merge한다.
3. TB2 namespace·TF·Action 격리와 자동 작업 할당은 별도 후속 범위에서 시작한다.
