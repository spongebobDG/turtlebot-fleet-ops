# 학습 일지: Phase 2 TB1 Safety Watchdog 배포

날짜: 2026-07-15  
단계: Phase 2  
진행 상태: 진행 중 - TB1 빌드와 자동 테스트 완료, 실차 동작 검증 대기

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
- [ ] watchdog 실차 graph 연결 확인
- [ ] 명령이 없을 때 0 속도 확인
- [ ] 속도 제한과 timeout 정지 확인
- [ ] 저속 직진·회전·정지 확인
- [ ] emergency stop과 중립 재무장 확인

## 다음에 할 일

TB1 bringup과 watchdog을 ROS domain 42에서 실행한 뒤 먼저 움직임 없이 `/cmd_vel`의
Publisher, Subscriber와 0 속도 출력을 확인한다. 구조가 정확할 때만 바퀴를 띄운 상태의
속도 제한 시험으로 넘어간다.
