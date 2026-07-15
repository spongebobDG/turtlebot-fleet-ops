# 학습 일지: Phase 2 TB1 Safety Watchdog 배포

날짜: 2026-07-15

단계: Phase 2

진행 상태: 완료

## 오늘의 목표

관제 PC의 WSL에서 검증한 `safety_watchdog` 패키지를 TB1에 내려받아 Raspberry
Pi aarch64 환경에서도 빌드와 자동 테스트가 성공하는지 확인한다. 이 단계에서는
실제 `/cmd_vel`에 실차 명령을 보내지 않는다.

## 왜 이 작업을 하는가

WSL에서 테스트가 통과해도 TB1은 CPU 아키텍처, 설치 패키지와 실행 환경이 다르다.
따라서 실차를 움직이기 전에 실제 배포 대상에서 다음 항목을 분리해서 확인해야 한다.

1. GitHub 작업 브랜치를 정상적으로 받을 수 있는가
2. ROS 2 Python 패키지가 aarch64 환경에서 빌드되는가
3. 안전 정책 단위 테스트가 통과하는가
4. ROS 토픽과 서비스 통합 테스트가 통과하는가
5. 코드 품질 검사가 함께 통과하는가

## 진행한 행동

TB1에 공개 GitHub 저장소를 복제하고 Phase 2 작업 브랜치로 전환했다.

```bash
git clone https://github.com/spongebobDG/turtlebot-fleet-ops.git
cd ~/turtlebot-fleet-ops
git fetch origin
git switch feat/phase-2-safe-teleoperation
git pull --ff-only
```

ROS 2 Humble을 불러온 뒤 패키지를 빌드했다.

```bash
source /opt/ros/humble/setup.bash

colcon build \
  --base-paths robot \
  --packages-select safety_watchdog \
  --symlink-install
```

실제 로봇 도메인 42와 분리된 142에서 전체 테스트를 실행했다.

```bash
source install/setup.bash

ROS_DOMAIN_ID=142 colcon test \
  --packages-select safety_watchdog \
  --event-handlers console_direct+

colcon test-result --verbose
```

## 실제 결과

### Git 배포

다음 브랜치와 커밋이 TB1에서 확인됐다.

```text
feat/phase-2-safe-teleoperation
e4fa025 docs: clarify Phase 2 commit verification
f0c63cd docs: add TB1 safe teleoperation procedure
4630820 fix: require neutral command after emergency stop
3626fd4 feat: add TurtleBot safety watchdog
```

### 빌드

```text
Starting >>> safety_watchdog
Finished <<< safety_watchdog [7.17s]
Summary: 1 package finished [8.37s]
```

TB1의 Raspberry Pi aarch64 환경에서 패키지 빌드가 성공했다.

### 자동 테스트

```text
collected 13 items
test/test_flake8.py .
test/test_pep257.py .
test/test_policy.py ..........
test/test_watchdog_node.py .
Summary: 13 tests, 0 errors, 0 failures, 0 skipped
```

확인된 테스트 범위:

- 속도 제한 정책
- 양방향 속도 clamp
- `NaN`, 양의 무한대와 음의 무한대 차단
- 잘못된 제한값 거부
- timeout 경계 조건
- ROS 토픽 입력과 출력
- emergency stop 서비스
- 비상정지 해제 후 중립 재무장
- flake8
- pep257

### 실차 ROS graph 연결

TurtleBot3 bringup과 watchdog을 동시에 실행한 상태에서 다음 경로를 확인했다.

```text
/safety/cmd_vel_in
        -> safety_watchdog
        -> /cmd_vel
        -> turtlebot3_node
        -> OpenCR
```

확인된 끝점:

- `/safety/cmd_vel_in` Subscriber: `safety_watchdog` 1개
- `/cmd_vel` Publisher: `safety_watchdog` 1개
- `/cmd_vel` Subscriber: `turtlebot3_node` 1개
- 명령이 없을 때 `/cmd_vel`: 모든 축 0
- 안전 출력 발행 주기: 약 `19.997 Hz`
- `/odom`: 실제 메시지 수신
- `/dev/ttyACM0`: `turtlebot3_ros`가 소유

### 속도 제한과 timeout 실차 시험

바퀴를 바닥에서 띄운 상태에서 다음 입력을 10 Hz로 전달했다.

```yaml
input:
  linear.x: 1.0
  angular.z: 2.0
```

watchdog을 통과한 실제 `/cmd_vel` 출력은 다음과 같았다.

```yaml
output:
  linear.x: 0.05
  angular.z: 0.3
```

