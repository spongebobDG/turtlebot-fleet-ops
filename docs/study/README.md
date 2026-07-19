# 공부 문서 운영 방식

이 디렉터리는 프로젝트를 진행하며 반드시 이해해야 할 개념과 면접 모범 답변을 Phase별로 정리한다. 명령과 시행착오는 `docs/learning-log`, 재실행 절차는 `docs/setup`, 대표 문제 해결은 `docs/case-studies`에 분리한다.

## 문서별 역할

| 문서 | 목적 | 주요 독자 |
| --- | --- | --- |
| `README.md` | 프로젝트 전체 요약과 현재 상태 | 면접관, 협업자 |
| `docs/study` | 필수 개념, 설명 방법, 면접 모범 답변 | 학습자 본인 |
| `docs/case-studies` | 대표 문제의 진단과 의사결정 | 면접관, 기술 리뷰어 |
| `docs/setup` | 재현 가능한 설치·운영 절차 | 개발자, 운영자 |
| `docs/learning-log` | 실제 명령, 실패와 해결의 상세 기록 | 학습자 본인 |

## Phase 종료 때 반드시 남길 내용

1. 이번 Phase에서 반드시 알아야 하는 개념
2. 개념을 쉬운 말로 설명한 모범 답변
3. 실제 프로젝트에서 확인한 증거
4. 흔히 하는 틀린 설명과 바로잡기
5. 30초, 1분, 3분 설명 예시
6. 실무형 면접 질문과 모범 답변
7. 명령을 보지 않고 다시 해볼 체크리스트
8. 아직 모르는 내용과 다음 검증 항목

## 추천 학습 주기

### 작업 중

- 명령을 실행하기 전에 무엇을 확인하는지 한 문장으로 말한다.
- 성공 조건을 먼저 예상한다.
- 결과가 다르면 로그를 근거로 다음 계층을 확인한다.

### Phase 종료 직후

- 공부 문서의 필수 개념을 한 번 읽는다.
- 1분 설명을 소리 내어 말한다.
- 복습 문제의 답을 가리고 직접 답한다.
- 핵심 확인 명령 한두 개를 보지 않고 실행한다.

### 프로젝트 완료 후

- 전체 구조를 처음부터 다시 연결해서 본다.
- 대표 사례 3~5개를 STAR 형식으로 연습한다.
- 코드, 테스트, PR과 문서 링크를 함께 설명한다.
- 설계 대안과 현재 한계를 설명할 수 있는지 확인한다.

## 현재 공부 문서

- [Phase 1: TB1 Bringup과 LDS-02 장애 진단](phase-1-tb1-bringup.md)
- [Phase 2: 안전 수동 제어와 Watchdog](phase-2-safe-teleoperation.md)
- [Phase 3: Robot Agent와 상태 계약](phase-3-robot-agent.md)
- [Phase 4: 웹 Fleet Gateway와 분산 통신](phase-4-web-fleet-gateway.md)
- [Phase 5: 로컬 Nav2, 좌표 변환과 lease 기반 안전](phase-5-tb1-navigation.md)
- [Phase 5: SLAM, 지도 산출물과 실차 Nav2 검증](phase-5-slam-nav2.md)
- [Phase 6: TB1 작업 상태 머신과 운영 기록](phase-6-tb1-operations.md)
- [Phase 7: ROS 2 로그 분석 MLOps](phase-7-ros2-log-mlops.md)
- [Phase 8: Deadman 제어·순찰·프로필 전환·설명 가능한 MLOps](phase-8-web-control-patrol-diagnostics.md)
- [관제 PC: WSL2·ROS 2 지속 실행과 검증 계층](control-pc-wsl-ros2-readiness.md)

## 이해도 판정 기준

다음 네 단계로 판단한다.

| 단계 | 가능한 행동 |
| --- | --- |
| 1. 따라 하기 | 제공된 명령을 실행할 수 있다. |
| 2. 설명하기 | 각 명령이 무엇을 확인하는지 말할 수 있다. |
| 3. 재현하기 | 핵심 절차를 보지 않고 다시 수행할 수 있다. |
| 4. 응용하기 | 비슷한 새로운 장애에서 확인 순서를 설계할 수 있다. |

프로젝트 진행 중에는 1~2단계여도 괜찮다. 각 Phase 종료 때 2단계를 만들고, 프로젝트 완료 후 3~4단계까지 깊게 복습한다.
