# 학습 일지: Docker Desktop과 WSL2 통합

날짜: 2026-07-15

단계: Phase 0 - 관제 개발환경 구성

진행 상태: 완료

## 오늘의 목표

Windows에 Docker Desktop을 설치하고 `Ubuntu-22.04` WSL2에서 Linux 컨테이너를 `sudo` 없이 실행한다.

## 왜 이 작업을 했는가

향후 FastAPI, 데이터베이스와 관측 도구를 동일한 실행환경으로 재현하려면 컨테이너 실행환경이 필요하다. 초기에는 개별 서비스를 이해하고 구현한 뒤 Docker Compose로 묶는다.

## 선택한 방향

- Docker Desktop per-user 설치
- WSL2 Linux 컨테이너 백엔드
- `Ubuntu-22.04` WSL Integration만 활성화
- WSL 내부 Docker Engine 중복 설치 금지
- 개발환경은 Docker Desktop, 실제 Ubuntu 배포 서버는 Docker Engine 사용

## 진행할 활동

1. `Ubuntu-22.04`를 기본 WSL 배포판으로 지정한다.
2. 공식 설치 파일을 내려받는다.
3. per-user, WSL2, Linux 컨테이너 전용으로 설치한다.
4. `Ubuntu-22.04` WSL Integration을 활성화한다.
5. Windows에서 client/server 정보를 확인한다.
6. WSL에서 `hello-world`와 Alpine 컨테이너를 실행한다.

## 실제 결과

Windows PowerShell에서 다음 결과를 확인했다.

```text
Docker Desktop=4.82.0
Docker Client=29.6.1
Docker Engine=29.6.1
context=desktop-linux
server OS/Arch=linux/amd64
OperatingSystem=Docker Desktop
```

Client와 Server 정보가 모두 표시되므로 Windows Docker CLI와 Linux Docker Engine은 정상이다.

`Ubuntu-22.04` WSL에서는 다음 Windows 경로의 CLI를 발견했지만 실행에 실패했다.

```text
/mnt/c/Program Files/Docker/Docker/resources/bin/docker
The command 'docker' could not be found in this WSL 2 distro.
We recommend to activate the WSL integration in Docker Desktop settings.
```

문제 해결 후 WSL에서 다음 결과를 확인했다.

```text
Docker Client=29.6.1 linux/amd64
Docker Engine=29.6.1 linux/amd64
Docker Desktop=4.82.0
context=default
hello-world=성공
alpine:3.20=성공
docker ps -a=빈 목록
```

## 발생한 문제와 해결

### Ubuntu-22.04 Docker 실행 실패

처음에는 통합 설정 문제처럼 보였지만 Docker Desktop 설정에는 `Ubuntu-22.04`가 정확히 등록돼 있었다. 백엔드 로그에서 WSL 통합 프록시의 `Exec format error`를 확인했다.

직접 확인한 근본 원인:

```text
/mnt/wsl/docker-desktop/docker-desktop-user-distro: 0 bytes
/run/docker-desktop/docker-desktop-user-distro: 0 bytes
```

Docker Desktop이 WSL에 제공해야 할 통합 실행 파일이 비어 있었기 때문에 CLI와 Docker 소켓을 구성하는 프록시가 실행되지 않았다.

해결 과정:

1. Docker Desktop 설정 파일에서 `Ubuntu-22.04` 통합이 활성화된 것을 확인했다.
2. Docker Desktop과 모든 WSL 인스턴스를 완전히 종료했다.
3. Docker Desktop을 다시 시작해 통합 바이너리를 약 23 MB 크기로 재생성했다.
4. Docker 소켓 생성 후 WSL에서 Client/Server 연결을 확인했다.
5. `hello-world`, Alpine 컨테이너와 종료 후 잔여 컨테이너가 없음을 확인했다.

짧은 원인 요약: 설정은 맞았지만 Docker Desktop의 WSL 통합 파일이 손상됐고, 콜드 재시작으로 복구했다.

## 완료 체크리스트

- [x] `Ubuntu-22.04` 기본 WSL 지정
- [x] Docker Desktop 설치
- [x] WSL2 백엔드 활성화
- [x] `Ubuntu-22.04` 통합 활성화
- [x] Windows Docker 검증
- [x] WSL Docker 검증
- [x] `hello-world` 실행
- [x] Alpine 임시 컨테이너 실행

## 복습 문제와 정답

### 1. 왜 WSL 내부에 Docker Engine을 따로 설치하지 않는가?

정답: Docker Desktop의 WSL2 백엔드와 별도 Engine이 동시에 존재하면 Docker CLI가 어느 daemon에 연결되는지 혼란과 충돌이 생길 수 있기 때문이다.

이유: 개발 PC에서는 Docker Desktop 하나가 엔진과 WSL 통합을 관리하도록 구성한다.

### 2. Docker image와 container는 어떻게 다른가?

정답: image는 실행환경을 담은 읽기 전용 설계도이고, container는 그 image로 만든 실행 인스턴스다.

이유: 같은 image에서 여러 container를 만들 수 있으며 각각 별도의 실행 상태를 가진다.

### 3. `docker run --rm hello-world`의 `--rm`은 무엇인가?

정답: 컨테이너 프로세스가 종료되면 해당 컨테이너 인스턴스를 자동 삭제한다.

이유: 일회성 검증 컨테이너가 목록과 저장공간에 계속 쌓이는 것을 방지한다.

### 4. Windows와 WSL에서 `docker version`의 Server 정보가 모두 표시되어야 하는 이유는 무엇인가?

정답: Docker CLI뿐 아니라 실제 Docker daemon에도 연결됐는지 확인하기 위해서다.

이유: Client 정보만 보이면 명령 프로그램은 있지만 컨테이너를 실행할 서버가 동작하지 않는 상태일 수 있다.

### 5. 개발 PC와 실제 Linux 배포 서버의 Docker 구성이 다른 이유는 무엇인가?

정답: Windows 개발 PC는 WSL 통합과 GUI 관리가 필요하지만 Linux 서버는 Docker Engine을 직접 서비스로 실행하는 것이 일반적이기 때문이다.

이유: 환경별 운영 방식은 다르지만 Dockerfile과 Compose 정의를 공유해 애플리케이션 실행환경을 재현할 수 있다.

## 다음에 할 일

환경 문서를 검토하고 커밋한 뒤 원격 GitHub 저장소 연결과 Draft Pull Request 흐름을 설정한다.

## 관련 커밋

Docker 설치와 검증이 끝난 후 기록한다.
