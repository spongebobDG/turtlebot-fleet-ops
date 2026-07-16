# 학습 일지: Phase 4 TB1 웹 관제와 Zenoh 통신 경로

날짜: 2026-07-16
단계: Phase 4
진행 상태: 구현·실차 통신·안전 장애 검증 완료, PR 준비 중

## 오늘의 목표

- TB1 RobotStatus를 WSL에서 실시간으로 수신한다.
- REST와 WebSocket 기반 Fleet Gateway를 구현한다.
- 브라우저에서 단일 로봇 상태를 확인한다.
- 웹 비상정지와 통신 단절 시 안전 동작을 실차로 검증한다.
- WSL과 물리 LAN 사이 통신 경로를 재현 가능한 운영 설정으로 만든다.

## 왜 이 작업을 했는가

Phase 3까지는 TB1 내부에서 상태를 수집하고 발행하는 데 성공했다. 관제 시스템이 되려면
이 상태를 사용자가 볼 수 있는 형태로 변환하고, 로봇이 사라졌을 때 오프라인을 판단하며,
안전 명령을 로봇까지 전달해야 한다. 특히 브라우저 화면만 만드는 것이 아니라 네트워크
단절과 서비스 시간 초과에서도 로봇이 안전한지 검증하는 것이 이번 단계의 핵심이었다.

## 진행한 활동

### Fleet Gateway 구현

- thread-safe `StatusRegistry`와 3초 online timeout을 구현했다.
- `RobotStatus`를 JSON-safe dictionary로 명시적으로 직렬화했다.
- FastAPI REST API와 WebSocket endpoint를 구현했다.
- HTML·CSS·JavaScript 대시보드를 ROS 패키지 정적 자산으로 포함했다.
- 비상정지 적용·해제 API와 ROS 2 `SetBool` service client를 연결했다.
- 오프라인 상태의 e-stop 해제를 서버에서 HTTP 409로 거부했다.
- ROS 데이터 문자열은 HTML escaping 후 화면에 표시했다.

### WSL 통신 경로 조사

- WSL mirrored networking과 Hyper-V 기본 inbound 허용을 확인했다.
- 전용 UDP 인바운드 규칙이 이미 존재함을 확인했다.
- 물리 LAN에서 WSL로 향하는 일반 UDP·TCP가 도달하지 않는 현상을 재현했다.
- 방화벽을 더 넓히지 않고 Zenoh ROS 2 DDS bridge로 전환했다.
- TB1은 TCP 7447을 수신하고 WSL이 outbound 연결하도록 구성했다.
- WSL DDS는 CycloneDDS 설정으로 loopback에 격리했다.

### 브리지 설치와 무결성 검증

Zenoh 1.9.0 standalone binary를 x86_64와 aarch64에 설치했다.

```text
x86_64 SHA-256:
91aa0d569fffd57e7ebb1a591b97789891c543b1ff0a1658413ce6cbbba34a9e

aarch64 SHA-256:
e3eb1fd4459e4b877653419b1c25eaf92418d70fe53ee767eca005f1a19443dc
```

두 호스트 모두 다음 결과를 확인했다.

```text
zenoh-bridge-ros2dds v1.9.0
```

## 실행한 주요 명령

WSL Gateway 빌드와 테스트:

```bash
source /opt/ros/humble/setup.bash

colcon build \
  --base-paths interfaces control \
  --packages-up-to fleet_gateway \
  --symlink-install

colcon test \
  --base-paths interfaces control \
  --packages-select fleet_gateway

colcon test-result --verbose
```

TB1 브리지:

```bash
ROS_DISTRO=humble \
ROS_DOMAIN_ID=42 \
~/.local/bin/zenoh-bridge-ros2dds
```

WSL 브리지:

```bash
ROS_DISTRO=humble \
ROS_DOMAIN_ID=42 \
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
CYCLONEDDS_URI=file:///path/to/infra/zenoh/cyclonedds-localhost.xml \
~/.local/bin/zenoh-bridge-ros2dds -e tcp/ROBOT_ADDRESS:7447
```

## 실제 결과

### 자동 테스트

```text
13 tests, 0 errors, 0 failures, 0 skipped
```

두 개의 `SelectableGroups` deprecation warning은 Humble의 기존 pytest plugin 의존성에서
발생했고 기능 실패는 아니었다.

### 실제 Gateway 상태

```json
{
  "status": "ok",
  "known_robots": 1,
  "online_robots": 1
}
```

실시간 API와 대시보드에서 다음 범주를 확인했다.

- TB1 heartbeat와 online 상태
- 배터리 percentage와 voltage
- odom 위치·yaw·속도
- LiDAR valid point 수와 최소 거리
- CPU·메모리·디스크·load average·uptime
- Wi-Fi 신호
- fault code와 상태 레벨

