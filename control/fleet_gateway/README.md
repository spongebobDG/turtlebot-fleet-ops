# fleet_gateway

`fleet_gateway`는 ROS 2 `RobotStatus` heartbeat를 웹 REST·WebSocket API로 변환하고,
웹의 비상정지, 초기 위치와 Nav2 목적지 요청을 각 로봇의 안전·navigation
interface로 전달하는 관제 PC용 ROS 2 패키지다. 현재 운영 범위는 TB1 한 대이며 작업,
고장 전이와 감사 기록을 SQLite에 보존한다.

## 제공 경로

- `GET /api/health`: Gateway 상태와 로봇 수
- `GET /api/robots`: 전체 로봇의 마지막 상태와 online 판정
- `GET /api/robots/{robot_id}`: 단일 로봇 상태
- `POST /api/robots/{robot_id}/estop`: 비상정지 적용·해제
- `GET /api/robots/{robot_id}/map`: 최신 OccupancyGrid 단건 조회
- `PUT /api/robots/{robot_id}/localization/initial-pose`: 초기 위치 적용
- `POST /api/robots/{robot_id}/navigation/goals`: 단일 목표 접수
- `DELETE /api/robots/{robot_id}/navigation/goals/{command_id}`: 일치 목표 취소
- `GET /api/tasks`, `GET /api/tasks/{task_id}`: 작업 조회
- `POST /api/robots/{robot_id}/tasks`: 지도 목적지 작업 생성
- `POST /api/tasks/{task_id}/run`: 생성 작업 실행
- `DELETE /api/tasks/{task_id}`: 생성 또는 활성 작업 취소
- `POST /api/tasks/{task_id}/retry`: 실패·취소 작업의 새 attempt 생성
- `GET /api/robots/{robot_id}/faults`: 활성·해제 고장 이력
- `GET /api/events`: 안전·위치추정·작업·고장 감사 이벤트
- `WS /ws/robots`: 0.5초 주기의 상태 snapshot
- `GET /`: 단일 로봇 관제 대시보드

온라인 여부는 로봇이 보내는 값이 아니라 Gateway가 마지막 heartbeat의 로컬 수신
시각을 기준으로 판정한다. navigation과 safety 상태도 receipt age를 별도로 계산한다.
지도는 WebSocket에 반복하지 않고 REST로 가져온다. 활성 목표에는 0.5초마다
`NavigationLease`를 발행한다.

기본 운영 DB는 `~/.local/share/turtlebot-fleet-ops/operations.sqlite3`다. 테스트나 임시
실행에서는 `FLEET_OPERATIONS_DB`로 다른 파일을 지정한다. 동일 fault heartbeat는 한 번의
발생 event로 압축하고 해제 때 별도 event를 남긴다. retry는 기존 실패를 덮지 않고
`parent_task_id`와 증가한 attempt를 가진 새 task를 만든다.
Gateway가 재시작되면 이전 ROS action handle을 복구할 수 없으므로 DB의 `STARTING`과
`ACTIVE` task는 `FAILED`로 닫고 감사 event를 남긴다. 이전 lease나 목표는 자동으로
재개하지 않으며 새 시도는 명시적인 retry로만 만든다.

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

로봇 없는 작업·고장 UI 개발은 다음 경로를 사용한다.

```bash
bash scripts/weekend/verify_workspace.sh
bash scripts/weekend/start_mock_stack.sh
```

mock은 현재 `NavigateRobot`, lease, 지도·초기 위치와 safety 계약을 제공하지만 실차 센서,
모터와 물리 정지시간을 대신하지 않는다.

ROS 2가 없는 Windows에서 UI만 확인하려면 다음 seeded preview를 사용한다.

```powershell
python -m pip install fastapi uvicorn websockets
python infra/navigation/robotless_web_preview.py
```

기본 주소는 `http://127.0.0.1:18080`이다. preview는 실제 heartbeat, DDS, action 또는
`/cmd_vel` 검증이 아니다.

WSL과 로봇 사이의 실제 운영 경로는 Zenoh TCP 브리지를 사용한다. 실행 순서와
systemd 구성은 [TB1 웹 관제 운영 절차](../../docs/setup/tb1-web-dashboard.md)와
[Zenoh 브리지 운영 문서](../../infra/zenoh/README.md),
[TB1 Nav2 운영 절차](../../docs/setup/tb1-navigation.md)를 따른다.

현재 단계는 신뢰된 실습 LAN용이다. 인터넷에 노출하기 전에는 인증, 권한 분리,
TLS, 요청 감사 로그가 필요하다.
