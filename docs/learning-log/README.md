# 학습 일지 작성 규칙

각 작은 작업이 끝날 때 `YYYY-MM-DD-주제.md` 형식으로 기록한다. 같은 날짜에 여러 작업이 있으면 주제가 겹치지 않도록 구체적인 이름을 사용한다.

## 단계별 주요 기록

- Phase 0: [환경 조사](2026-07-15-phase-0-environment-survey.md)
- Phase 0: [ROS 2 Humble 설치](2026-07-15-wsl-ros2-humble-install.md)
- Phase 0: [Docker Desktop 및 WSL 통합](2026-07-15-docker-desktop-wsl-install.md)
- Phase 0: [Git 작업 방식과 첫 브랜치](2026-07-15-git-workflow-and-first-branch.md)
- Phase 0: [GitHub 원격 저장소 구성](2026-07-15-github-cli-and-remote-repository.md)
- Phase 0: [PR 검토와 main 보호](2026-07-15-github-pr-review-and-main-ruleset.md)
- Phase 1: [TB1 Bringup과 LDS-02 GPIO UART 복구](2026-07-15-phase-1-tb1-bringup-and-lds02-gpio-uart.md)
- Phase 2: [TB1 Safety Watchdog 배포](2026-07-15-phase-2-tb1-watchdog-deployment.md)
- Phase 3: [Robot Agent 구현](2026-07-16-phase-3-robot-agent-implementation.md)
- Phase 3: [TB1 Robot Agent 실차 검증](2026-07-16-phase-3-tb1-robot-agent-validation.md)
- Phase 4: [TB1 웹 관제와 Zenoh 통신 경로](2026-07-16-phase-4-web-dashboard-and-zenoh.md)
- Phase 5: [TB1 로컬 Nav2와 웹 목적지 구현](2026-07-17-phase-5-tb1-navigation-implementation.md)
- 범위 결정: [TB1 단일 로봇 MVP 집중](2026-07-16-single-robot-mvp-scope-decision.md)
- Phase 5 실차: [새 장소 안전 매핑](2026-07-16-phase-5-new-location-clean-mapping.md)
- Phase 5 실차: [지도 산출물 검증](2026-07-16-phase-5-map-artifact-validation.md)
- Phase 5 실차: [Nav2 사전 점검](2026-07-16-phase-5-navigation-preflight.md)
- Phase 5 실차: [SLAM과 Zenoh 안전 검증](2026-07-16-phase-5-slam-and-zenoh-safety-validation.md)
- Phase 5 웹: [Nav2 Action 수명주기](2026-07-16-phase-5-web-nav2-action-lifecycle.md)
- Phase 5 안전: [잔류 teleop 명령 사고](2026-07-16-tb1-residual-teleop-command-incident.md)
- 인수인계: [로봇 없는 개발 환경과 후속 작업](2026-07-16-weekend-robotless-handoff.md)
- Phase 6: [TB1 로봇 없는 작업·고장·감사 기능](2026-07-18-tb1-robotless-operations.md)
- 환경: [현재 관제 PC 기준선 재조사](2026-07-18-current-pc-baseline.md)
- 환경: [현재 PC TB1 관제 준비 완료](2026-07-18-control-pc-readiness.md)
- Phase 5 실차: [TB1 acceptance 배포와 정지 상태 사전검증](2026-07-18-tb1-acceptance-deployment.md)
- Phase 5 실차: [TB1 로컬 Nav2 실차 수용 시험 완료](2026-07-19-phase-5-tb1-navigation-acceptance.md)
- Phase 6 실차: [TB1 작업·복구 실차 수용 시험 완료](2026-07-19-phase-6-tb1-operations-acceptance.md)
- 관제 UX: [한 화면 관제와 heartbeat 단절 감사 로그](2026-07-19-single-screen-dashboard-connectivity-audit.md)
- Phase 7: [ROS 2 로그 MLOps와 정밀 지도 뷰포트](2026-07-19-phase-7-ros2-log-mlops-and-map-viewport.md)

## 공부와 면접용 문서

- [공부 문서 운영 방식](../study/README.md)
- [Phase 1 필수 개념과 모범 답변](../study/phase-1-tb1-bringup.md)
- [Phase 2 안전 제어 필수 개념과 모범 답변](../study/phase-2-safe-teleoperation.md)
- [Phase 3 Robot Agent 필수 개념과 모범 답변](../study/phase-3-robot-agent.md)
- [Phase 4 웹 Fleet Gateway 필수 개념과 모범 답변](../study/phase-4-web-fleet-gateway.md)
- [Phase 5 로컬 Nav2와 lease 안전 필수 개념](../study/phase-5-tb1-navigation.md)
- [Phase 5 SLAM·지도 산출물·Nav2 실차 개념](../study/phase-5-slam-nav2.md)
- [관제 PC WSL2·ROS 2 지속 실행과 검증 계층](../study/control-pc-wsl-ros2-readiness.md)
- [LDS-02 `/scan` 데이터 복구 사례](../case-studies/lds02-scan-data-recovery.md)
- [비상정지 중립 재무장 설계 사례](../case-studies/safety-watchdog-neutral-rearm.md)
- [Robot Agent stale 감지·복구 사례](../case-studies/robot-agent-stale-recovery.md)
- [Zenoh 서비스 시간 초과와 RMW 혼용 사례](../case-studies/zenoh-service-timeout-rmw-mismatch.md)
- [SLAM Toolbox 가변 스캔 정규화 사례](../case-studies/slam-toolbox-variable-scan-normalization.md)
- [Phase 3 Robot Agent 설계](../design/phase-3-robot-agent.md)
- [Phase 4 Fleet Gateway 설계](../design/phase-4-tb1-web-dashboard.md)
- [Phase 5 TB1 Nav2와 웹 목적지 설계](../design/phase-5-tb1-navigation.md)
- [Phase 6 TB1 작업·고장·감사 설계](../design/phase-6-tb1-operations.md)
- [Phase 7 ROS 2 로그 MLOps와 지도 뷰포트 설계](../design/phase-7-ros2-log-mlops.md)
- [Phase 7 ROS 2 로그 분석 MLOps 공부](../study/phase-7-ros2-log-mlops.md)

## 기록 원칙

- 실제 실행한 명령과 실제 결과만 기록한다.
- 확인하지 못한 내용은 `미확인`으로 남긴다.
- 성공 결과뿐 아니라 실패 원인과 해결 과정도 기록한다.
- 비밀번호, Wi-Fi 정보, 정확한 IP, API 키는 기록하지 않는다.
- 복습 문제 바로 아래에 정답과 이유를 함께 기록한다.
- 관련 커밋이 생기면 마지막에 커밋 해시와 메시지를 추가한다.

## 기본 형식

```markdown
# 학습 일지: 작업 이름

날짜:
단계:
진행 상태:

## 오늘의 목표

## 왜 이 작업을 했는가

## 진행한 활동

## 실행한 명령

## 실제 결과

## 배운 점 / 메모

## 발생한 문제와 해결

## 완료 체크리스트

## 복습 문제와 정답

### 1. 문제

정답:

이유:

## 다음에 할 일

## 관련 커밋
```