### 브라우저 시각 검증

- 정적 CSS 요청: HTTP 200, `text/css`
- WebSocket 연결: 실시간 연결 상태
- 등록 로봇: 1
- 온라인 로봇: 1
- fault: 0
- TB1 카드: 실제 센서·자원 값이 계속 갱신됨

### 웹 비상정지

CycloneDDS 통일 후 웹 요청 결과:

```json
{
  "success": true,
  "robot_id": "tb1",
  "engaged": true,
  "message": "Emergency stop activated"
}
```

TB1의 실제 출력:

```text
linear.x=0.0
angular.z=0.0
```

### 통신 단절과 복구

TB1 Zenoh bridge를 중단한 뒤:

```json
{
  "robot_id": "tb1",
  "online": false,
  "heartbeat_age_sec": 6.161
}
```

오프라인 상태에서 e-stop 해제 요청:

```text
HTTP 409
Cannot release emergency stop while robot is offline
```

브리지 복구 후:

```json
{
  "robot_id": "tb1",
  "online": true,
  "heartbeat_age_sec": 1.077
}
```

해제 응답:

```text
Emergency stop released; waiting for a neutral command
```

중립 명령을 보낸 뒤 `/cmd_vel`은 계속 0이었다.

## 발생한 문제와 해결

### 1. colcon symlink-install에서 CSS가 404가 됨

Starlette의 당시 버전이 symlink된 정적 디렉터리를 기대한 방식으로 따라가지 않아
HTML은 열리지만 CSS가 404였다. 허용된 정적 파일 이름을 명시하고 `FileResponse`로
반환하도록 수정했다. 수정 후 CSS는 HTTP 200으로 확인했다.

### 2. Zenoh가 다른 ROS 배포판 GID를 가정함

로봇 브리지 실행 시 `ROS_DISTRO`가 없으면 다른 배포판을 가정해 invalid GID 경고가
발생했다. `ROS_DISTRO=humble`을 명시하고 브리지를 재시작하자 경고가 사라졌다.

### 3. WSL 시각이 앞서 Zenoh timestamp가 폐기됨

TB1 로그에서 관제 브리지 timestamp가 현재보다 500ms 이상 앞섰다는 오류를 확인했다.
실측 시 WSL이 Windows보다 약 2초 느렸고 TB1과도 1초 이상 차이가 났다.
`hwclock -s`로 WSL 시간을 동기화하고 브리지를 재시작했다.

### 4. 상태 토픽은 되지만 e-stop 서비스가 시간 초과됨

TB1 직접 호출은 성공했으므로 watchdog 문제를 제외했다. Zenoh debug 로그에서 양쪽
service endpoint 발견과 query 생성은 확인됐지만 원격 bridge가 5초 후 `Timeout`을
반환했다. TB1 ROS 노드는 Fast DDS, 브리지는 CycloneDDS였던 점을 공식 권장 조합과
비교했다.

TB1에 `ros-humble-rmw-cyclonedds-cpp`를 설치하고 watchdog을 CycloneDDS로
재시작하자 웹 e-stop이 즉시 성공했다. 이후 모든 TB1 운영 서비스를 CycloneDDS로
통일하도록 systemd 단위를 작성했다.

상세 사례:
[Zenoh 서비스 시간 초과와 RMW 혼용](../case-studies/zenoh-service-timeout-rmw-mismatch.md)

### 5. WSL 사용자 systemd 버스가 없음

WSL 최소 설치본에는 `dbus-user-session`이 없어 `systemctl --user`를 바로 사용할 수
없었다. 패키지를 설치하고 `loginctl enable-linger dg`를 적용해 로그인 세션이 없어도
관제 서비스가 유지되도록 했다.

### 6. Gateway가 systemd에서만 시작 실패함

대화형 셸에서는 정상이었지만 systemd 시작 스크립트의 `set -u`와 ROS Humble 환경
설정 스크립트가 충돌했다. ROS underlay와 workspace overlay를 source하는 구간에서만
nounset을 끄고, 이후 다시 켜도록 범위를 제한해 해결했다.

### 7. systemd 자동 복구를 기능 수준에서 검증

TB1 bringup, safety watchdog, Robot Agent, Zenoh bridge와 WSL control bridge, Gateway를
사용자 서비스로 배포했다. WSL bridge와 Gateway의 주 프로세스를 각각 강제 종료했을
때 새 PID로 자동 재시작됐고 REST 상태와 e-stop 왕복 호출도 다시 성공했다.

TB1 Robot Agent의 주 PID `8286`을 종료한 시험에서는 다음과 같이 관측됐다.

