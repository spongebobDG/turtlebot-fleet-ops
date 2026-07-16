# Phase 3 설계: Robot Agent와 RobotStatus 계약

## 목적

관제 시스템이 `/battery_state`, `/odom`, `/scan`과 Linux 자원 정보를 각각 해석하지
않아도 되도록 로봇 내부에서 하나의 구조화된 상태로 집계한다. TB1에서 검증한 뒤 같은
코드와 다른 설정을 TB2에 적용한다.

## 데이터 흐름

```text
/battery_state ─┐
/odom ──────────┼─> robot_agent ─> /fleet/robot_status ─> 향후 Fleet Gateway
/scan ──────────┤
Linux resources ┘
```

Robot Agent는 주행 명령을 발행하지 않는다. 상태 관측과 안전 제어를 분리하며, 모터 정지는
Phase 2의 `safety_watchdog`이 계속 담당한다.

## 패키지 분리

| 패키지 | 빌드 형식 | 책임 |
| --- | --- | --- |
| `fleet_interfaces` | `ament_cmake` | `RobotStatus.msg` 생성과 공유 |
| `robot_agent` | `ament_python` | 토픽 구독, 정규화, freshness·health 계산, 상태 발행 |

인터페이스를 실행 코드와 분리하면 이후 FastAPI gateway, 로그 수집기와 테스트 도구가
Robot Agent 구현에 의존하지 않고 메시지 계약만 사용할 수 있다.

## RobotStatus 계약

원본 정의는
[`RobotStatus.msg`](../../robot/fleet_interfaces/msg/RobotStatus.msg)에 있다.

| 영역 | 주요 필드 | 의미 |
| --- | --- | --- |
| 식별 | `robot_id`, `hostname`, `header.stamp` | 논리 로봇 ID, 실제 host, 발행 시각 |
| 전체 상태 | `level`, `fault_codes` | OK/WARN/ERROR와 기계 판독 가능한 원인 |
| 배터리 | received/fresh/valid, age, percent, voltage | 수신·시간·값 유효성을 분리 |
| 주행 상태 | odom received/fresh/valid, x, y, yaw, velocity | 평면 위치와 속도 snapshot |
| LiDAR | scan received/fresh/valid, age, point count, min range | 원본 scan을 요약한 상태 |
| 시스템 | CPU, memory, disk, load average, uptime | Raspberry Pi 자원 상태 |

## received, fresh, valid를 나눈 이유

세 조건은 서로 다른 장애를 나타낸다.

- `received=false`: 프로세스 시작 후 메시지를 한 번도 받지 못함
- `received=true`, `fresh=false`: 과거에는 받았지만 갱신이 끊김
- `fresh=true`, `valid=false`: 메시지는 오지만 값이 비정상임

Topic 이름이나 Publisher 존재만으로는 실제 데이터 품질을 판단할 수 없다. 이 구분은
Phase 1에서 `/scan` Publisher는 존재했지만 데이터가 없었던 장애 경험을 설계에 반영한
것이다.

## Freshness 정책

마지막 callback 시간을 `time.monotonic()`으로 기록한다. 시스템 시각이나 NTP 보정이
바뀌어도 age 계산이 역행하지 않게 하기 위해서다.

| source | TB1 timeout |
| --- | ---: |
| battery | 5.0초 |
| odom | 1.0초 |
| scan | 2.0초 |

Threshold는 [`tb1.yaml`](../../robot/robot_agent/config/tb1.yaml)에서 변경할 수 있다.
실제 발행 주기와 네트워크 지연을 측정한 뒤 조정해야 하며, 현재 값이 모든 환경의 정답은
아니다.

## Health 정책

### ERROR

- `ODOM_NOT_RECEIVED`, `ODOM_INVALID`, `ODOM_STALE`
- `SCAN_NOT_RECEIVED`, `SCAN_INVALID`, `SCAN_STALE`

### WARN

- battery 미수신·비정상·stale·20% 이하
- CPU, memory, disk가 각 90% 이상

### OK

모든 필수 source가 fresh·valid이고 경고 threshold를 넘지 않은 상태다.

Fault code는 화면 문장 대신 안정적인 identifier를 사용한다. 향후 dashboard 번역, alert
rule과 로그 검색이 문구 변경에 영향받지 않게 하기 위해서다.

## 온라인 상태를 메시지에 넣지 않은 이유

Robot Agent 프로세스나 로봇 전원이 꺼지면 스스로 `online=false` 메시지를 보낼 수 없다.
따라서 Agent는 1 Hz heartbeat 역할의 상태만 발행하고, Fleet Gateway가 마지막 수신
시각을 기준으로 online/offline을 판단한다.

## 숫자 정규화 결정

### 배터리 percentage

표준 `BatteryState.percentage`는 일반적으로 0~1이지만 현재 TurtleBot 출력에서는
86.66처럼 0~100 값이 관찰됐다. Agent는 다음 규칙으로 0~100 percent로 통일한다.

- 0~1: 100을 곱함
- 1 초과~100: 그대로 사용
- 범위 밖 또는 비유한 값: unknown

### unknown 값

향후 JSON gateway에서 비표준 NaN 직렬화를 피하기 위해 숫자 unknown은 `-1.0`을
사용하고 별도의 `valid` 필드로 판정한다. 위치가 실제로 -1일 수도 있으므로 consumer는
sentinel만 보지 말고 반드시 valid를 함께 확인해야 한다.

## QoS 결정

`/scan`은 실제 TB1에서 BEST_EFFORT Publisher로 확인됐으므로 Robot Agent 구독도
sensor-data QoS를 사용한다. Reliable 구독을 무조건 요구하면 BEST_EFFORT Publisher와
호환되지 않아 topic은 보이지만 메시지를 받지 못할 수 있다.

## 현재 범위에서 제외한 것

- gateway에서의 online/offline 판정
- 상태 저장 DB와 웹소켓 전송
- 진단 이력과 alert suppression
- systemd 자동 시작·재시작
- TB2 namespace와 다중 로봇 검증
- 센서 고장 시 안전 정지 연동

## 완료 조건

- [x] custom `RobotStatus` interface 생성
- [x] battery, odom, scan과 host resource 집계
- [x] received/fresh/valid와 fault code 계산
- [x] WSL build와 29개 Robot Agent 테스트 통과
- [x] 설치된 launch 파일 시작과 초기 fail-closed 로그 확인
- [ ] TB1 실제 source를 사용해 OK 상태 메시지 확인
- [ ] TB1에서 source 중단 후 stale fault 전환 확인
- [ ] 실제 결과를 학습 일지와 PR에 기록
