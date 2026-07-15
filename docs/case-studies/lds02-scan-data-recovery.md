# 사례 연구: LDS-02 `/scan` 데이터 복구

날짜: 2026-07-15

상태: 복구 완료, 영구 하네스와 포트 설정 일반화 필요

## 한 줄 요약

ROS 2 `/scan` Publisher는 존재하지만 데이터가 없던 문제를 토픽에서 물리 배선까지 계층적으로 추적해 LDS-02 TX 선 이탈을 찾고, Raspberry Pi GPIO UART 우회로 정상 패킷과 `/scan`을 복구했다.

## 상황

TurtleBot3 Burger TB1에 ROS 2 Humble, OpenCR와 LDS-02 bringup을 구성했다. `/odom`, `/battery_state`, `/joint_states` 등은 보였고 배터리 실제 값도 수신했다. LiDAR는 물리적으로 회전했으며 `/scan` Publisher도 1개 존재했다.

그러나 `/scan` 메시지는 발행되지 않았다. 이 상태에서는 SLAM과 Nav2를 진행할 수 없었다.

## 목표

- 재설치보다 증거를 기반으로 장애 계층을 찾는다.
- 센서 데이터가 마지막으로 정상 확인되는 지점을 찾는다.
- 최소 변경으로 LiDAR 데이터 수신을 복구한다.
- 임시 해결과 영구 해결을 구분해 기록한다.

## 가설과 검증

| 순서 | 가설 | 검증 | 결과 |
| --- | --- | --- | --- |
| 1 | 토픽이 존재하지 않는다 | `ros2 topic list` | `/scan` 존재 |
| 2 | Publisher가 없다 | `ros2 topic info --verbose` | `ld08_driver` Publisher 1개 |
| 3 | QoS가 맞지 않는다 | SensorDataQoS로 echo | 10초 시간 초과 |
| 4 | 드라이버가 실행되지 않는다 | 프로세스와 노드 목록 | 드라이버 실행 중 |
| 5 | 다른 프로세스가 포트를 사용한다 | `fuser` | 드라이버만 소유 |
| 6 | 드라이버가 바이트를 읽는다 | `/proc/<PID>/io` 전후 비교 | 5초 동안 증가 없음 |
| 7 | 흐름 제어 문제다 | `crtscts`, `-crtscts` raw 검사 | 둘 다 시간 초과 |
| 8 | USB 장치가 끊어진다 | 커널 로그 | CP2102 연결 정상, 관련 오류 없음 |
| 9 | 물리 TX 경로가 끊겼다 | 커넥터와 배선 확인 | LDS-02 TX 선 이탈 발견 |

## 핵심 증거

### ROS 2 계층

```text
/scan Publisher count=1
Node=/ld08_driver
QoS Reliability=BEST_EFFORT
SCAN_ECHO_EXIT=124
```

### 프로세스와 직렬 계층

```text
rchar: 115943 -> 115943
syscr: 2415 -> 2415
read_bytes: 3510272 -> 3510272
```

```text
RAW_WITH_CRTSCTS=124
RAW_WITHOUT_CRTSCTS=124
```

드라이버는 존재했지만 센서 바이트를 받지 못했다.

## 근본 원인

LDS-02 TX 선이 커넥터에서 완전히 빠져 있었다.

```text
5V 정상  ─┐
PWM 정상 ─┼─> 센서 회전
GND 정상 ─┘
TX 단선  ───> 거리 데이터가 호스트에 도달하지 않음
```

센서 회전 여부만으로 데이터 통신 정상 여부를 판정한 것이 초기 오해였다.

## 해결

LDS-02는 TX 전용 3.3V UART를 사용하므로 센서 TX를 Raspberry Pi GPIO15 RXD에 연결했다. 운영체제의 시리얼 콘솔을 해제하고 `/dev/serial0`을 센서 전용으로 확보했다.

```text
LDS-02 TX  -> GPIO15, physical pin 10
LDS-02 GND -> GND, physical pin 6
```

