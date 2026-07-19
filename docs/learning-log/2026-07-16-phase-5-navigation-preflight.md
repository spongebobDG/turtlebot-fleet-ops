# 학습 일지: Phase 5 TB1 Nav2 환경과 안전 경계 준비

날짜: 2026-07-16
단계: Phase 5A
진행 상태: 패키지 설치·무이동 사전 점검·설정 구현 완료, 실차 매핑 대기

## 오늘의 목표

- WSL 방화벽과 통신 설정을 최종 확인한다.
- TB1의 SLAM·Nav2 실행 전 센서, TF와 자원을 확인한다.
- TB1에 누락된 Humble 패키지를 설치한다.
- Nav2 속도가 기존 Safety Watchdog를 우회하지 않는 설정 패키지를 만든다.
- 실제 결과와 필수 개념을 운영·공부 문서에 남긴다.

## 진행한 활동

### Hyper-V 방화벽 확인

`Get-NetFirewallHyperVVMSetting` 결과 `DefaultInboundAction=Allow`를 확인했다. 전용
`WSL-ROS2-DDS-Domain42` 규칙 생성 시 “파일이 이미 있음”이 나온 것은 동일 규칙이 이미
존재하기 때문이었다. 기본 인바운드도 허용 상태라 중복 규칙을 만들지 않고 종료했다.

### TB1 무이동 사전 점검

- `tb1-bringup`, `tb1-safety-watchdog`, `tb1-robot-agent`, `tb1-zenoh-bridge`: 모두 active
- `/scan`: 메시지 수신, `frame_id=base_scan`, `scan_time=0.0997506초`
- `/odom`: 메시지 수신, `frame_id=odom`, `child_frame_id=base_footprint`
- `odom -> base_footprint`: TF 출력 확인
- `base_link -> base_scan`: 고정 TF 출력 확인
- 메모리: 3.7GiB 중 available 약 3.2GiB
- 루트 디스크: 29GiB 중 약 22GiB 여유
- 최종 `/cmd_vel`: 선속도 0, 각속도 0

초기 TF 조회의 “frame does not exist” 한 줄은 discovery 직후의 대기 메시지였고, 같은
명령에서 이어서 실제 변환이 반복 출력됐으므로 TF 단절로 판정하지 않았다.

### WSL 배포판 구분

두 WSL 배포판을 혼동하지 않도록 확인했다.

- `Ubuntu-22.04`: ROS 2 Humble, Nav2, SLAM Toolbox, 운영 systemd 서비스 존재
- `Ubuntu`: Python 3.14 계열, 현재 프로젝트 운영 배포판 아님

프로젝트 표준은 계속 `Ubuntu-22.04`로 유지한다.

### TB1 패키지 설치

TB1에는 Nav2와 SLAM Toolbox가 없었다. 다음 패키지를 apt로 설치했다.

- Navigation2와 `nav2_bringup` 1.1.20 계열
- SLAM Toolbox 2.6.10 계열
- TurtleBot3 Navigation2 2.3.6 계열
- `python3-rosdep`, rosdep 0.26.0

설치 후 Nav2 주요 패키지와 `turtlebot3_navigation2`가 모두 `/opt/ros/humble`에서
조회됐고 `dpkg --audit` 출력은 비어 있었다.

### `fleet_navigation` 구현

- SLAM Toolbox 비동기 mapping launch 작성
- Map Server, AMCL과 Nav2 non-composed navigation launch 작성
- controller 출력 → `cmd_vel_nav` → velocity smoother 구성
- smoother와 recovery behavior 출력 → `/safety/cmd_vel_in` remapping
- Nav2, smoother와 behavior 속도를 0.05 m/s, 0.3 rad/s로 제한
- Burger frame, `/scan`, costmap과 AMCL 파라미터 작성
- 지도와 pose graph 저장 규칙 작성
- 설정과 안전 토픽 계약 자동 테스트 8개 추가
- GitHub Actions의 테스트 대상에 `fleet_navigation` 추가

## 실제 검증 결과

```text
fleet_navigation build: PASS
fleet_navigation tests: 8 passed
전체 colcon test-result: 72 tests, 0 errors, 0 failures, 0 skipped
TB1 Nav2/SLAM package prefix: /opt/ros/humble
TB1 dpkg audit: no output
TB1 운영 서비스: 4개 active
TB1 /cmd_vel: linear.x=0.0, angular.z=0.0
```

두 launch 파일의 `--show-args`도 성공해 설치된 package share의 기본 config와 map 경로를
정상 해석하는 것을 확인했다.

## 발생한 문제와 해결

### 1. PowerShell에서 원격 Bash 변수 손실

