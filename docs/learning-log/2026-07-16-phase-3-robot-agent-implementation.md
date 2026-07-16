# 2026-07-16 Phase 3 Robot Agent 구현 일지

단계: Phase 3

진행 상태: 완료 - WSL·TB1 최신 자동 테스트 33개와 TB1 정상·장애·복구 검증 완료

브랜치: `feat/phase-3-robot-agent`

## 목표

TB1의 battery, odom, scan freshness와 Raspberry Pi 자원을 하나의 typed 상태 메시지로
구조화한다. 이후 Gateway가 로봇별 원본 topic을 직접 해석하지 않게 한다.

## 구현 내용

### `fleet_interfaces`

`RobotStatus.msg` custom interface를 추가했다. identity, 전체 health, 세 source의
received/fresh/valid와 age, battery·planar odom·scan 요약, Linux resource와 fault code를
포함한다.

### `robot_agent`

- `/battery_state`, `/odom`, `/scan` 구독
- 1 Hz `/fleet/robot_status` 발행
- monotonic clock 기반 freshness
- 0~1과 0~100 battery percentage 정규화
- quaternion 정규화와 yaw 변환
- 유효 LiDAR point 개수와 최단 거리 계산
- `psutil` 기반 CPU, memory, disk, load, uptime 수집
- OK/WARN/ERROR와 stable fault code 생성
- TB1 YAML과 launch 파일 추가

## 주요 설계 결정

1. interface와 실행 package를 분리했다.
2. source 상태를 received/fresh/valid로 나눴다.
3. Agent의 online 자기 선언 대신 Gateway heartbeat 판정을 선택했다.
4. unknown 숫자는 JSON 호환을 위해 `-1.0`과 valid flag로 표현했다.
5. 실제 TB1 endpoint와 호환되도록 scan 구독은 sensor-data QoS를 사용했다.
6. Robot Agent는 관측만 담당하고 모터 정지는 Safety Watchdog에 유지했다.

## WSL 검증 결과

의존성과 package discovery:

```text
All system dependencies have been satisfied
fleet_interfaces  (ros.ament_cmake)
robot_agent       (ros.ament_python)
safety_watchdog   (ros.ament_python)
```

빌드:

```text
Starting >>> fleet_interfaces
Finished <<< fleet_interfaces
Starting >>> robot_agent
Finished <<< robot_agent
Summary: 2 packages finished
```

Robot Agent 테스트:

```text
collected 29 items
test_flake8.py: passed
test_model.py: 26 passed
test_node.py: passed
test_pep257.py: passed
29 passed, 2 warnings
```

통합 테스트는 초기 missing ERROR, 세 source를 받은 OK, timeout 이후 ODOM/SCAN stale
ERROR 전환까지 확인했다.

## 발생한 문제와 처리

### WSL clock skew warning

Custom interface 빌드에서 파일 시간이 약 1~2초 미래라는 `Clock skew detected` 경고가
나왔다. Windows mount와 WSL clock의 짧은 차이에서 발생했으며 build와 생성물, 29개
테스트는 모두 성공했다. 기능 결함으로 보지 않고 기록만 남겼다. 반복되거나 차이가 커지면
WSL 시간 동기화와 build directory timestamp를 점검한다.

### 자동 launch 검증 명령 종료 시간 초과

PowerShell에서 WSL bash의 `$AGENT_PID`와 `$RESULT`가 예상보다 먼저 확장되어 종료할 PID가
비어 있었다. launch 자체는 다음 로그로 성공을 확인했다.

```text
Robot Agent ready: robot_id=tb1, output=/fleet/robot_status, rate=1.00Hz
Robot health level=2: ODOM_NOT_RECEIVED, SCAN_NOT_RECEIVED,
BATTERY_NOT_RECEIVED
```

남은 `robot_agent`와 launch process를 확인해 종료했다. 기능 테스트는 pytest ROS graph
통합 테스트로 이미 통과했으며, 실차 launch는 TB1 절차에서 다시 확인한다.

### Phase 2 문서가 수정으로 표시됨

내용 hash가 HEAD와 같고 diff도 없었지만 Windows 줄바꿈·timestamp 상태 때문에 수정으로
표시됐다. 파일을 다시 index해 거짓 변경 표시를 제거했고 Phase 3 commit에는 포함하지
않았다.

## 현재까지 완료한 것

- [x] custom interface 설계와 생성
- [x] Robot Agent 구현
- [x] pure normalization·health 테스트
- [x] ROS graph 통합 테스트
- [x] dependency와 package discovery 확인
- [x] launch 설치·시작 로그 확인
- [x] TB1 정상 실제 상태 확인
- [x] source 중단 stale 전환 확인
- [x] TB1 결과 문서화

## 다음 작업

Phase 3 PR을 최종 리뷰하고 main에 squash merge한다. Phase 4에서는 Fleet Gateway가
RobotStatus를 구독하고 heartbeat age로 online/offline을 판단하며 FastAPI REST와
WebSocket으로 최소 웹 화면에 전달한다.

## 원본 요구사항 재검토 후 보강

프로젝트 원본 Phase 3 수집 목록과 구현을 다시 대조해 Wi-Fi 신호와 source별 실제 마지막
수신 시각이 빠진 것을 발견했다. 다음을 추가했다.

- battery, odom, scan의 ROS clock 기반 `last_received`
- monotonic `age_sec`와 실제 시각의 역할 분리
- `/proc/net/wireless` 기반 interface, signal dBm, quality percent
- Wi-Fi가 없는 환경의 `wifi_valid=false`와 JSON-safe unknown
- wireless parser와 timestamp 통합 assertion 4개

최종 WSL 결과:

```text
collected 33 items
33 passed, 2 warnings
Summary: 33 tests, 0 errors, 0 failures, 0 skipped
```

TB1에서 이미 확인한 29개는 보강 전 revision의 실제 결과로 유지한다. 최신 revision
`86047b7`을 TB1에 배포한 뒤 33개도 오류와 실패 없이 통과했다.