GPIO UART에서 5초간 원시 데이터를 캡처했다.

```text
CAPTURE_BYTES=44105
LDS header 54 2c count=940
```

이 결과로 다음을 분리해서 증명했다.

1. LDS-02 센서 TX 출력은 정상이다.
2. Raspberry Pi GPIO UART 입력은 정상이다.
3. 115200bps 설정이 맞다.
4. 이전 CP2102 경로 또는 해당 커넥터가 문제였다.

공식 `ld08_driver`가 CP2102만 자동 선택하므로 TB1 검증을 위해 포트를 `/dev/serial0`으로 최소 수정했다. 다시 빌드한 뒤 사용자가 `/scan` 데이터 수신을 확인했다.

## 결과

- LiDAR 정상 패킷 수신 복구
- ROS 2 `/scan` 수신 복구
- 불필요한 ROS 2 재설치 회피
- 장애 계층을 물리 TX 경로로 특정
- 재현 절차와 운영상 한계를 문서화

정확한 `/scan` 발행 주기는 아직 기록하지 못했다.

## 의사결정과 대안

### 선택: Raspberry Pi GPIO UART

장점:

- 기존 Linux ROS 2 드라이버를 계속 사용할 수 있다.
- OpenCR 펌웨어 변경이 필요 없다.
- 원시 UART 검증이 쉽다.

단점:

- 시리얼 콘솔을 해제해야 한다.
- 현재 임시 점퍼는 진동에 약하다.
- 공식 드라이버의 포트 선택 방식을 수정해야 한다.

### 제외: OpenCR UART

OpenCR에는 UART 하드웨어가 있지만 기본 TurtleBot3 펌웨어가 LDS-02 패킷을 ROS 2 LaserScan으로 전달하지 않는다. 이 방법은 OpenCR 펌웨어와 Raspberry Pi 통신 프로토콜까지 수정해야 해 장애 복구 범위를 넘어선다.

### 권장 영구 조치

1. LDS-02 TX 커넥터를 올바른 크림프 단자 또는 교체 하네스로 수리한다.
2. 드라이버에 `port` launch 인자를 추가한다.
3. TB1과 TB2의 포트를 로봇별 설정으로 분리한다.
4. 시작 로그에 선택한 포트와 baud rate를 남긴다.
5. `/scan` 주기와 데이터 freshness를 상태 감시에 추가한다.

## STAR 면접 답변

### Situation

> TurtleBot3 Burger의 ROS 2 Humble bringup에서 `/odom`과 배터리는 정상인데 `/scan` Publisher만 존재하고 실제 메시지가 없었습니다.

### Task

> SLAM을 시작하기 전에 LiDAR 데이터가 끊기는 계층을 증거로 특정하고 최소 변경으로 복구해야 했습니다.

### Action

> SensorDataQoS로 메시지를 확인해 QoS 문제를 배제하고, 드라이버의 직렬 읽기 카운터와 원시 UART를 검사했습니다. CP2102에서 바이트가 전혀 들어오지 않아 물리 배선을 확인했고 LDS-02 TX 선 이탈을 발견했습니다. GPIO15 RXD로 우회하고 시리얼 콘솔을 해제한 뒤 정상 패킷을 검증했습니다.

### Result

> 5초 동안 44,105바이트와 `54 2c` 헤더 940개를 확인했고 드라이버 포트를 변경해 `/scan`을 복구했습니다. 동시에 임시 점퍼와 하드코딩이라는 한계를 기록하고 영구 하네스와 설정 분리를 후속 작업으로 정의했습니다.

## 이 사례에서 보여주는 역량

- ROS 2 토픽과 QoS 진단
- Linux 프로세스와 직렬 장치 조사
- UART 하드웨어 이해
- 계층별 가설 수립과 증거 기반 제거
- 임시 복구와 영구 개선의 구분
- 실제 수치와 실패 이력을 포함한 기술 문서화
