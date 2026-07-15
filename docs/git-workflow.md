# Git 작업 흐름

이 프로젝트는 한 명이 개발하더라도 회사의 리뷰·검증 흐름을 연습하기 위해 GitHub Flow를 사용한다.

## 브랜치 역할

### `main`

- 현재 시점에서 검증되고 통합 가능한 상태를 보관한다.
- 프로젝트 전체가 최종 완성된 뒤에만 사용하는 브랜치가 아니다.
- 작업 파일을 직접 수정하거나 바로 커밋하지 않는다.
- 작업 브랜치의 Pull Request를 통해서만 변경을 반영한다.

### 작업 브랜치

- `main`에서 생성한다.
- 하나의 작은 목표만 다룬다.
- 작업이 끝나면 Pull Request로 검토한 후 `main`에 병합한다.
- 병합이 끝난 브랜치는 삭제한다.

## 브랜치 이름

| 접두어 | 용도 | 예시 |
| --- | --- | --- |
| `feat/` | 새로운 기능 | `feat/phase-1-tb1-bringup` |
| `fix/` | 버그 수정 | `fix/tb1-lidar-timeout` |
| `docs/` | 문서만 변경 | `docs/phase-1-runbook` |
| `test/` | 테스트 추가 | `test/tb1-bringup-failure` |
| `refactor/` | 동작을 바꾸지 않는 구조 개선 | `refactor/robot-config-loader` |
| `chore/` | 환경 조사와 저장소 관리 | `chore/phase-0-wsl-audit` |
| `spike/` | 폐기할 수 있는 짧은 기술 검증 | `spike/wsl-dds-discovery` |

## 표준 작업 순서

```text
작은 작업 정의
→ main 최신 상태 확인
→ 작업 브랜치 생성
→ 구현 또는 조사
→ 직접 검증
→ 학습 일지 기록
→ 변경 내용 검토
→ 작은 단위 커밋
→ 원격 브랜치 push
→ Draft Pull Request
→ 자체 리뷰와 테스트
→ Ready for review
→ Squash merge
→ 작업 브랜치 삭제
```

## 작업 시작 명령

```bash
git switch main
git status
git pull --ff-only
git switch -c <type>/<short-description>
git branch --show-current
```

원격 저장소가 연결되기 전에는 `git pull --ff-only`을 실행하지 않는다.

## 커밋 전 확인

```bash
git status
git diff
git diff --check
```

검토가 끝난 파일만 명시적으로 스테이징한다.

```bash
git add <file1> <file2>
git diff --cached
git commit -m "<type>: <summary>"
```

`git add .`은 의도하지 않은 로그, 비밀정보 또는 생성물을 포함할 수 있으므로 초반에는 사용하지 않는다.

## 커밋 메시지

```text
feat: add tb1 status publisher
fix: stop robot when command times out
docs: update WSL environment inventory
test: cover task state transitions
chore: configure repository workflow
```

- 제목은 한 커밋이 만든 결과를 설명한다.
- 서로 다른 목적의 변경은 별도 커밋으로 나눈다.
- 테스트하지 않은 기능을 완료됐다고 표현하지 않는다.

## Pull Request 체크리스트

- [ ] 한 가지 목표만 포함한다.
- [ ] 변경 이유와 범위를 설명했다.
- [ ] 직접 실행한 검증 명령과 결과를 기록했다.
- [ ] 오류나 미확인 항목을 숨기지 않았다.
- [ ] IP, 비밀번호, Wi-Fi 정보, API 키가 포함되지 않았다.
- [ ] 관련 학습 일지를 작성했다.
- [ ] `main`과의 차이를 직접 검토했다.

## 현재 적용 범위

- 현재 작업 브랜치: `chore/phase-0-wsl-audit`
- 현재 목표: WSL 관제 환경의 OS, ROS 2, Docker와 로봇 네트워크 상태 확인
- 원격 저장소: 아직 연결되지 않음
- 브랜치 보호와 Pull Request: 원격 저장소 연결 후 적용