SSH 한 줄 명령의 `$p`, 정규식 괄호와 따옴표가 PowerShell·Windows argument parsing을
거치며 사라져 반복문의 package 이름이 빈 값이 됐다. 로봇 패키지 문제가 아니었다.
중요 검증은 패키지 이름을 직접 지정했고, 긴 원격 스크립트는 표준입력 전달 방식으로
분리했다.

### 2. SSH 제한시간보다 apt 설치가 오래 걸림

로컬 SSH가 3분 뒤 timeout됐지만 TB1의 `apt-get`과 `dpkg`는 계속 실행 중이었다. 잠금을
삭제하거나 두 번째 apt를 실행하지 않고 다음 증거를 확인했다.

- `dpkg` 프로세스 상태가 running
- `/var/log/dpkg.log`의 package 항목이 계속 증가
- 10초 동안 `wchar`, `write_bytes` 증가
- SD카드·EXT4 I/O 오류 없음

마지막 `update-motd` 후처리까지 기다린 뒤 package prefix와 `dpkg --audit`로 완료를
확정했다.

## 배운 점 / 메모

- 패키지 관리 중 lock은 원인이 아니라 동시 변경을 막는 보호 장치다.
- 프로세스가 오래 걸릴 때 elapsed time만으로 hang을 판정하지 않고 로그와 I/O 진행을 본다.
- Nav2 기본 launch도 기존 시스템의 안전 토픽 계약과 충돌할 수 있어 diff 검토가 필요하다.
- 속도 제한 설정과 독립 watchdog는 서로 다른 책임이다.
- mapping과 localization은 `map -> odom` TF 소유권을 전환하는 운영 모드다.

## 오늘 꼭 기억해야 할 것

1. `map -> odom`은 SLAM 또는 AMCL 중 하나만 발행한다.
2. Nav2 controller·behavior의 모든 속도는 watchdog 입력을 거친다.
3. `NavigateToPose`는 Goal·feedback·result·cancel이 있는 ROS 2 Action이다.
4. `/map`이 나온다고 좋은 지도가 된 것은 아니며 loop closure와 벽 정합을 확인한다.
5. apt가 진행 중일 때 lock을 지우지 말고 프로세스, 로그와 I/O 증가를 확인한다.

## 완료 체크리스트

- [x] Hyper-V 인바운드 허용 확인
- [x] 프로젝트 WSL 배포판을 Ubuntu-22.04로 확정
- [x] TB1 센서·odom·TF·자원 무이동 점검
- [x] TB1 Nav2·SLAM Toolbox·rosdep 설치
- [x] `fleet_navigation` launch와 안전 파라미터 작성
- [x] 자동 테스트 8개와 전체 72개 테스트 통과
- [x] `/cmd_vel` 0과 기존 서비스 active 재확인
- [ ] TB1 SLAM `/map`, `map -> odom` 무이동 검증
- [ ] 안전 구역 매핑과 지도 저장
- [ ] 터미널 Nav2 Goal 실차 검증
- [ ] 웹 Goal 연동

## 복습 문제와 정답

### 1. Nav2 기본 `/cmd_vel` 출력을 그대로 사용하지 않은 이유는?

정답: 기존 시스템에서는 watchdog만 최종 `/cmd_vel`을 발행해야 하는데 Nav2가 직접
발행하면 timeout, e-stop과 중립 재무장 안전 경계를 우회할 수 있기 때문이다.

### 2. 오래 실행되는 apt를 바로 강제 종료하지 않은 이유는?

정답: `dpkg.log`와 write I/O가 계속 증가해 실제 설치가 진행 중이었고, 중간 종료는
패키지 데이터베이스를 half-configured 상태로 남길 수 있기 때문이다.

### 3. 지도 작성과 AMCL 주행을 분리하는 이유는?

정답: SLAM과 AMCL이 동시에 같은 `map -> odom` TF를 발행하지 않게 하고, 검토된 정적
지도를 운영 주행의 기준으로 사용하기 위해서다.

### 4. Nav2에 저속 설정을 했는데 watchdog도 같은 제한을 갖는 이유는?

정답: Nav2 설정은 정상 제어 품질, watchdog는 모든 입력에 대한 모터 직전의 독립 안전
상한이므로 책임이 다르다.

## 다음에 할 일

1. 브랜치를 원격에 게시하고 TB1에서 `fleet_navigation`을 빌드한다.
2. SLAM을 무이동 상태로 시작해 `/map`, `map -> odom`과 `/cmd_vel=0`을 확인한다.
3. 사용자가 로봇을 안전 구역에 배치하면 저속 수동 매핑을 진행한다.

## 관련 커밋

이 일지와 Phase 5A 코드를 같은 작업 브랜치의 작은 커밋으로 기록한다.
