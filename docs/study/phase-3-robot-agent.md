# Phase 3 공부 문서: Robot Agent와 상태 계약

## 이번 Phase를 한 문장으로 설명하면

“로봇의 여러 ROS topic과 Linux 자원을 하나의 typed `RobotStatus` heartbeat로 집계하고,
수신 여부·freshness·값 유효성을 분리해 관제 시스템이 즉시 상태와 원인을 판단할 수 있게
했습니다.”

## 오늘 꼭 기억해야 할 것

1. **Topic이 보인다는 것과 데이터가 정상이라는 것은 다르다.** Publisher 수뿐 아니라
   실제 메시지, freshness, validity를 확인해야 한다.
2. **received, fresh, valid는 서로 다른 장애다.** 합쳐서 `healthy` 하나로 만들면 진단
   근거를 잃는다.
3. **죽은 Agent는 `online=false`를 보낼 수 없다.** online은 Gateway가 heartbeat의
   마지막 수신 시각으로 판정한다.
4. **QoS도 통신 계약이다.** type과 topic 이름이 같아도 Reliability가 호환되지 않으면
   메시지가 전달되지 않는다.
5. **Interface는 여러 서비스가 공유하는 API다.** 실행 코드와 분리하고 변경 영향을
   테스트·리뷰해야 한다.
6. **실제 시각과 경과 시간은 목적이 다르다.** 화면·로그에는 ROS timestamp, timeout에는
   monotonic age를 사용한다.

## 반드시 알아야 할 구조

```text
원본 센서·상태 topic
  ├─ /battery_state
  ├─ /odom
  └─ /scan
        + Linux CPU/memory/disk
                 │
                 ▼
            robot_agent
                 │  fleet_interfaces/msg/RobotStatus
                 ▼
       /fleet/robot_status (1 Hz)
                 │
                 ▼
        향후 Fleet Gateway와 Web
```

## 1. 왜 Robot Agent가 필요한가

웹 서버가 각 TurtleBot의 원본 topic 이름, QoS, 배터리 단위와 장애 판정 규칙을 모두 알면
결합도가 높아진다. Robot Agent는 로봇 가까이에서 원본 데이터를 해석하고 안정적인 상태
계약으로 바꾸는 anti-corruption layer 역할을 한다.

장점:

- 로봇별 드라이버 차이를 Agent 설정과 정규화 로직에 숨김
- Gateway는 하나의 메시지 계약만 처리
- freshness와 fault 판정을 로봇마다 동일하게 적용
- TB2 추가 시 같은 코드와 다른 `robot_id` 설정 재사용

## 2. Custom message를 사용한 이유

JSON 문자열을 `std_msgs/String`으로 보내면 빠르게 만들 수 있지만 다음 문제가 있다.

- 컴파일 시 field와 type을 검사할 수 없음
- consumer마다 JSON parsing과 예외 처리가 필요
- 필드 변경을 ROS interface dependency로 추적하기 어려움
- `ros2 interface show`, rosbag과 introspection의 이점을 잃음

`fleet_interfaces/msg/RobotStatus`를 사용하면 schema가 명시되고 빌드 시 호환성 문제가
드러난다. 향후 web 경계에서만 typed ROS message를 JSON으로 변환한다.

## 3. 인터페이스 패키지를 분리한 이유

`fleet_interfaces`는 message 계약만, `robot_agent`는 실행 코드만 가진다. Gateway가
RobotStatus를 사용하기 위해 Robot Agent 구현과 `psutil`까지 의존할 필요가 없다.

실무적으로 interface 변경은 여러 producer와 consumer에 영향을 주므로 일반 코드보다
더 신중한 리뷰와 버전 관리가 필요하다.

## 4. received, fresh, valid의 차이

| 상태 | 예시 | 필요한 판단 |
| --- | --- | --- |
| not received | 노드 시작 후 `/scan`을 한 번도 못 받음 | 배선, driver, QoS, domain 확인 |
| stale | 이전에는 받았지만 마지막 scan이 오래됨 | process·통신 중단 의심 |
| invalid | 최신 scan이지만 유효 거리점이 0개 | 센서 값 또는 파라미터 이상 |

이 세 값을 하나의 `healthy` boolean으로 합치면 원인과 대응 방법을 잃는다. Phase 1에서
Publisher가 존재해도 `/scan` 데이터가 없었던 경험이 이 모델의 근거다.

## 5. Freshness와 heartbeat

Agent는 각 callback에서 `time.monotonic()`을 저장하고 상태 발행 시 age를 계산한다.
monotonic clock은 NTP나 시스템 시각 수정으로 역행하지 않으므로 timeout 측정에 적합하다.

