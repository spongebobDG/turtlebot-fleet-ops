# 학습 일지: TB1 acceptance 배포와 정지 상태 사전검증

날짜: 2026-07-18

단계: Phase 5 실차 acceptance 사전 단계

진행 상태: TB1 배포와 정지 상태 검증 완료, 지도 작성과 실제 주행 검증 대기

## 오늘의 목표

새 관제 PC에서 TB1에 비대화식 SSH로 접속하고, 저장소의 최신 Phase 5 패키지와 운영
서비스를 배포한다. 로봇을 움직이기 전에는 fail-closed 상태, 센서 수신, 속도 명령 경로,
e-stop 해제 동작을 확인해 실제 매핑을 시작할 수 있는 기준선을 만든다.

## 연결 문제와 해결

새 공유기는 TB1에 이전 환경과 다른 DHCP 주소를 할당했다. 관제 PC가 로컬 준비 파일의
이전 주소를 계속 사용한 것이 최초 연결 실패의 원인이었다. 새 LAN 주소를 로컬 설정에만
반영한 뒤 SSH와 Zenoh 포트가 모두 연결됐다. 실제 로그인 계정은 `dg`였으며, 존재하지
않는 다른 계정으로는 비밀번호가 맞아도 인증될 수 없다.

Windows에서 `tb1.local`은 LAN의 TB1이 아닌 외부 DNS 주소로 해석돼 timeout이 발생했다.
현재 acceptance 경로는 정확한 주소를 Git에 기록하지 않고 로컬 준비 표식을 사용한다.
주소 재변경을 막기 위해 공유기 DHCP 예약을 사용하는 것이 좋다.

전용 공개 키 등록 스크립트의 여러 줄 원격 명령은 Windows OpenSSH를 거치며 인수가
분리됐다. 공개 키를 base64로 전달하는 한 줄 명령으로 바꾼 뒤 다음 표식을 확인했다.

```text
TB1_SSH_AUTH_OK
TB1_SSH_SETUP_OK
```

이후 모든 acceptance 명령은 비밀번호 입력 없이 실행할 수 있다.

## 배포 전 audit

읽기 전용 preflight에서 ROS 2 Humble, Nav2, SLAM Toolbox, UART, 저장소 아키텍처와 원격
worktree는 정상이었다. 다음 일곱 항목만 준비되지 않았다.

- `jq`, `pidstat` 제공 패키지 미설치
- bringup과 watchdog 미실행
- mapping과 navigation systemd unit 미설치

이 결과는 저장소·ROS 환경을 다시 구성할 필요 없이 의존성과 운영 unit만 배포하면 된다는
뜻이었다.

## 실제 배포 결과

배포 중에는 TB1 런타임 서비스를 먼저 정지해 움직임 경로를 fail-closed로 유지했다. 의존성
설치, 최신 커밋 fetch, robot workspace 빌드와 테스트, unit 설치를 수행했고 결과는 다음과
같았다.

```text
Summary: 217 tests, 0 errors, 0 failures, 0 skipped
TB1_ACCEPTANCE_DEPLOY_OK profile=IDLE
```

배포 후 서비스 상태:

| 서비스 | 상태 |
| --- | --- |
| TB1 bringup | active |
| safety watchdog | active |
| robot agent | active |
| robot-side Zenoh bridge | active |
| mapping profile | inactive |
| navigation profile | inactive |

저장 지도 디렉터리가 없다는 preflight 경고는 예상된 결과다. 다음 단계에서 안전 teleop으로
지도와 pose graph를 처음 생성해야 한다.

Windows PowerShell이 pipe로 보낸 셸 스크립트에 CRLF를 다시 넣어 배포 후 audit가 한 번
실패했다. 로봇에서 `tr -d '\r'`로 정규화한 다음 Bash에 전달하도록 수정했고 같은 audit와
증거 수집을 다시 실행해 통과했다. 배포 자체와 217개 테스트는 이 오류 전 이미 성공했다.

## 정지 상태의 실제 측정

