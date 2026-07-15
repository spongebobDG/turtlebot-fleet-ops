# 학습 일지: Draft PR 자체 리뷰와 main Ruleset

날짜: 2026-07-15

단계: Phase 0 - GitHub 협업 환경 구성

진행 상태: Ruleset 구성과 Ready for review 전환 완료, squash merge 대기

## 오늘의 목표

Draft Pull Request를 브라우저에서 확인하고, `main`에 직접 push하거나 이력을 강제로 바꾸지 못하도록 GitHub 보호 규칙을 설정한다.

## 왜 이 작업을 했는가

작업 규칙을 문서에만 적으면 실수로 `main`에 직접 push할 수 있다. GitHub Ruleset으로 PR 필수, 강제 push 차단과 squash 병합을 기술적으로 강제하면 실제 회사와 비슷한 안전장치를 연습할 수 있다.

## 진행한 활동

1. Draft PR #1을 브라우저에서 열었다.
2. PR의 base가 `main`, head가 작업 브랜치인지 확인했다.
3. 저장소 병합 방식을 squash 전용으로 변경했다.
4. 병합된 작업 브랜치 자동 삭제를 활성화했다.
5. 기본 브랜치를 대상으로 `protect-main` Ruleset을 만들었다.
6. GitHub API로 Ruleset 대상과 세부 규칙을 다시 읽어 검증했다.

PR 화면을 연 뒤 별도 문제 보고 없이 다음 단계로 진행했다.

## 실행한 명령

```powershell
gh pr view 1 --web

gh api repos/spongebobDG/turtlebot-fleet-ops `
  --jq '{allow_squash_merge,allow_merge_commit,allow_rebase_merge,delete_branch_on_merge}'

gh api repos/spongebobDG/turtlebot-fleet-ops/rulesets `
  --jq 'map({id,name,enforcement,target})'
```

Ruleset 상세값은 해당 Ruleset 조회 API로 검증했다.

## 실제 결과

### 저장소 병합 설정

```text
allow_squash_merge=true
allow_merge_commit=false
allow_rebase_merge=false
delete_branch_on_merge=true
```

### protect-main Ruleset

```text
name=protect-main
target=branch
target branch=default branch (main)
enforcement=active
bypass actors=none
restrict deletions=enabled
block force pushes=enabled
require linear history=enabled
require pull request=enabled
required approvals=0
resolve review conversations=required
allowed merge methods=squash
required status checks=disabled
```

## 선택한 이유

- `main`은 PR을 거쳐야 변경되도록 했다.
- 혼자 작업하므로 필수 승인은 0명으로 설정했다. 작성자는 자신의 PR 승인 요건을 채울 수 없기 때문이다.
- squash만 허용해 작업 브랜치의 세부 커밋을 `main`에서 하나의 목적 단위로 보이게 했다.
- force push와 삭제를 막아 공유 기준 브랜치의 이력을 보호했다.
- CI가 아직 없으므로 존재하지 않는 status check를 요구하지 않았다.
- 우회 권한을 두지 않아 저장소 관리자도 같은 작업 흐름을 따르게 했다.

## 발생한 문제와 해결

설정 과정에서 오류는 발생하지 않았다. GitHub 화면에서 저장한 뒤 API를 다시 조회해 UI에서 선택한 값이 실제 규칙으로 반영됐는지 검증했다.

## 완료 체크리스트

- [x] Draft PR 브라우저 열기
- [x] squash merge만 허용
- [x] merge/rebase merge 비활성화
- [x] 병합 후 작업 브랜치 자동 삭제
- [x] 기본 브랜치 대상 Ruleset 활성화
- [x] PR 필수 설정
- [x] 강제 push와 삭제 차단
- [x] 선형 이력과 대화 해결 필수 설정
- [x] API로 실제 적용값 검증
- [x] 기록 커밋을 Draft PR에 push
- [x] Ready for review 전환
- [ ] squash merge

## 복습 문제와 정답

### 1. 작업 규칙을 문서로만 관리하지 않고 Ruleset도 사용하는 이유는 무엇인가?

정답: 문서는 사람이 참고하는 규칙이지만 Ruleset은 GitHub가 위반 작업을 기술적으로 차단하기 때문이다.

이유: 실수나 절차 누락이 있어도 `main` 직접 변경과 강제 push 같은 위험한 작업을 서버에서 막을 수 있다.

### 2. 필수 승인 수를 0명으로 둔 이유는 무엇인가?

정답: 현재는 1인 저장소여서 PR 작성자 외에 승인할 사람이 없기 때문이다.

이유: PR 자체는 반드시 만들게 하면서도 존재하지 않는 다른 사람의 승인을 기다려 병합이 영구히 막히는 상황을 피한다. 팀원이 생기면 1명 이상으로 높인다.

### 3. squash merge의 장점은 무엇인가?

정답: 작업 브랜치의 여러 중간 커밋을 `main`에 하나의 목적 단위 커밋으로 반영한다.

이유: `main` 이력이 간결해지고 특정 기능이나 작업 전체를 되돌리기 쉬워진다.

### 4. `Require linear history`는 무엇을 막는가?

정답: 대상 브랜치에 merge commit이 생기는 것을 막는다.

이유: 분기와 병합선이 복잡하게 얽히지 않는 일직선 형태의 이력을 유지한다.

### 5. 지금 required status checks를 켜지 않은 이유는 무엇인가?

정답: 아직 GitHub Actions 등으로 실행되는 CI check가 없기 때문이다.

이유: 존재하지 않는 check를 요구하면 PR을 정상적으로 병합할 수 없다. CI 추가 후 실제 check 이름을 등록한다.

### 6. 작업 브랜치 자동 삭제가 안전한 이유는 무엇인가?

정답: 병합된 변경 내용과 검토 기록은 `main` 커밋과 Pull Request에 남기 때문이다.

이유: 완료된 단기 브랜치를 제거하면 활성 작업 브랜치만 남아 목록이 명확해진다.

## 다음에 할 일

PR #1의 전체 변경을 최종 확인하고 Ready for review로 전환했다. GitHub에서 `MERGEABLE`, `CLEAN` 상태를 확인했으므로 다음으로 squash merge한다.

## 관련 Pull Request

- [PR #1: docs: prepare Phase 0 development environment](https://github.com/spongebobDG/turtlebot-fleet-ops/pull/1)

## 관련 커밋

- `a2c30fa docs: record main branch protection`