RobotStatus 자체도 1 Hz heartbeat다. Gateway는 마지막 RobotStatus 수신 시각으로 로봇의
online/offline을 판정해야 한다.

### 왜 Agent가 `online=false`를 보내지 않는가

프로세스가 죽거나 전원이 꺼지면 메시지를 보낼 수 없다. 자기 자신이 계속 살아 있다고
가정해야 발행할 수 있는 `online` boolean은 장애 판정에 신뢰할 수 없다. 수신자가 heartbeat
부재를 판단하는 것이 맞다.

## 6. ROS time과 monotonic time의 역할 차이

- `header.stamp`: ROS clock을 사용해 다른 ROS 데이터와 시간축을 맞춤
- freshness timeout: process monotonic clock을 사용해 경과 시간을 안정적으로 계산

시뮬레이션의 `/clock`을 freshness에 사용할지는 별도 정책이다. 현재 Agent는 실제 TB1
운영을 대상으로 wall/ROS time 정지와 무관한 process 경과 시간을 사용한다.

## 7. BatteryState percentage 단위 정규화

ROS 표준 의미는 0~1이지만 TB1에서 86.66 같은 0~100 값이 관찰됐다. Agent는 0~1이면
100을 곱하고, 1 초과~100이면 그대로 사용한다. 범위를 벗어나거나 비유한 값은 unknown으로
처리한다.

이 로직은 임의 추측이 아니라 실제 장치 증거와 표준 양쪽을 수용하기 위한 compatibility
policy다. 원본 값과 vendor 문서를 추가 확인하면 더 명시적인 driver별 adapter로 바꿀 수
있다.

## 8. `-1.0` sentinel과 valid flag

JSON 표준에는 NaN이 없다. 미래 Gateway 직렬화를 고려해 unknown 숫자를 `-1.0`으로
표현하고 별도의 valid flag를 둔다.

단점은 위치 x=-1처럼 실제 값과 sentinel이 겹칠 수 있다는 점이다. 따라서 consumer는
숫자만 비교하지 말고 반드시 received/fresh/valid를 함께 사용해야 한다. 장기적으로는
field별 availability 또는 별도 diagnostic 구조를 검토할 수 있다.

## 9. 마지막 수신 시각과 age를 둘 다 제공하는 이유

`last_received`는 “몇 시에 마지막으로 받았는가”를 로그와 화면에서 보여준다. `age_sec`는
“지금 기준으로 얼마나 오래됐는가”를 timeout 정책에 사용한다. 마지막 시각은 ROS clock,
age는 monotonic clock으로 계산해 각 목적에 맞는 시간원을 사용한다.

## 10. Quaternion을 yaw로 바꾸는 이유

`Odometry` orientation은 quaternion이다. 2D 관제 지도에는 z축 회전인 yaw가 더 직접적이다.
Agent는 quaternion이 유한하고 norm이 0이 아닌지 확인하고 정규화한 뒤 yaw로 변환한다.

정규화 없이 계산하면 센서·수치 오차로 unit quaternion 조건이 깨졌을 때 잘못된 각도가
나올 수 있다.

## 11. LiDAR를 요약하는 이유

RobotStatus에 수백 개의 scan range를 복제하면 1 Hz 상태 메시지가 불필요하게 커진다.
원본 `/scan`은 필요할 때 별도로 사용하고 상태에는 다음만 넣는다.

- 유효 거리점 개수
- 가장 가까운 유효 거리
- 수신·freshness·valid 상태

유효점은 finite이며 `range_min <= value <= range_max`인 값이다.

## 12. QoS 호환성

TB1의 LDS-02 `/scan` Publisher는 BEST_EFFORT였다. Reliable subscriber가 BEST_EFFORT
Publisher를 요구하면 호환되지 않을 수 있으므로 Agent의 scan 구독은 sensor-data QoS를
사용했다.

Topic과 type이 같아도 QoS가 호환되지 않으면 데이터는 전달되지 않는다. `ros2 topic info
--verbose`로 양쪽 endpoint의 reliability, durability와 history를 확인해야 한다.

## 13. Wi-Fi signal을 어떻게 수집하는가

Linux kernel이 제공하는 `/proc/net/wireless`에서 interface, link quality와 signal dBm을
읽는다. 별도 `iwconfig` process를 1초마다 실행하지 않아 가볍고, Wi-Fi 장치가 없는
환경에서는 `wifi_valid=false`로 명확히 표현한다.

## 14. Health level과 fault code

`level`은 화면 색상이나 빠른 filtering용이고, `fault_codes`는 원인과 자동 대응용이다.

- OK: 필수 source가 fresh·valid이고 경고 없음
- WARN: battery 또는 host resource 문제
- ERROR: odom·scan missing/invalid/stale