입력 프로세스가 종료된 1초 후 확인한 출력은 다음과 같았다.

```yaml
output_after_timeout:
  linear.x: 0.0
  angular.z: 0.0
```

물리적으로 바퀴가 제한 속도로 움직인 뒤 자동 정지하는 것도 확인했다. 정확한
정지 지연시간은 아직 계측하지 않았으며, 설정값과 1초 후 0 출력만 근거로 기록한다.

### Emergency stop과 중립 재무장 실차 시험

`0.03 m/s` 비영 입력을 10 Hz로 계속 보내는 상태에서 emergency stop 서비스를
활성화했다.

```text
input publisher count: 1
input subscriber count: 1
service response: Emergency stop activated
/cmd_vel during estop: 0.0, 0.0
```

비영 입력 Publisher가 계속 1개인 상태에서 emergency stop을 해제했다.

```text
service response: Emergency stop released; waiting for a neutral command
input publisher count after release: 1
/cmd_vel before neutral: 0.0, 0.0
```

따라서 정지 해제만으로 이전 또는 연속 비영 명령이 다시 모터로 전달되지 않는 것을
확인했다. 입력 발행기를 종료한 뒤 중립 명령을 한 번 전송했다.

```yaml
neutral:
  linear.x: 0.0
  angular.z: 0.0
```

중립 재무장 후 새로운 저속 명령을 보냈을 때 다음 출력이 허용됐다.

```yaml
input_after_rearm:
  linear.x: 0.03
  angular.z: 0.0

output_after_rearm:
  linear.x: 0.03
  angular.z: 0.0

output_after_input_ends:
  linear.x: 0.0
  angular.z: 0.0
```

이 결과로 다음 상태 전이를 실제 ROS graph에서 검증했다.

```text
TIMEOUT -> ACTIVE -> ESTOP -> WAITING_NEUTRAL -> ACTIVE -> TIMEOUT
```

### 바닥 저속 직진 시험

TB1을 평평한 바닥에 내려놓고 `0.03 m/s` 명령을 한 번만 발행했다. watchdog은
마지막 명령을 0.5초 동안만 유효하게 취급한다.

```text
position before: x=1.4764493921, y=-0.0022108721
position after:  x=1.4905966961, y=-0.0020142118
delta x: 0.0141473040 m
delta y: 0.0001966602 m
planar distance: 0.0141486710 m
```

이론상 최대 이동거리는 `0.03 m/s * 0.5 s = 0.015 m`다. 실제 odom 변화는 약
`0.01415 m`, 즉 1.415 cm로 이론값과 가까웠다. 명령 1초 후 `/cmd_vel`은 모든 축
0이었고 실제 로봇도 짧게 전진한 뒤 정지했다.

앞선 바퀴 공중 시험에서도 엔코더가 회전했기 때문에 odom 절대 위치 약 1.49 m를 실제
바닥 이동거리로 해석하지 않았다. 이번 시험의 전후 차이만 검증 근거로 사용했다.

### 바닥 저속 제자리 회전 시험

`0.2 rad/s` 회전 명령을 한 번만 발행했다.

```text
yaw before: 0.0082646608 rad
yaw after:  0.0953295827 rad
delta yaw:  0.0870649219 rad
delta yaw:  4.9884525660 degrees
translation during rotation: 0.0007341117 m
```

이론상 최대 회전량은 `0.2 rad/s * 0.5 s = 0.1 rad`, 약 5.73도다. 실제 odom
회전량은 약 0.0871 rad, 4.99도였다. 병진 변화는 약 0.73 mm였으며 1초 후
`/cmd_vel`과 odom twist는 0으로 돌아왔다.

### Keyboard teleop 시험

TB1 workspace에서 패키지와 실행 파일을 확인했다.

```text
package prefix: /home/dg/turtlebot3_ws/install/turtlebot3_teleop
executable: turtlebot3_teleop teleop_keyboard
```

teleop의 기본 `cmd_vel` 출력을 실제 모터 토픽으로 직접 연결하지 않고 안전 입력으로
remap했다.

```bash
ros2 run turtlebot3_teleop teleop_keyboard \
  --ros-args \
  -r cmd_vel:=/safety/cmd_vel_in
```

키보드 전진과 정지를 실행해 실제 로봇이 정상적으로 움직이고 멈추는 것을 확인했다.
teleop 종료 후 최종 상태는 다음과 같았다.

```text
/safety/cmd_vel_in publisher count: 0
/safety/cmd_vel_in subscriber count: 1
related teleop processes: none
/cmd_vel linear.x: 0.0
/cmd_vel angular.z: 0.0
```

