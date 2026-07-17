# fleet_gateway

`fleet_gateway`는 ROS 2 `RobotStatus` heartbeat를 웹 REST·WebSocket API로 변환하고,
웹의 비상정지, 초기 위치와 Nav2 목적지 요청을 각 로봇의 안전·navigation
interface로 전달하는 관제 PC용 ROS 2 패키지다.

## 제공 경로

- `GET /api/health`: Gateway 상태와 로봇 수
- `GET /api/robots`: 전체 로봇의 마지막 상태와 online 판정
- `GET /api/robots/{robot_id}`: 단일 로봇 상태
- `POST /api/robots/{robot_id}/estop`: 비상정지 적용·해제
- `GET /api/robots/{robot_id}/map`: 최신 OccupancyGrid 단건 조회
- `PUT /api/robots/{robot_id}/localization/initial-pose`: 초기 위치 적용
- `POST /api/robots/{robot_id}/navigation/goals`: 단일 목표 접수
- `DELETE /api/robots/{robot_id}/navigation/goals/{command_id}`: 일치 목표 취소
- `WS /ws/robots`: 0.5초 주기의 상태 snapshot
- `GET /`: 단일 로봇 관제 대시보드

온라인 여부는 로봇이 보내는 값이 아니라 Gateway가 마지막 heartbeat의 로컬 수신
시각을 기준으로 판정한다. navigation과 safety 상태도 receipt age를 별도로 계산한다.
지도는 WebSocket에 반복하지 않고 REST로 가져온다. 활성 목표에는 0.5초마다
`NavigationLease`를 발행한다.

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

WSL과 로봇 사이의 실제 운영 경로는 Zenoh TCP 브리지를 사용한다. 실행 순서와
systemd 구성은 [TB1 웹 관제 운영 절차](../../docs/setup/tb1-web-dashboard.md)와
[Zenoh 브리지 운영 문서](../../infra/zenoh/README.md),
[TB1 Nav2 운영 절차](../../docs/setup/tb1-navigation.md)를 따른다.

현재 단계는 신뢰된 실습 LAN용이다. 인터넷에 노출하기 전에는 인증, 권한 분리,
TLS, 요청 감사 로그가 필요하다.