증거 묶음은 Git에서 제외되는 로컬 `output/tb1-acceptance/` 아래에 저장했다. 정확한 IP와
환경별 정보는 커밋하지 않는다.

- Ubuntu 22.04 aarch64, 메모리 약 3.7 GiB, 여유 디스크 약 21 GiB
- 배터리 약 87.8%, 전압 약 12.08 V
- `/scan` 약 9.6 Hz, `/odom` 약 20 Hz, `/battery_state` 약 20 Hz
- 5초 동안 `/cmd_vel`의 선속도와 각속도는 모두 0
- `/cmd_vel` publisher는 `safety_watchdog` 하나, subscriber는 TurtleBot3 base 하나
- safety 상태는 `WAITING_NEUTRAL`, e-stop false, motion-armed false
- robot 상태는 fault 없이 센서 fresh/valid

3초의 짧은 정지 샘플에서는 전체 CPU 필드가 약 28.2%, 메모리가 약 14.2%였다. LDS 드라이버
프로세스가 약 57% CPU를 사용했지만 이 값은 짧은 순간 표본이므로 10분 주행 acceptance의
지속 경고 판정으로 사용하지 않는다.

LiDAR 최소 거리는 약 0.203 m였다. 로봇이 장애물 가까이에 있다는 뜻이므로 실제 motion은
보내지 않았다. 넓은 바닥으로 이동하고 케이블과 전원 스위치 접근을 확인한 뒤에만 매핑을
시작한다.

## 정지 상태 e-stop 전이

활성 목표와 motion 입력이 없는 상태에서 웹 API로 e-stop을 켰다가 해제했다.

```text
engage  -> ESTOP, e-stop=true, motion-armed=false
release -> WAITING_NEUTRAL, e-stop=false, motion-armed=false
```

해제 뒤 자동 재무장이나 자동 출발은 없었고 odom 속도도 0 범위에 머물렀다. 이는 정지
상태의 사전검증이며, 완료 조건인 주행 중 즉시 정지와 활성 목표·lease 제거를 대신하지
않는다.

## 배운 점

1. 같은 공유기에 연결됐다는 사실만으로 이전 주소나 `.local` 이름을 계속 쓸 수 있는 것은
   아니다. DHCP 할당과 실제 DNS 해석을 각각 확인해야 한다.
2. 계정이 틀리면 올바른 비밀번호도 인증에 실패한다. 주소, 계정, 인증 수단을 분리해
   진단해야 한다.
3. Git의 LF 규칙과 별개로 Windows PowerShell의 native-process pipe가 CRLF를 만들 수 있다.
   원격 실행 경계에서도 줄바꿈을 정규화해야 한다.
4. e-stop 해제는 운전 허가가 아니다. `WAITING_NEUTRAL`과 motion-armed false가 유지돼야
   이전 명령이 재생되지 않는다.
5. 정지 상태 smoke와 실제 주행 acceptance를 문서에서 구분해야 부분 검증을 완료로
   잘못 표시하지 않는다.

## 남은 실차 범위

- 빈 공간에서 안전 teleop 매핑과 지도·pose graph 저장
- navigation 프로필에서 웹 초기 위치, AMCL `READY`, 지도·LiDAR 정합
- 저속 목표 도달, 취소, WARN 확인, 중복 목표 거부와 실제 속도 상한
- 주행 중 e-stop과 Gateway/Zenoh lease 만료 시간
- navigation agent, Nav2, arbiter, watchdog 장애와 systemd 복구
- 10분 주행 CPU·메모리 측정과 최종 증거 정리

접속·배포·기본 센서 사전점검은 끝났으므로 남은 순수 실차 시간은 약 `2시간 35분~3시간
50분`으로 추정한다. 재시험 여유 40분을 포함하면 최대 `4시간 30분`의 시험 창을 잡는다.
모든 동적 체크리스트와 로그가 채워지기 전에는 Phase 5를 완료로 표시하지 않는다.

## Ethernet에서 Wi-Fi로 전환