첫 번째 즉시 조회에서는 Publisher가 잠시 1개로 보였지만, 프로세스와 상세 endpoint를
다시 확인한 결과 종료 후 Publisher 0개와 관련 프로세스 없음이 확인됐다. ROS graph
상태는 단일 순간의 요약만 보지 않고 endpoint와 OS 프로세스를 함께 확인했다.

## 발생한 문제와 판단

### `rosdep` 명령이 없음

TB1에서 다음 메시지가 출력됐다.

```text
Command 'rosdep' not found
```

현재 판단:

- `rosdep check`만 실행하지 못했다.
- `colcon build`가 성공했으므로 빌드에 필요한 ROS 패키지는 현재 설치돼 있다.
- 모든 단위·통합 테스트도 통과했으므로 Phase 2 실차 검증을 막는 문제는 아니다.
- 새로운 의존성이 늘어날 때 재현성 검사를 위해 `rosdep` 설치를 별도 환경 개선으로
  처리한다.

중요한 점은 명령 하나의 실패만 보고 전체 배포 실패로 판단하지 않고, 그 명령이
무엇을 검증하려던 것인지와 다른 증거를 함께 보는 것이다.

### lint 의존성 경고

```text
Warning: SelectableGroups dict interface is deprecated. Use select.
```

이는 Humble 환경에 설치된 lint 도구 쪽 의존성 경고다. 테스트 결과는 `13 passed`이며
현재 작성한 watchdog 로직의 실패는 아니다. 경고를 숨기지 않고 알려진 비차단 항목으로
남긴다.

### 첫 2초 입력 시험에서 바퀴가 움직이지 않음

처음에는 `timeout 2 ros2 topic pub`을 사용했지만 `publisher: beginning loop`가
출력되지 않았고 바퀴도 움직이지 않았다. ROS 2 CLI 프로세스 시작과 DDS discovery가
완료되기 전에 `timeout`이 발행기를 종료한 것으로 판단했다.

입력 시간을 6초와 10초로 늘렸을 때 Publisher와 Subscriber 연결, 바퀴 동작과 제한
출력을 확인했다. 이 사례에서 `timeout=124`만으로 watchdog timeout이 성공했다고
판단하면 안 되며, 입력 발행기가 실제 메시지를 보냈는지도 함께 확인해야 한다.

### Bringup 터미널 종료로 로봇 노드가 사라짐

중간 검사에서 watchdog만 보이고 `/cmd_vel` Subscriber가 0개가 됐다. 프로세스와 OpenCR
소유자를 확인한 결과 TurtleBot3 bringup이 종료된 상태였다. bringup 터미널을 다시 열어
실행한 뒤 Publisher 1개와 Subscriber 1개의 전체 경로를 복구했다.

현재는 수동 검증 단계이므로 bringup과 watchdog 터미널을 계속 유지한다. 자동 시작은
실차 안전 기능 검증이 끝난 뒤 systemd 단계에서 처리한다.

### `ros2 topic echo`의 lost message 알림

Emergency stop 출력 확인 중 `A message was lost` 알림이 있었지만, 20 Hz로 계속
발행되는 `/cmd_vel`에서 CLI 구독자가 일부 샘플을 놓친 알림이었다. 이어서 수신한 최신
메시지가 모든 축 0이었고 서비스 상태와 물리 정지 결과도 일치했다. 이 알림만으로
watchdog 발행 실패로 판단하지 않았다.

## 반드시 알아야 하는 내용

### `colcon build`와 `colcon test`의 차이

`colcon build` 성공은 패키지를 설치 가능한 형태로 만들었다는 뜻이다. 로직이 요구사항에
맞게 동작한다는 뜻은 아니다. `colcon test`는 속도 제한, timeout과 emergency stop 같은
동작을 별도로 검증한다. 따라서 둘 다 성공해야 한다.

### WSL 테스트와 TB1 테스트를 모두 하는 이유

WSL은 빠른 개발과 반복 테스트 환경이고 TB1은 실제 배포 환경이다. WSL 통과는 코드의
빠른 피드백을 제공하고, TB1 통과는 aarch64와 실제 설치 상태에서도 재현된다는 근거를
제공한다.

### 테스트에 `ROS_DOMAIN_ID=142`를 사용한 이유

TB1 실차 bringup은 도메인 42를 사용한다. 자동 통합 테스트를 다른 도메인에서 실행하면
테스트용 `/cmd_vel` 토픽이 실제 TurtleBot3 graph에 섞이지 않는다. 안전 테스트는 실제
로봇과 격리된 환경에서 먼저 수행해야 한다.

