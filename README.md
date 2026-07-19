# TurtleBot Fleet Ops

ROS 2 기반 TurtleBot 웹 관제·운영 학습 프로젝트다. 현재 MVP는 `tb1` 한 대에 집중해
bringup, 상태 수집, 안전 제어, 웹 관제, 자율주행, 작업과 장애 복구를 끝에서 끝까지
완성한다. TB2와 다중 로봇 할당은 현재 범위에서 제외하고 후속 확장으로만 남긴다.

> 현재 상태: Phase 5·6 TB1 단일 로봇 MVP 실차 수용 시험과 `main` 병합 완료. Phase 7에서는
> 정확한 확대·이동 지도 뷰포트와 `/rosout` 이상탐지 MLOps를 구현했으며 TB1 로그 데이터 기반
> end-to-end 수집을 확인했다. 재부팅 직후 실차 로그에서 제어 주기 지연·경로 실패·충돌 방지
> 개입을 분리 진단했고, 전송 후보가 없는 기본 좌표 재사용을 차단했다. 후속 제자리 방향 목표가
> 오도메트리 이동과 달리 지도 자세에 수렴하지 않은 사건을 계기로 지도 기준 진척·피드백·최대
> 실행시간 감시도 navigation agent에 추가했다. 이후 잘못된 초기 yaw로 지도와 실제 이동이
> 반대로 보이며 벽에 접촉한 회귀를 e-stop으로 종료했다. 실시간 LiDAR overlay, 전역 scan-map
> 자동 정렬, 정합률 미달 초기 pose의 `422` 거부, 20cm 로컬 clearance와 현재 pose 자유 셀
> 감시를 배포했다. 대표성 있는 정상 주행
> 데이터와 Production 모델 수용 시험은 남아 있다. TB2와 자동 작업 할당은 완료 범위에 포함하지 않는다.

## 프로젝트 목표

- `tb1`의 ROS 2 상태를 실시간으로 수집한다.
- 웹에서 로봇 상태, 위치, 배터리와 장애를 관제한다.
- Nav2 목적지와 작업을 로봇에 전달한다.
- 단일 로봇 작업의 생성·실행·취소·실패·재시도를 추적한다.
- 센서, 통신, 프로세스와 주행 장애를 근거 데이터로 진단한다.
- ROS 2 로그의 수집·학습·승격·추론을 재현 가능한 MLOps 수명주기로 운영한다.
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
| Phase 7 | 정밀 지도 UX와 ROS 2 로그 이상탐지 MLOps | 구현·TB1 수집 경로 확인, Production 모델 수용 시험 전 |

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

TB1 /rosout ── /fleet/rosout relay ── Zenoh ──> log collector ──> model registry
                                           │
                                           └── inference status ──> Gateway/Web
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
- 후속 회귀 시험에서 같은 위치의 방향 목표가 76.4초 동안 지도 자세에 수렴하지 않아 명시적으로
  취소했다. 세 속도 경로의 상한과 watchdog 단일 Publisher는 유지됐고, 지도 진척 20초·Nav2
  feedback 3초·절대 180초 상한의 로컬 감시와 fake Nav2 회귀 테스트를 추가했다.
- Phase 7 주행 회귀에서는 약 180° 뒤집힌 초기 yaw가 웹과 실제 이동을 어긋나게 한 것을 실제
  LiDAR endpoint로 확인했다. 자동 scan-map 정렬은 잘못된 후보의 일치도 8%를 92~93%로
  보정했고, 지도 내부 endpoint 비율은 99~100%였다. 정합률 35% 미만 pose는 초기 위치 서비스에
  전달하지 않는다.

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
- [ROS 2 로그 MLOps 학습·승격·추론 운영](docs/setup/ros2-log-mlops.md)
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
- [Phase 7 ROS 2 로그 분석 MLOps 공부](docs/study/phase-7-ros2-log-mlops.md)
- [Phase 7 ROS 2 로그 MLOps와 지도 뷰포트 설계](docs/design/phase-7-ros2-log-mlops.md)
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
- [Phase 7 ROS 2 로그 MLOps와 지도 뷰포트 구현 일지](docs/learning-log/2026-07-19-phase-7-ros2-log-mlops-and-map-viewport.md)

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

1. TB1 `/rosout` 정상 운전 기준을 수집하고 후보 품질을 검토해 Production 모델을 승격한다.
2. 알려진 오류 replay에서 anomaly score·원인 특징·탐지 지연과 false positive를 기록한다.
3. 10 Hz Behavior Tree와 지도 기준 goal supervision을 적용한 정상 목표에서 장시간 기준 로그와
   자동 취소 시간을 추가 수집한다.
4. 저상 장애물 LiDAR 사각과 큰 방향 전환 recovery는 운영 제한과 tuning backlog로 유지한다.
5. TB2 namespace·TF·Action 격리와 자동 작업 할당은 별도 후속 범위에서 시작한다.