문장 대신 `ODOM_STALE` 같은 안정적인 identifier를 쓰면 dashboard 언어와 로그 문구가
달라져도 alert rule이 깨지지 않는다.

## 15. Robot Agent와 Safety Watchdog의 차이

| 구성요소 | 책임 | 실패 시 기본 행동 |
| --- | --- | --- |
| Robot Agent | 관측, 정규화, health 상태 발행 | ERROR/fault 상태 또는 heartbeat 중단 |
| Safety Watchdog | 모터 명령 제한과 timeout 정지 | `/cmd_vel` 0 |

관측 노드에 모터 정지까지 섞으면 책임과 테스트 범위가 커진다. 이후 Fault Manager가 어떤
Agent fault에서 e-stop을 활성화할지 명시적으로 연결하는 편이 낫다.

## 자동 테스트 구성

최종 로컬 Robot Agent 테스트는 33개다.

- normalization: battery 단위, quaternion, scan 유효점
- freshness: missing, boundary, stale, 미래 timestamp
- health: OK/WARN/ERROR와 fault 우선순위
- parameter validation
- ROS graph: 초기 missing → 정상 source OK → source stale 전환
- Linux Wi-Fi status parsing과 unknown 처리
- flake8와 pep257

Custom interface 생성과 launch 설치는 실제 colcon build와 launch 시작으로 추가 확인했다.

## TB1 실제 검증 증거

- 최신 TB1 자동 테스트: 33개 통과, 실패 0
- 정상 상태: `level=0`, fault 없음, 세 source fresh·valid
- RobotStatus 발행률: 평균 1.000 Hz
- Wi-Fi: `wlan0`, 검증 snapshot -35dBm
- source 중단: odom 1초, scan 2초, battery 5초 순서로 stale
- 최종 장애 상태: `level=2`, 세 stale fault
- bringup 재시작: Agent 재시작 없이 `Robot health OK` 복구

상세 과정은
[Robot Agent stale 감지·복구 사례](../case-studies/robot-agent-stale-recovery.md)에 있다.

## 면접용 모범 답변

### 30초

“각 로봇의 배터리, odometry, LiDAR와 시스템 자원을 Robot Agent가
`fleet_interfaces/RobotStatus`로 집계하도록 만들었습니다. 단순 수신 여부뿐 아니라
freshness와 값 유효성을 분리하고 안정적인 fault code를 발행합니다. Agent가 죽으면
`offline` 메시지를 보낼 수 없기 때문에 온라인 판정은 Gateway가 1 Hz heartbeat의 마지막
수신 시각으로 하도록 설계했습니다. 현재 WSL에서 33개 테스트를 통과했습니다.”

### 1분

“웹 서버가 로봇별 원본 topic과 장애 규칙에 직접 결합되지 않도록 Robot Agent 계층을
만들었습니다. message schema는 별도 `fleet_interfaces` 패키지에 두고 실행 코드는
`robot_agent`에 분리했습니다. `/battery_state`, `/odom`, `/scan`을 구독해 1 Hz
`/fleet/robot_status`로 발행하며 received, fresh, valid를 따로 제공합니다. timeout에는
monotonic clock을 쓰고, scan은 실제 Publisher에 맞춰 BEST_EFFORT sensor QoS를
사용했습니다. 표준과 실제 TurtleBot의 배터리 단위 차이를 0~100으로 정규화하고 JSON을
고려해 NaN 대신 sentinel과 valid flag를 사용했습니다. 정책과 ROS graph를 포함한 33개
테스트가 통과했으며 다음은 TB1의 실제 source와 stale 복구를 검증하는 단계입니다.”

### 3분 답변 구조

1. 문제: Gateway가 원본 topic과 로봇별 차이를 모두 알면 결합도가 높음
2. 계약: typed `RobotStatus`와 interface package 분리
3. 상태 모델: received/fresh/valid, age, health level, stable fault codes
4. 정규화: battery 단위, quaternion→yaw, scan summary, JSON-safe unknown
5. 시간·통신: monotonic freshness, 1 Hz heartbeat, scan QoS
6. 테스트: pure policy + ROS graph + build/launch
7. 한계: TB1 실차 pending, online은 Gateway 담당, alert와 자동정지 연동 미구현
8. 다음: TB1 검증 후 FastAPI Fleet Gateway

## 면접 질문과 정답

### Q1. 왜 diagnostic_msgs 대신 custom message를 만들었나요?

`DiagnosticArray`도 가능한 선택이지만 현재 dashboard에 필요한 위치, 속도, battery와
resource를 매번 key-value로 해석하게 된다. 안정적인 fleet domain contract가 필요해
typed custom message를 선택했고, 일반 진단 도구 연동이 필요하면 DiagnosticArray를 함께
발행할 수 있다.

