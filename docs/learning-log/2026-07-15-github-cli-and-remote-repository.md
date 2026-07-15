# 학습 일지: GitHub CLI 인증과 원격 저장소 연결

날짜: 2026-07-15

단계: Phase 0 - GitHub 협업 환경 구성

진행 상태: 진행 중

## 오늘의 목표

로컬 Git 저장소를 GitHub Public 저장소와 연결하고, 작업 브랜치를 Draft Pull Request로 검토할 준비를 한다.

## 왜 이 작업을 했는가

로컬 커밋만으로는 변경 내용을 다른 환경에 백업하거나 Pull Request로 비교·검토할 수 없다. 회사식 작업 흐름을 연습하기 위해 `main`과 작업 브랜치를 GitHub에 게시하고, 작업 중인 변경은 Draft PR로 관리한다.

## 진행한 활동

1. Windows에 GitHub CLI를 설치했다.
2. GitHub 계정을 브라우저 방식으로 인증했다.
3. Git 작업 프로토콜을 HTTPS로 설정했다.
4. 같은 이름의 원격 저장소가 없는 것을 확인했다.
5. 전체 작업 트리와 Git 이력에서 민감정보 패턴을 검사했다.
6. GitHub에 Public 저장소를 생성했다.
7. 로컬 저장소에 `origin` 원격을 연결했다.
8. 반복 가능한 자체 검토를 위해 Pull Request 템플릿을 추가했다.

## 실행한 명령

```powershell
winget install --id GitHub.cli -e
gh --version
gh auth login
gh auth status

cd C:\project\turtlebot-fleet-ops

gh repo create spongebobDG/turtlebot-fleet-ops `
  --public `
  --source=. `
  --remote=origin

git remote -v

gh repo view spongebobDG/turtlebot-fleet-ops `
  --json nameWithOwner,visibility,url
```

인증 결과에 포함되는 토큰 값은 문서에 기록하지 않았다.

## 실제 결과

```text
GitHub CLI=2.96.0
GitHub account=spongebobDG
Git protocol=https
Repository=spongebobDG/turtlebot-fleet-ops
Visibility=PUBLIC
Remote name=origin
Fetch/Push URL=https://github.com/spongebobDG/turtlebot-fleet-ops.git
Working branch=chore/phase-0-dev-environment
Working tree=clean (문서 작성 전)
```

저장소 주소: <https://github.com/spongebobDG/turtlebot-fleet-ops>

원격 저장소는 생성됐지만 아직 `main`과 작업 브랜치를 push하지 않았다. 따라서 Pull Request도 아직 만들지 않았다.

## 민감정보 검사

현재 파일과 전체 Git 이력에서 다음 패턴을 검사했다.

- 로봇의 정확한 사설 IP
- GitHub 토큰 형식
- password, secret, token 등의 값 할당 형태

검사 결과 일치 항목은 없었다. Git 커밋의 작성자 이름과 이메일은 정상적인 커밋 메타데이터이므로 검사 대상 비밀정보가 아니다.

## 배운 점 / 메모

- Git은 로컬 버전 관리 도구이고 GitHub는 원격 저장소와 PR 검토 기능을 제공하는 서비스다.
- `origin`은 원격 저장소 URL 자체가 아니라 그 URL에 붙인 관례적인 별칭이다.
- Public 저장소를 만들기 전에는 현재 파일뿐 아니라 과거 커밋 이력도 검사해야 한다.
- GitHub CLI 인증 결과에 토큰이 가려져 보이더라도 학습 일지에는 토큰 값을 복사하지 않는다.
- 원격 저장소를 생성하는 것과 로컬 브랜치를 push하는 것은 별개의 작업이다.
- PR 템플릿은 변경 이유, 검증 결과와 미확인 항목을 팀의 공통 형식으로 남기게 한다.

## 발생한 문제와 해결

GitHub CLI 설치 직후 기존 Codex 프로세스는 갱신 전 PATH를 사용해 `gh`를 찾지 못했다. 새 PowerShell에서는 `gh`가 정상 실행됐으므로 사용자 환경의 설치 문제는 아니었다. 기존 프로세스에서는 설치된 실행 파일의 절대 경로를 사용해 읽기 전용 검사를 계속했다.

짧은 원인 요약: 설치 후 이미 실행 중이던 프로세스에는 변경된 PATH가 자동 반영되지 않을 수 있다.

## 완료 체크리스트

- [x] GitHub CLI 설치
- [x] GitHub 계정 인증
- [x] HTTPS Git 프로토콜 설정
- [x] 공개 전 민감정보 검사
- [x] GitHub Public 저장소 생성
- [x] `origin` 원격 연결
- [ ] `main` 원격 게시
- [ ] 작업 브랜치 원격 게시
- [ ] Draft Pull Request 생성

## 복습 문제와 정답

### 1. Git과 GitHub는 같은 도구인가?

정답: 아니다. Git은 로컬에서 커밋과 브랜치를 관리하는 분산 버전 관리 도구이고, GitHub는 Git 저장소 호스팅과 Pull Request 등의 협업 기능을 제공한다.

이유: 인터넷이나 GitHub가 없어도 로컬 Git 커밋은 만들 수 있지만 원격 공유와 GitHub PR은 사용할 수 없다.

### 2. `origin`은 무엇인가?

정답: 로컬 Git 저장소에 등록한 원격 저장소의 관례적인 별칭이다.

이유: 긴 원격 URL 대신 `git push origin main`처럼 짧고 일관된 이름을 사용할 수 있다.

### 3. 저장소 생성 후에도 `git push`가 필요한 이유는 무엇인가?

정답: GitHub 저장소 생성은 원격 공간만 만들며 로컬 커밋과 브랜치를 자동으로 전송하지 않기 때문이다.

이유: 로컬 객체와 원격 객체는 push나 fetch 같은 명시적인 동기화 작업으로 교환된다.

### 4. Public 저장소를 만들기 전에 Git 이력까지 검사하는 이유는 무엇인가?

정답: 현재 파일에서 삭제한 비밀정보도 과거 커밋에는 남아 있을 수 있기 때문이다.

이유: Public 저장소에 push하면 접근 가능한 커밋 이력도 함께 공개된다.

### 5. `git push -u origin <branch>`의 `-u`는 무엇을 하는가?

정답: 현재 로컬 브랜치가 이후 기본적으로 push하고 pull할 원격 추적 브랜치를 설정한다.

이유: 최초 연결 후에는 원격과 브랜치 이름을 매번 입력하지 않고 `git push`를 사용할 수 있다.

## 다음에 할 일

문서 변경을 검토하고 커밋한 뒤 `main`과 `chore/phase-0-dev-environment`를 원격에 push한다. 이후 작업 브랜치에서 `main`을 대상으로 Draft Pull Request를 만든다.

## 관련 커밋

문서 검토와 커밋 후 기록한다.
