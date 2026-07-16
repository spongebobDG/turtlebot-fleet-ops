# 학습 일지: 새 PC 주말 무로봇 개발 인수인계

날짜: 2026-07-16
단계: 개발환경 재현과 인수인계
진행 상태: 자동화·mock·런북 구현과 기존 WSL 검증 완료, 새 PC bootstrap 실행 대기

## 목표

로봇이 없는 새 PC에서도 GitHub의 같은 브랜치에서 전체 빌드·테스트와 웹 상태·e-stop·Nav2
수명주기 개발을 이어갈 수 있게 한다.

## 구현한 것

- Ubuntu 22.04·ROS 2 Humble 설치와 rosdep 의존성 자동화
- 5개 workspace 패키지 전체 빌드·테스트 스크립트
- TB1 상태, e-stop heartbeat·서비스와 NavigateToPose를 제공하는 mock node
- mock과 Fleet Gateway를 동시에 실행하는 ROS launch
- GitHub·Google Drive 역할 분리와 기기 간 handoff 절차

## 실제 검증 결과

```text
Bash syntax: PASS
workspace build: 5 packages
workspace tests: 178 tests, 0 errors, 0 failures, 0 skipped
mock health: online_robots=1
mock e-stop release: PASS
mock NavigateToPose x=1.0: SUCCEEDED
mock final e-stop: true
smoke marker: WEEKEND_MOCK_SMOKE_OK status=SUCCEEDED final_estop=true
```

현재 WSL에는 ROS 2가 이미 설치돼 있어 bootstrap의 apt 설치를 반복 실행하지 않았다. 세 설치
스크립트의 Bash 문법과 설치 이후 전체 경로는 검증했으며, 완전히 새 Ubuntu 22.04에서의 첫
bootstrap 결과는 새 PC에서 기록한다.

## 오늘 꼭 기억해야 할 것

1. **코드의 기준 저장소는 GitHub이고 Google Drive는 큰 산출물 보조 저장소다.**
2. **Drive 동기화 폴더에서 Git working tree를 직접 운영하지 않는다.**
3. **mock 통과는 API·상태 머신 증거이며 모터·센서·네트워크 실차 증거가 아니다.**
4. **기기를 바꾸기 전 commit·push·clean working tree를 확인한다.**
5. **재현 가능한 환경은 설치 기억이 아니라 실행 가능한 script와 CI로 만든다.**

## 면접에서는 이렇게 설명한다

> 하드웨어가 없는 기간에도 개발이 멈추지 않도록 ROS 2 상태·e-stop·Nav2 Action 계약을
> 제공하는 mock TB1을 만들었습니다. 새 PC는 Ubuntu 22.04 WSL에서 bootstrap과 전체 검증
> 스크립트로 동일 환경을 재현하고, 웹과 상태 머신은 mock 통합 테스트로 개발합니다. 다만
> mock 결과와 실차 acceptance를 문서에서 분리해 하드웨어 안전을 과장하지 않았습니다.

## 복습 문제와 정답

### 1. Git 저장소를 Google Drive 폴더 안에 두면 왜 위험한가?

정답: Drive의 비동기 동기화와 파일 잠금이 Git의 원자적 rename, 실행 권한, 줄바꿈과 동시에
작동해 충돌이나 오염을 만들 수 있다. local working tree와 artifact backup을 분리해야 한다.

### 2. mock으로 검증할 수 있는 것과 없는 것은 무엇인가?

정답: REST·WebSocket·ROS 메시지·Action 상태 전이와 UI는 검증할 수 있다. 실제 DDS/Wi-Fi
지연, LiDAR, OpenCR, 모터, 미끄러짐, 충돌 여유와 비상정지 물리는 검증할 수 없다.

### 3. 새 PC에서 첫 코드 수정 전에 무엇을 확인해야 하는가?

정답: 올바른 branch와 최신 remote commit, clean working tree, Humble 환경, 전체 baseline
테스트 통과를 확인한다. baseline이 실패하면 새 변경과 환경 문제를 구분할 수 없다.

## 다음 작업

새 PC에서 bootstrap·전체 검증·mock 대시보드 실행 결과를 기록한 뒤 TB1 로그·장애·단일 로봇
작업 수명주기 구현을 시작한다.
