# fleet_gateway

`fleet_gateway`는 ROS 2 `RobotStatus` heartbeat를 웹 REST·WebSocket API로 변환하고,
웹의 비상정지와 Nav2 목적지 요청을 로봇의 `safety_watchdog` 서비스와
`NavigateToPose` Action으로 전달하는 관제 PC용 ROS 2 패키지다.

## 제공 경로

- `GET /api/health`: Gateway 상태와 로봇 수
- `GET /api/robots`: 전체 로봇의 마지막 상태와 online 판정
- `GET /api/robots/{robot_id}`: 단일 로봇 상태
- `POST /api/robots/{robot_id}/estop`: 비상정지 적용·해제
- `POST /api/robots/{robot_id}/navigation/goals`: map 좌표 Goal 전송
- `GET /api/robots/{robot_id}/navigation`: 마지막 Goal 상태 조회
- `POST /api/robots/{robot_id}/navigation/cancel`: 활성 Goal 취소
- `POST /api/robots/{robot_id}/navigation/retry`: 마지막 실패 Goal 재시도
- `WS /ws/robots`: 0.5초 주기의 로봇·Goal 상태 snapshot
- `GET /`: 단일 로봇 관제 대시보드

온라인 여부는 로봇이 보내는 값이 아니라 Gateway가 마지막 heartbeat의 로컬 수신
시각을 기준으로 판정한다. 기본 timeout은 3초다.

## Nav2 Goal 수명주기

```text
IDLE -> PENDING -> RUNNING -> SUCCEEDED
                         \-> ABORTED
                         \-> CANCELING -> CANCELED
                                      \-> TIMEOUT
      \-> REJECTED
```

HTTP Goal 요청은 Nav2의 최종 도착까지 기다리지 않고 Action 서버의 수락 여부까지만
확인한 뒤 `202 Accepted`를 반환한다. 진행 feedback과 최종 결과는 조회 API와
WebSocket으로 전달한다. 로봇마다 활성 Goal은 하나만 허용한다.

```bash
curl -X POST http://localhost:8000/api/robots/tb1/navigation/goals \
  -H 'Content-Type: application/json' \
  -d '{"x": 1.0, "y": 0.5, "yaw": 0.0, "timeout_sec": 300}'

curl http://localhost:8000/api/robots/tb1/navigation
curl -X POST http://localhost:8000/api/robots/tb1/navigation/cancel
curl -X POST http://localhost:8000/api/robots/tb1/navigation/retry
```

좌표는 유한한 숫자와 `map` frame만 허용한다. 오프라인 로봇은 새 Goal을 거부한다.
비상정지는 먼저 로컬 watchdog를 정지 상태로 만들고 활성 Goal 취소를 요청한다. 활성
Goal이 남은 동안에는 비상정지 해제를 거부한다. Goal timeout이나 늦은 수락은 fail-closed로
비상정지를 적용하고 Action 취소를 요청한다.

새 Goal과 재시도는 watchdog의 `/safety/estop_active` heartbeat가 최신이고 해제 상태일
때만 허용한다. 재시도 가능한 상태는 `ABORTED`, `REJECTED`, `TIMEOUT`이며 새 Goal ID와
`retry_count`, `retried_from_goal_id`를 반환한다. 성공 Goal과 사용자가 취소한 Goal은
재시도하지 않는다.

## 실행

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///path/to/infra/zenoh/cyclonedds-localhost.xml
ros2 launch fleet_gateway fleet_gateway.launch.py
```

그 후 관제 PC 브라우저에서 `http://localhost:8000`을 연다.

로봇이 없는 개발 PC에서는 mock TB1과 Gateway를 함께 실행할 수 있다.

```bash
bash scripts/weekend/start_mock_stack.sh
```

mock은 상태, e-stop 서비스·heartbeat와 `NavigateToPose` 성공·취소·timeout·abort 경로를
제공하지만 실차 acceptance를 대신하지 않는다. 새 PC 전체 절차는
[주말 무로봇 개발 환경](../../docs/setup/weekend-robotless-development.md)을 따른다.

WSL과 로봇 사이의 실제 운영 경로는 Zenoh TCP 브리지를 사용한다. 실행 순서와
systemd 구성은 [TB1 웹 관제 운영 절차](../../docs/setup/tb1-web-dashboard.md)와
[Zenoh 브리지 운영 문서](../../infra/zenoh/README.md)를 따른다.

현재 단계는 신뢰된 실습 LAN용이다. 인터넷에 노출하기 전에는 인증, 권한 분리,
TLS, 요청 감사 로그가 필요하다.
