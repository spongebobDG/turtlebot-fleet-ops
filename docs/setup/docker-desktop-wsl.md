# Docker Desktop WSL2 설치 런북

대상: Windows 관제 PC와 `Ubuntu-22.04` WSL2

설치 방식: Docker Desktop Windows per-user 설치와 WSL2 통합

상태: 완료

## 결정

- Windows에는 Docker Desktop을 per-user 방식으로 설치한다.
- 컨테이너 백엔드는 WSL2를 사용한다.
- Linux 컨테이너만 사용하고 Windows 컨테이너 기능은 사용하지 않는다.
- Docker Desktop의 WSL Integration은 `Ubuntu-22.04`에만 활성화한다.
- WSL 내부에 `docker.io` 또는 Docker Engine을 별도로 설치하지 않는다.
- Docker 명령을 `sudo` 없이 실행한다.

이 구성은 Windows GUI와 업데이트 관리, WSL의 Linux 개발환경과 Docker 엔진을 연결한다. 실제 배포 서버에서는 Docker Desktop이 아니라 Linux Docker Engine을 사용한다.

## 현재 확인 결과

2026-07-15에 Windows Docker Desktop 설치와 엔진 실행은 성공했다.

| 항목 | 결과 |
| --- | --- |
| Docker Desktop | `4.82.0` |
| Docker Client/Engine | `29.6.1` |
| Windows context | `desktop-linux` |
| Server OS/Arch | `linux/amd64` |
| Windows Engine | 정상 |
| `Ubuntu-22.04` WSL | 통합 복구 및 실행 성공 |
| WSL Docker Client/Engine | `29.6.1` / `29.6.1` |
| WSL context | `default` |
| `hello-world` | 성공 |
| `alpine:3.20` | 성공 |
| 테스트 후 컨테이너 | 없음 |

초기에는 WSL의 `command -v docker`가 Windows에 설치된 Docker CLI만 찾았고 실행에 실패했다. Docker Desktop 설정은 올바르게 `Ubuntu-22.04`를 지정하고 있었지만, WSL에 제공된 `docker-desktop-user-distro` 통합 바이너리가 0바이트여서 `Exec format error`가 발생했다.

Docker Desktop을 완전히 중지하고 WSL을 종료한 뒤 다시 시작해 통합 바이너리를 정상 크기로 재생성했다. 이후 `/usr/bin/docker`, `/var/run/docker.sock`, Client/Server 연결, `hello-world`와 Alpine 컨테이너 실행을 확인했다.

## 1. Ubuntu-22.04를 기본 WSL로 지정

PowerShell에서 실행한다.

```powershell
wsl.exe --set-default Ubuntu-22.04
wsl.exe -l -v
```

목록에서 `Ubuntu-22.04` 왼쪽에 `*`가 표시되는지 확인한다.

## 2. 공식 설치 파일 다운로드

[Docker Desktop Windows 공식 설치 페이지](https://docs.docker.com/desktop/setup/install/windows-install/)에서 WSL2 x86_64 설치 파일을 다운로드한다.

기본 다운로드 경로와 파일명은 다음과 같다.

```text
C:\Users\<사용자명>\Downloads\Docker Desktop Installer.exe
```

## 3. Per-user 설치

PowerShell에서 실제 다운로드 경로로 이동한 뒤 실행한다.

```powershell
cd $HOME\Downloads
Start-Process '.\Docker Desktop Installer.exe' -Wait -ArgumentList 'install', '--user', '--backend=wsl-2', '--no-windows-containers'
```

per-user 설치는 현재 사용자 영역에 설치하며 Linux 컨테이너용 WSL2 백엔드만 사용한다.

## 4. Docker Desktop 시작과 설정

Windows 시작 메뉴에서 Docker Desktop을 실행한다. 최초 약관과 안내를 확인한 뒤 다음 값을 설정한다.

```text
Settings
├── General
│   └── Use the WSL 2 based engine: ON
└── Resources
    └── WSL Integration
        ├── Ubuntu-22.04: ON
        └── Ubuntu: OFF
```

설정을 변경했다면 `Apply & restart`를 누르고 Docker Desktop이 `Engine running` 상태가 될 때까지 기다린다.

## 5. Windows PowerShell 검증

새 PowerShell 창에서 실행한다.

```powershell
docker version
docker context show
docker info --format '{{.OperatingSystem}}'
```

클라이언트와 서버 정보가 모두 표시되고 context는 일반적으로 `desktop-linux`, 운영체제는 `Docker Desktop`으로 표시된다.

## 6. Ubuntu-22.04 WSL 검증

```powershell
wsl.exe -d Ubuntu-22.04
```

WSL에서 실행한다.

```bash
command -v docker
docker version
docker context show
docker run --rm hello-world
```

`hello-world` 출력에 `Hello from Docker!`가 표시되면 이미지 다운로드, 컨테이너 생성, 실행과 출력까지 성공한 것이다.

## 7. Linux 컨테이너 추가 검증

```bash
docker run --rm alpine:3.20 uname -a
docker ps -a
```

Alpine Linux 커널 정보가 출력되고 종료된 임시 컨테이너가 남지 않아야 한다.

## 완료 기준

- [x] `Ubuntu-22.04`가 기본 WSL 배포판이다.
- [x] Docker Desktop이 WSL2 백엔드로 실행된다.
- [x] `Ubuntu-22.04` WSL Integration이 활성화된다.
- [x] 일반 `Ubuntu` WSL Integration은 비활성화된다.
- [x] Windows PowerShell에서 Docker client/server가 확인된다.
- [x] WSL에서 `sudo` 없이 Docker 명령을 실행한다.
- [x] `hello-world` 컨테이너가 성공한다.
- [x] Alpine 임시 컨테이너가 성공하고 종료 후 남지 않는다.

## 오류 처리 원칙

- WSL에서 `docker: command not found`가 나오면 WSL 내부에 Docker를 설치하지 않고 Docker Desktop의 WSL Integration 설정을 확인한다.
- `Cannot connect to the Docker daemon`이면 Docker Desktop이 `Engine running` 상태인지 확인한다.
- Docker가 `sudo`에서만 실행되면 의도한 Docker Desktop 통합이 아니므로 중단하고 현재 설치 상태를 확인한다.
- Windows 컨테이너 모드로 전환하지 않는다.

## 공식 참고 자료

- [Docker Desktop Windows 설치](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Docker Desktop WSL2 백엔드](https://docs.docker.com/desktop/features/wsl/)
- [Docker Desktop WSL 개발](https://docs.docker.com/desktop/features/wsl/use-wsl/)