시험 공간에서 Ethernet 케이블을 제거하기 위해 TB1을 2.4 GHz Wi-Fi로 전환했다. 이동
로봇은 최대 전송률보다 거리와 연결 유지가 중요하므로 5 GHz보다 2.4 GHz를 선택했다.
SSID와 정확한 무선 주소는 로컬 설정에만 보관하고, 비밀번호는 PowerShell의 숨김 입력으로
받아 pipe로 전달했다. Git, 명령 인수와 터미널 출력에는 비밀번호를 남기지 않았다.

최초 실행에서 netplan 설치와 무선 연결은 성공했지만 종료 trap이 실패했다. root 권한으로
기존 설정을 복사하면서 임시 백업 파일 소유자도 root로 바뀌었는데 일반 사용자 `rm`으로
지우려고 한 것이 원인이었다. trap의 백업 삭제를 `sudo -n rm`으로 바꾸고, 실패 실행이
남긴 정확한 임시 파일을 확인한 뒤 삭제했다. native SSH stderr가 PowerShell의 전역
`ErrorActionPreference=Stop`을 즉시 발생시키지 않도록 원격 종료 코드와 출력을 먼저
수집한 다음 명시적으로 실패시키는 방식도 적용했다.

케이블 제거 뒤 유선 carrier는 0, 무선 carrier는 1이고 기본 경로는 `wlan0`이었다. SSH와
Zenoh 포트는 통과했지만 robot heartbeat와 safety가 잠시 stale이 됐다. CycloneDDS
participant가 시작 시 선택한 유선 인터페이스를 링크 변경 뒤에도 유지한 것이 원인이었다.
mapping과 navigation 프로필이 inactive임을 확인한 다음 bringup, watchdog, robot agent,
robot-side Zenoh를 fail-closed 순서로 재시작했다.

재바인딩 뒤 Gateway는 `online=1`, heartbeat와 battery·odom·scan·safety 모두 fresh,
Wi-Fi quality 약 90%, `WAITING_NEUTRAL`, e-stop false, motion-armed false를 보고했다. 이
재시작 절차를 Wi-Fi 설정 스크립트에 포함해 다음 전환에서는 stale 상태를 자동으로
복구한다. 실제 motion 명령은 보내지 않았고 mapping과 navigation은 계속 inactive다.

## 첫 보호 이동 dry-run에서 발견한 안전 상태 계약 불일치

현장 빈 공간 확인 뒤 Zenoh와 잔류 teleop을 중지하고 e-stop 서비스를 호출했다. 서비스는
`success=True`, `Emergency stop activated`를 반환했지만 바퀴를 움직이지 않는
`supervised_motion` dry-run은 다음처럼 fail-closed됐다.

```text
SUPERVISED_MOTION_FAILED: e-stop status did not confirm active=True
```

watchdog은 Phase 5 공개 인터페이스인 `/fleet/safety_status`에 `SafetyStatus`를 2 Hz로
발행한다. 보호 이동 노드는 이전 Phase 2 실험의 `/safety/estop_active` Bool과
transient-local QoS를 계속 기다리고 있었다. 서비스로 상태를 바꿀 수는 있지만 서로 다른
토픽·메시지·QoS 때문에 결과를 확인할 수 없었던 것이다. 안전 노드가 서비스 성공만 믿지
않고 이동을 거부한 동작은 올바른 fail-closed 결과였다.

보호 이동의 기본 status 토픽과 타입을 `/fleet/safety_status`의 `SafetyStatus`로 바꾸고,
watchdog publisher와 같은 volatile reliable depth 10 QoS를 사용했다. fake watchdog
통합 테스트도 동일한 공개 메시지로 바꿨다. 격리 Humble 실행에서 navigation agent의
85개 테스트를 포함한 `183 tests, 0 errors, 0 failures, 0 skipped`를 확인했다. 수정본을
TB1에 재배포하고 dry-run을 다시 통과하기 전에는 실제 5 cm 명령을 실행하지 않는다.
