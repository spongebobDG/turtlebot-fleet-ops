# Phase 4 설계: TB1 Fleet Gateway와 웹 관제

## 목적

관제 PC의 WSL에서 TB1의 `/fleet/robot_status`를 수신하고 웹 브라우저에 실시간으로
보여 준다. 로봇의 heartbeat가 끊기면 Gateway가 offline을 판정하며, 웹에서
TB1 `safety_watchdog` 비상정지 서비스를 호출할 수 있게 한다.

## 데이터 흐름

```text
TB1 robot_agent -- local DDS --> TB1 Zenoh bridge
                                      |
                                      | TCP 7447
                                      v
WSL Zenoh bridge -- loopback DDS --> fleet_gateway
                                         |-- StatusRegistry
                                         |-- REST /api/robots
                                         |-- WS /ws/robots
                                         `-- HTML dashboard

Browser -- POST estop --> fleet_gateway -- Zenoh service route --> TB1 safety_watchdog
```

물리 LAN과 WSL 사이의 DDS discovery·동적 UDP 포트 의존성을 줄이기 위해 호스트 간
경로는 Zenoh TCP로 고정한다. WSL DDS는 loopback에 격리해 직접 DDS와 Zenoh의
중복 경로 및 루프를 방지한다.

## 책임 분리

- Robot Agent: 로봇 내부 센서·자원 상태를 해석한다.
- Fleet Gateway: 여러 heartbeat의 마지막 수신 시각을 저장하고 online을 판정한다.
- FastAPI: 상태 조회·실시간 스트림·안전 명령 경계를 제공한다.
- Browser: 상태를 표현하고 사용자의 명시적인 안전 명령만 전달한다.
- Safety Watchdog: 최종 속도 제한·timeout·비상정지를 로봇에서 집행한다.

웹이나 Gateway가 최종 모터 안전장치가 아니다. 네트워크가 끊겨도 로봇 내부
Watchdog가 0 속도를 계속 출력하는 구조를 유지한다.

## 온라인 판정

Robot Agent가 죽거나 로봇 전원이 꺼지면 `online=false` 메시지를 보낼 수 없다.
따라서 Gateway가 로컬 monotonic clock으로 마지막 heartbeat 수신 후 경과 시간을
계산한다.

- 기본 heartbeat: 1 Hz
- online timeout: 3초
- `age <= 3초`: online
- `age > 3초`: offline

이 판정은 로봇 시계와 관제 PC 시계가 달라도 영향을 받지 않는다.

## API 계약

| 경로 | 역할 |
| --- | --- |
| `GET /api/health` | Gateway와 알려진·온라인 로봇 수 |
| `GET /api/robots` | 모든 마지막 상태와 online 판정 |
| `GET /api/robots/{id}` | 한 로봇 상태 |
| `POST /api/robots/{id}/estop` | 비상정지 적용 또는 해제 |
| `WS /ws/robots` | 0.5초 간격의 전체 상태 snapshot |

## 안전 결정

- 비상정지 적용과 해제 모두 브라우저 확인창을 거친다.
- offline 로봇의 해제 버튼은 비활성화한다.
- Watchdog는 해제 후에도 중립 명령을 받기 전까지 움직임을 허용하지 않는다.
- Gateway 명령 실패는 HTTP 503으로 반환한다.
- offline 로봇의 비상정지 해제는 서버도 HTTP 409로 거부한다.
- 실제 서비스 호출은 1초 발견 timeout과 3초 응답 timeout을 둔다.
- 로봇 ROS 노드와 브리지는 Humble·domain 42·CycloneDDS 조합으로 통일한다.

## 현재 보안 범위

Phase 4는 신뢰된 실습 LAN용이다. 인터넷 공개용 완성 상태가 아니다. 운영 배포에는
로그인, 역할 기반 권한, TLS, CSRF 방어, 명령 감사 로그, rate limit이 추가로
필요하다.

## 완료 조건

- [x] WSL에서 TB1 RobotStatus 실데이터 수신
- [x] Gateway 패키지 build와 전체 테스트 통과
- [x] REST에서 TB1 online과 실제 상태 확인
- [x] WebSocket 실시간 갱신 확인
- [x] 웹 대시보드 시각 확인
- [x] 웹 비상정지 적용·해제와 안전 출력 확인
- [x] 상태 경로 중단 시 3초 후 offline, 복구 시 online 확인
- [x] offline 비상정지 해제의 서버 차단 확인
- [x] 작업 일지·공부·운영 문서 작성
- [x] TB1·WSL systemd 실기 배포와 자동 복구 확인
- [ ] PR CI·자체 리뷰와 squash merge