### Q2. source timestamp 대신 callback 시간을 쓴 이유는 무엇인가요?

서로 다른 driver의 header timestamp 품질과 clock 동기화에 의존하지 않고 “Agent가 마지막
메시지를 언제 받았는가”를 일관되게 판단하기 위해서다. 센서 생성 시각 지연을 판단하려면
향후 header age를 별도 metric으로 추가해야 한다.

### Q3. `online` 필드가 왜 없나요?

Agent나 전원이 죽으면 false를 발행할 수 없으므로 producer 자기 선언은 신뢰할 수 없다.
Gateway가 마지막 heartbeat age로 판정해야 한다.

### Q4. freshness timeout은 어떻게 정하나요?

정상 발행 주기, jitter, 네트워크 지연을 측정한 뒤 정상 간격보다 충분히 크면서 장애 감지
요구시간보다 작은 값으로 정한다. 현재 값은 초기 TB1 정책이며 실측 후 조정한다.

### Q5. 왜 scan 전체를 RobotStatus에 넣지 않았나요?

상태 heartbeat의 크기와 책임을 제한하기 위해서다. 상태에는 health에 필요한 요약만 넣고
지도나 장애물 처리는 원본 scan을 별도 소비한다.

### Q6. WARN과 ERROR 기준은 어떻게 결정했나요?

현재 관제 목적에서 odom과 scan 상실은 핵심 기능 장애라 ERROR, battery와 자원 임계치는
운영 가능한 조기 경고라 WARN으로 분류했다. 자동 주행 요구사항에 따라 정책은 변경될 수
있으며 설정·테스트로 관리해야 한다.

### Q7. RobotStatus가 계속 오면 로봇이 안전하다는 뜻인가요?

아니다. 관측 Agent가 살아 있다는 뜻일 뿐이다. 실제 field의 fresh/valid, fault code,
Safety Watchdog과 하드웨어 상태를 함께 봐야 한다.

### Q8. 다중 로봇에서 같은 topic을 써도 되나요?

여러 publisher가 `/fleet/robot_status`를 발행하고 `robot_id`로 구분하는 방식은 gateway가
한 topic을 구독하기 편하다. 네임스페이스 격리 방식도 가능하며, 보안·QoS·확장성 요구를
측정한 뒤 선택한다. 현재는 두 로봇 규모의 단일 fleet topic을 선택했다.

## 복습 문제

1. received, fresh, valid가 각각 false인 대표 상황을 하나씩 말하라.
2. Agent가 자신의 offline 상태를 직접 발행할 수 없는 이유는 무엇인가?
3. freshness 계산과 `header.stamp`에 서로 다른 clock을 쓴 이유는 무엇인가?
4. `/scan` 구독에 sensor-data QoS를 사용한 근거는 무엇인가?
5. custom interface package를 실행 package에서 분리한 장점은 무엇인가?
6. battery percentage 정규화 규칙을 설명하라.
7. unknown 숫자에 `-1.0`과 valid flag를 함께 쓰는 이유와 단점은 무엇인가?
8. Robot Agent와 Safety Watchdog의 책임 차이는 무엇인가?

### 정답

1. 미수신은 시작 후 메시지 없음, stale은 과거 수신 후 갱신 중단, invalid는 최신 메시지의
   값이 비정상인 경우다.
2. 프로세스나 전원이 죽으면 메시지를 보낼 실행 주체가 없기 때문이다.
3. ROS stamp는 데이터 시간축 정렬, monotonic은 시각 변경에 안전한 경과시간 계산용이다.
4. 실제 LDS-02 `/scan` Publisher가 BEST_EFFORT였고 compatible 구독이 필요했기 때문이다.
5. consumer가 실행 구현 없이 schema만 의존하고 interface 변경 영향을 명확히 관리한다.
6. 0~1은 100을 곱하고 1 초과~100은 유지하며 나머지는 unknown이다.
7. JSON의 NaN 문제를 피하고 validity를 명시한다. 실제 -1 값과 겹칠 수 있어 valid 확인이
   필수라는 단점이 있다.
8. Agent는 관측과 상태 발행, Watchdog은 모터 명령 제한과 정지를 담당한다.

## 프로젝트 완성 후 깊이 볼 항목

1. ROS interface 호환성과 semantic versioning
2. DDS QoS compatibility와 deadline/liveliness
3. Prometheus metric과 RobotStatus의 역할 분리
4. event-driven diagnostics와 1 Hz snapshot의 trade-off
5. clock synchronization, sensor timestamp latency
6. fleet 규모 증가 시 topic partition과 namespace
7. 상태 DB schema와 time-series retention