## 면접에서 설명하는 모범 답변

> 안전 watchdog을 WSL에서 먼저 개발하고 단위·ROS graph 통합 테스트 13개를 통과시킨
> 뒤, 동일한 브랜치를 Raspberry Pi aarch64 기반 TB1에 배포했습니다. 실차 명령과 테스트
> 메시지가 섞이지 않도록 테스트는 ROS_DOMAIN_ID 142에서 실행했고, TB1에서도 빌드와
> 테스트가 모두 성공했습니다. rosdep 명령은 설치되지 않았지만 실제 빌드와 테스트에
> 필요한 의존성은 충족된 상태였기 때문에 비차단 환경 개선 항목으로 분류했습니다.

## 복습 문제와 정답

### 1. `colcon build`가 성공하면 안전 기능 검증도 끝난 것인가

정답: 아니다. 빌드는 패키지 생성 가능 여부를 확인하며 timeout이나 비상정지 로직은
테스트로 별도 검증해야 한다.

### 2. 자동 테스트를 실차와 같은 ROS domain에서 실행하면 어떤 위험이 있는가

정답: 테스트용 토픽이 실제 로봇 graph와 발견·연결되어 의도하지 않은 명령이 실차에
전달될 수 있다. 따라서 별도 domain과 테스트 전용 토픽을 사용한다.

### 3. `rosdep check` 실패와 패키지 빌드 실패는 같은 의미인가

정답: 아니다. 이번 실패는 `rosdep` 실행 파일이 없는 환경 문제였다. 패키지 자체는
빌드와 테스트에 성공했다. 다만 장기 재현성을 위해 rosdep 환경은 나중에 보완한다.

### 4. 왜 x86_64 WSL과 aarch64 TB1 양쪽에서 테스트하는가

정답: 개발 환경에서 빠르게 결함을 찾고, 실제 배포 환경의 아키텍처와 설치 차이에서도
동작하는지 확인하기 위해서다.

## 완료 체크리스트

- [x] GitHub Phase 2 브랜치 복제
- [x] TB1에서 정확한 기능 커밋 확인
- [x] TB1 aarch64 환경에서 `colcon build` 성공
- [x] 격리 domain에서 자동 테스트 13개 통과
- [x] 경고와 비차단 문제 분리 기록
- [x] watchdog 실차 graph 연결 확인
- [x] 명령이 없을 때 0 속도와 약 20 Hz 출력 확인
- [x] 속도 제한과 입력 종료 후 timeout 정지 확인
- [ ] 저속 직진·회전·정지 확인
- [x] emergency stop 중 입력 차단 확인
- [x] 해제 후 연속 비영 입력 차단 확인
- [x] 중립 명령 후 재무장과 새 명령 수용 확인
- [x] 바닥에서 단일 저속 직진과 timeout 정지 확인
- [x] 바닥에서 단일 제자리 회전과 timeout 정지 확인
- [x] keyboard teleop을 안전 입력 토픽으로 remap해 확인
- [x] teleop 종료 후 Publisher 0과 안전 출력 0 확인

## 최종 PR 리뷰에서 추가로 발견한 문제

실차 검증 뒤 코드 리뷰에서 e-stop 재무장 중립 판정이 정규화된 명령을 사용한다는 점을
발견했다. `NaN`과 무한대는 정상 출력 경로에서 안전한 0으로 바꾸지만, 같은 값을 중립
판정에 사용하면 손상된 입력이 재무장 조건을 만족할 수 있다.

재무장 경로는 원시 입력 두 축이 모두 유한한지 먼저 검사하도록 변경했다. 비정상 수치가
중립으로 인정되지 않는 순수 정책 테스트 5개와 ROS graph 통합 시나리오를 보강했다.
최종 WSL 재검증 결과는 다음과 같다.

```text
collected 18 items
18 passed, 2 warnings
Summary: 18 tests, 0 errors, 0 failures, 0 skipped
```

TB1에서 기록한 13개 통과는 실차 배포 당시 revision의 결과다. 최종 변경은 비정상
수치의 재무장 거부를 더 보수적으로 만든 것이며, 기존 정상 중립·이동 명령 경로는
통합 테스트로 다시 확인했다.

## 다음에 할 일

Phase 2 필수 개념, 복습 문제, 면접 답변과 안전 설계 사례를 완성한 뒤 Draft PR을
최종 검토한다. Phase 3에서는 TB1의 battery, odom, scan freshness와 시스템 자원을
하나의 Robot Agent 상태 메시지로 구조화한다.
