# TurtleBot Fleet Ops

ROS 2 기반 다중 TurtleBot 웹 관제·플릿 관리 학습 프로젝트다. 두 대의 TurtleBot3를 단독 bringup부터 시작해 상태 수집, 안전 제어, 웹 관제, 자율주행, 작업 할당과 장애 복구까지 단계적으로 구현한다.

> 현재 상태: 개발 중. Phase 2의 TB1 안전 수동 제어와 watchdog 실차 검증을 완료했으며, 다음 단계는 구조화된 Robot Agent 상태 메시지다.

## 프로젝트 목표

- `tb1`, `tb2`의 ROS 2 상태를 실시간으로 수집한다.
- 웹에서 로봇 상태, 위치, 배터리와 장애를 관제한다.
- Nav2 목적지와 작업을 로봇에 전달한다.
- 작업을 적절한 로봇에 할당하고 장애 시 재할당한다.
- 센서, 통신, 프로세스와 주행 장애를 근거 데이터로 진단한다.
- 모든 과정에서 실행 결과, 실패 원인과 기술적 의사결정을 문서화한다.

## 현재 구성

| 구분 | 구성 |
| --- | --- |
| 로봇 | TurtleBot3 Burger 2대 (`tb1`, `tb2`) |
| SBC | Raspberry Pi 4, Ubuntu 22.04 |
| 로봇 미들웨어 | ROS 2 Humble |
| LiDAR | LDS-02 |
| 제어 보드 | OpenCR |
| 관제 개발환경 | Windows, WSL2 Ubuntu 22.04 |
| 컨테이너 | Docker Desktop WSL 통합 |
| 개발 방식 | GitHub Flow, 작업 브랜치, Draft PR, squash merge |

정확한 사설 IP, Wi-Fi 정보, 비밀번호와 토큰은 저장소에 기록하지 않는다.

## 단계별 진행 상태

| 단계 | 목표 | 상태 |
| --- | --- | --- |
| Phase 0 | 환경 조사, ROS 2·Docker·GitHub 개발환경 준비 | 완료 |
| Phase 1 | TB1 단독 bringup, OpenCR·LiDAR·주요 토픽 검증 | 완료, 설정 일반화 필요 |
| Phase 2 | TB1 저속 수동 제어, 정지와 watchdog | 완료 |
| Phase 3 | TB1 Robot Agent와 상태 메시지 | 다음 작업 |
| Phase 4 | 단일 로봇 웹 관제 | 대기 |
| Phase 5 이후 | Nav2, 로그, 장애 감지, TB2와 플릿 관리 | 대기 |

완료 표시는 실제 검증한 범위에만 사용한다. Phase 1의 `/scan` 수신은 확인했지만 정확한 발행 주기는 아직 기록하지 못했다.

## 현재 아키텍처

```text
LDS-02 ── UART ──> Raspberry Pi ── ld08_driver ──> /scan
OpenCR ── USB ───> Raspberry Pi ── turtlebot3_node ──> /odom, /battery_state
                                      │
                                      └── ROS 2 DDS, domain 42
                                               │
                                               └── WSL 관제 개발환경
```

최종 목표 구조:

```text
[tb1 Robot Agent] ─┐
                   ├── ROS 2 / Fleet Gateway ── FastAPI ── Web Dashboard
[tb2 Robot Agent] ─┘                  │
                                     ├── Task Manager
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

## 문서 안내

### 처음 보는 사람

- [Phase 1 대표 장애 해결 사례](docs/case-studies/lds02-scan-data-recovery.md)
- [TB1 Bringup 운영 절차](docs/setup/tb1-bringup.md)
- [TB1 안전 수동주행 및 Watchdog 검증 절차](docs/setup/tb1-safe-teleoperation.md)
- [Git 작업 흐름](docs/git-workflow.md)

### 공부와 면접 준비

- [공부 문서 운영 방식](docs/study/README.md)
- [Phase 1 필수 개념과 모범 답변](docs/study/phase-1-tb1-bringup.md)
- [Phase 2 안전 제어 필수 개념과 모범 답변](docs/study/phase-2-safe-teleoperation.md)
- [비상정지 중립 재무장 설계 사례](docs/case-studies/safety-watchdog-neutral-rearm.md)

### 실제 작업 이력

- [학습 일지 목록](docs/learning-log/README.md)
- [Phase 1 TB1 Bringup 학습 일지](docs/learning-log/2026-07-15-phase-1-tb1-bringup-and-lds02-gpio-uart.md)
- [Phase 2 TB1 Safety Watchdog 학습 일지](docs/learning-log/2026-07-15-phase-2-tb1-watchdog-deployment.md)

## 개발 원칙

1. TB1에서 기능 하나를 검증한 뒤 TB2와 다중 로봇으로 확장한다.
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

1. Phase 2 Draft PR을 최종 검토하고 `main`에 squash merge한다.
2. Phase 3에서 TB1 상태를 구조화하는 Robot Agent를 설계한다.
3. battery, odom, scan freshness와 시스템 자원을 상태 메시지로 통합한다.
4. TB1 전용 LiDAR 포트 하드코딩을 ROS 2 launch 설정으로 일반화한다.
5. 임시 GPIO 점퍼를 진동에 견디는 하네스로 교체한다.
