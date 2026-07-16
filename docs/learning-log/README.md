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

## 공부와 면접용 문서

- [공부 문서 운영 방식](../study/README.md)
- [Phase 1 필수 개념과 모범 답변](../study/phase-1-tb1-bringup.md)
- [Phase 2 안전 제어 필수 개념과 모범 답변](../study/phase-2-safe-teleoperation.md)
- [Phase 3 Robot Agent 필수 개념과 모범 답변](../study/phase-3-robot-agent.md)
- [LDS-02 `/scan` 데이터 복구 사례](../case-studies/lds02-scan-data-recovery.md)
- [비상정지 중립 재무장 설계 사례](../case-studies/safety-watchdog-neutral-rearm.md)
- [Robot Agent stale 감지·복구 사례](../case-studies/robot-agent-stale-recovery.md)
- [Phase 3 Robot Agent 설계](../design/phase-3-robot-agent.md)

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