- 약 3.7초: Gateway가 `online=false`로 판정
- 약 11.4초: ROS 2 discovery와 Zenoh 재등록 뒤 `online=true` 복귀
- 복구 MainPID: `8703`, Agent 프로세스 PID: `8818`
- 최종 heartbeat age: `0.543`초, fault 없음
- 최종 `/cmd_vel`: 선속도와 각속도 모두 0

짧은 고정 대기만 사용했을 때는 정상 복구 중인 서비스를 실패로 오판할 수 있었다.
운영 검증은 `MainPID` 변경과 API 기능 복귀를 제한 시간 동안 조건식으로 확인해야 한다.

## 배운 점 / 메모

- 화면에 데이터가 보이는 것은 전체 제어 경로가 정상이라는 뜻이 아니다.
- 토픽, 서비스, 액션은 각각 실제 end-to-end 테스트가 필요하다.
- 오프라인은 송신자가 아니라 수신자가 heartbeat age로 판정한다.
- 로봇 안전은 관제 서버보다 로봇 로컬 watchdog에 있어야 한다.
- 네트워크 경계를 단순화하는 고정 TCP 브리지는 WSL 환경에서 운영성이 높다.
- 공식 지원 조합을 기준선으로 두고 변경된 RMW 조합은 별도 검증해야 한다.
- 시각 동기화는 로그 보기 편의가 아니라 분산 메시지 수용 여부에 영향을 줄 수 있다.

## 오늘 꼭 기억해야 할 것

1. `online = now_monotonic - last_received <= timeout`
2. REST는 명령 결과, WebSocket은 지속 상태 스트림이다.
3. UI 안전 검사와 서버 안전 검사를 둘 다 둔다.
4. `ROS_DISTRO`, `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`을 런타임 계약으로 관리한다.
5. 네트워크가 끊겨도 로봇 watchdog은 0 속도를 출력해야 한다.
6. 토픽 성공으로 서비스 성공을 추정하지 않는다.
7. 프로세스 `active`와 기능 `ready`를 구분한다.

## 완료 체크리스트

- [x] Gateway 패키지와 API 구현
- [x] 자동 테스트 13개 통과
- [x] TB1 실데이터 REST 조회
- [x] WebSocket과 웹 화면 실시간 갱신
- [x] 웹 비상정지 적용과 실제 0 속도 확인
- [x] 브리지 단절 시 offline 판정
- [x] offline e-stop 해제 HTTP 409 차단
- [x] 브리지 복구와 online 전환
- [x] 설치·운영·공부 문서 작성
- [x] systemd 사용자 서비스 실기 배포와 자동 복구
- [x] Draft PR #5 생성
- [ ] CI 확인
- [ ] PR 자체 리뷰와 squash merge

## 복습 문제와 정답

### 1. 로봇이 죽으면 `online=false`를 보내도록 구현하면 왜 부족한가?

정답: 죽거나 통신이 끊긴 로봇은 메시지를 보낼 수 없으므로 수신자가 마지막 heartbeat
수신 후 경과 시간으로 오프라인을 추론해야 한다.

### 2. 비상정지의 최종 집행을 Gateway가 아니라 로봇에 둔 이유는?

정답: 관제 PC나 네트워크가 끊겨도 로봇이 입력 timeout을 감지하고 0 속도를 보장해야
하기 때문이다.

### 3. Fast DDS 토픽이 Zenoh bridge를 통과했는데 서비스가 실패한 이유는?

정답: 표준 토픽 상호 운용과 ROS 2 서비스 request/reply 식별자 호환은 별도 문제다.
CycloneDDS 기반 브리지의 공식 검증 조합에 맞춰 로봇 RMW도 CycloneDDS로 통일했다.

### 4. offline 해제를 HTTP 409로 반환한 이유는?

정답: 요청 형식은 맞지만 현재 로봇 상태와 충돌해 수행할 수 없는 명령이므로 409
Conflict가 의미에 맞고, 안전하지 않은 재무장을 서버가 거부해야 하기 때문이다.

### 5. WSL DDS를 loopback으로 제한한 이유는?

정답: 직접 DDS와 Zenoh라는 중복 경로가 동시에 생겨 메시지 중복이나 루프가 발생하는
것을 막기 위해서다.

## 다음에 할 일

1. PR #5의 CI와 전체 diff를 자체 리뷰한다.
2. PR을 Ready로 전환하고 squash merge한다.
3. Phase 5에서 SLAM·Nav2 웹 명령 경계를 설계한다.

## 관련 커밋

- `b36fdc3 feat: add TB1 fleet web dashboard`
- `f736e0f infra: add Zenoh ROS 2 bridge services`
- `cfcfe83 docs: record Phase 4 web validation`
- `3e6fc51 fix: load ROS environment in systemd gateway`
- Draft PR: `#5 feat: add TB1 real-time web fleet dashboard`
