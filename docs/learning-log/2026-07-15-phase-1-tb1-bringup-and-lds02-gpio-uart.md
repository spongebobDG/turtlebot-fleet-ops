# 학습 일지: Phase 1 TB1 Bringup과 LDS-02 GPIO UART 복구

날짜: 2026-07-15

단계: Phase 1 - tb1 단독 Bringup

진행 상태: 기본 bringup과 LiDAR 수신 복구 완료, 드라이버 포트 설정 일반화 필요

## 오늘의 목표

TB1에서 ROS 2 Humble, OpenCR, TurtleBot3 Burger와 LDS-02를 단독으로 bringup하고 `/odom`, `/battery_state`, `/scan` 등 주요 토픽의 실제 데이터 수신을 확인한다.

## 왜 이 작업을 했는가

다중 로봇과 웹 관제를 시작하기 전에 로봇 한 대의 센서와 구동 기반이 정상임을 증명해야 한다. 단일 로봇에서 검증하지 않은 문제를 namespace, DDS, 웹 서버 문제와 동시에 다루면 원인 범위가 지나치게 넓어진다.

이번 작업에서는 특히 ROS 2 토픽 이름이 보이는 것과 실제 센서 데이터가 흐르는 것이 다르다는 점을 확인했다.

## 진행한 활동

1. TB1에 ROS 2 Humble Base와 TurtleBot3/LDS-02 소스 패키지를 준비했다.
2. TurtleBot3 모델을 Burger, LiDAR 모델을 LDS-02로 설정했다.
3. OpenCR Burger 펌웨어를 갱신했다.
4. OpenCR과 CP2102 직렬 장치의 권한을 확인했다.
5. TurtleBot3 bringup에서 노드와 토픽 목록을 확인했다.
6. `/odom`과 `/battery_state`의 실제 메시지를 확인했다.
7. `/scan` Publisher는 있지만 메시지가 발행되지 않는 장애를 계층별로 조사했다.
8. LDS-02 TX 선이 커넥터에서 이탈한 물리 결함을 발견했다.
9. Raspberry Pi GPIO15 UART를 활성화하고 센서 TX를 직접 수신했다.
10. 공식 `ld08_driver`가 CP2102만 선택하는 부분을 TB1 검증용으로 수정했다.
11. 다시 빌드하고 `/scan` 수신 성공을 확인했다.

## 확인된 환경

| 항목 | 결과 |
| --- | --- |
| 로봇 | TurtleBot3 Burger |
| LiDAR | LDS-02 |
| ROS 2 | Humble |
| ROS_DOMAIN_ID | `42` |
| OpenCR | `/dev/ttyACM0` |
| 기존 LiDAR 변환기 | CP2102, `/dev/ttyUSB0` |
| 복구된 LiDAR 경로 | GPIO15, `/dev/serial0` -> `/dev/ttyS0` |
| TurtleBot3 소스 | `90a68bd` |
| ld08_driver 소스 | `4c52869` |

## OpenCR 펌웨어 갱신

처음 받은 `opencr_update.tar.bz2` 파일은 이름과 달리 bzip2 형식이 아니어서 압축 해제에 실패했다. 직접 받은 원본을 확인한 결과 gzip 매직 바이트 `1f 8b`를 가진 gzip 파일이었다.

```bash
file opencr_update.raw.tar.bz2
head -c 4 opencr_update.raw.tar.bz2 | xxd
sha256sum opencr_update.raw.tar.bz2
```

확인된 SHA-256:

```text
df13eba4e915c6ab4ed225329c8a02ebd69cd5655675e9d60f72214c4d029518
```

실제 형식에 맞게 gzip으로 해제한 뒤 Burger 펌웨어를 기록했다.

```bash
tar -xzf opencr_update.raw.tar.bz2
cd opencr_update
./update.sh /dev/ttyACM0 burger.opencr
```

실제 결과:

```text
OpenCR R1.0
firmware V230127R1
flash_erase OK
flash_write OK
CRC Check OK
Download OK
jump_to_fw OK
OPENCR_UPDATE_EXIT=0
```

## Bringup 1차 결과

확인된 노드:

```text
/diff_drive_controller
/ld08_driver
/robot_state_publisher
/turtlebot3_node
```

확인된 주요 토픽:

```text
/battery_state
/cmd_vel
/imu
/joint_states
/odom
/scan
/sensor_state
/tf
/tf_static
```

`/odom` 메시지와 다음 배터리 상태를 확인했다.

```text
voltage: 12.059999465942383
percentage: 86.65999603271484
present: true
```

## 발생한 문제: `/scan` Publisher는 있지만 메시지가 없음

`ros2 topic info /scan --verbose`에서는 `ld08_driver` Publisher가 1개 보였다. 하지만 센서 QoS로 메시지 한 개를 기다려도 시간 초과됐다.

```bash
timeout 10 ros2 topic echo \
  /scan sensor_msgs/msg/LaserScan \
  --qos-profile sensor_data \
  --once

echo "SCAN_ECHO_EXIT=$?"
```

실제 결과:

```text
SCAN_ECHO_EXIT=124
```

이는 QoS 화면 표시 문제가 아니라 실제 스캔 메시지가 없다는 증거였다.

## 직렬 계층 진단

`ld08_driver`가 `/dev/ttyUSB0`을 소유하고 있었지만 프로세스의 읽기 카운터가 5초 동안 증가하지 않았다.

```text
rchar: 115943 -> 115943
syscr: 2415 -> 2415
read_bytes: 3510272 -> 3510272
```

커널 로그에는 CP2102 연결이 정상적으로 보였고 관련 USB 오류나 연결 해제는 없었다. 흐름 제어를 켠 경우와 끈 경우 모두 5초 동안 원시 바이트를 받지 못했다.

```text
RAW_WITH_CRTSCTS=124
RAW_WITHOUT_CRTSCTS=124
```

따라서 ROS 2, QoS, 장치 권한과 baud rate보다 아래 계층인 센서 TX 배선 경로를 점검했다.

## 물리 원인 발견

LDS-02의 TX 선이 커넥터에서 완전히 이탈해 있었다. 5V, PWM과 GND는 유지되어 센서는 회전했지만 측정 데이터 출력만 CP2102에 도달하지 않았다.

처음에는 빠진 선을 RX로 오인해 Raspberry Pi TXD에 임시 연결했지만 올바른 신호 방향은 다음과 같다.

```text
LDS-02 TX(출력) -> 수신 장치 RXD(입력)
```

출력인 TX를 다른 TXD에 연결하면 안 된다.

## Raspberry Pi GPIO UART 우회 검증

LDS-02는 TX 전용 3.3V UART를 사용하므로 센서 TX를 Raspberry Pi GPIO15, 물리 핀 10의 RXD에 연결했다. GND도 공통으로 연결했고 Raspberry Pi TXD는 사용하지 않았다.

```text
LDS-02 TX  -> GPIO15, physical pin 10
LDS-02 GND -> GND, physical pin 6
```

UART 조사 결과는 다음과 같았다.

```text
/dev/serial0 -> ttyS0
enable_uart=1
kernel console=ttyS0,115200
```

`/dev/serial0`이 Linux 로그인 콘솔로 사용 중이어서 `/boot/firmware/cmdline.txt`를 백업하고 `console=serial0,115200`을 제거했다. 처음에는 실행 중인 장치명인 `ttyS0`만 제거하려 했으나 설정 파일에는 별칭 `serial0`으로 기록돼 있어 제거되지 않았다. 실제 파일 값을 기준으로 명령을 바로잡았다.

```text
backup=/boot/firmware/cmdline.txt.bak-before-lds-uart
removed=console=serial0,115200
masked=serial-getty@ttyS0.service
```

재부팅 후 확인 결과:

```text
/dev/serial0 -> ttyS0
/dev/ttyS0 owner/group=root:dialout
kernel console=console=tty1
UART owner=none
```

## 원시 패킷 검증

첫 번째 짧은 읽기에서는 4바이트만 수신됐다.

```text
00 c6 00 00
RAW_GPIO=0
```

이 결과만으로는 정상 LDS 패킷임을 증명할 수 없었다. 5초 동안 전체 입력을 저장하고 LDS-02 헤더 `54 2c`의 개수를 확인했다.

```bash
timeout 5 dd \
  if=/dev/serial0 \
  of=/tmp/lds-gpio.raw \
  bs=4096 \
  status=none

echo "CAPTURE_BYTES=$(wc -c < /tmp/lds-gpio.raw)"

xxd -p /tmp/lds-gpio.raw |
  tr -d '\n' |
  grep -o '542c' |
  wc -l
```

실제 결과:

```text
CAPTURE_EXIT=124
CAPTURE_BYTES=44105
LDS header count=940
```

`124`는 `timeout`이 지정된 5초 후 캡처를 종료했다는 의미다. 충분한 바이트 수와 반복되는 정상 헤더를 근거로 센서와 GPIO UART 경로가 정상임을 확인했다.

## 드라이버 수정과 최종 결과

공식 Humble `ld08_driver`는 USB 장치 목록에서 제품 문자열에 `CP2102`가 포함된 포트를 자동 선택한다. 런치 인자로 전달되는 포트를 실제 노드가 사용하지 않으므로 GPIO UART를 그대로 선택할 수 없었다.

TB1 동작 검증을 위해 `src/main.cpp`를 백업한 뒤 포트를 `/dev/serial0`으로 지정하고 CP2102 검색 결과가 포트를 덮어쓰지 않도록 최소 수정했다.

```text
backup=src/main.cpp.bak-before-gpio-uart
TB1 LiDAR port=/dev/serial0
```

`ld08_driver`만 다시 빌드하고 TurtleBot3 전체 bringup을 실행했다. 사용자가 `/scan` 데이터 수신 성공을 확인했다. 정확한 `/scan` 주기와 메시지 표본은 기록하지 못했다.

이 수정은 검증용 하드코딩이므로 최종 설계가 아니다. 후속 작업에서 `port`를 launch 인자로 받아 TB1과 TB2의 차이를 설정으로 분리한다.

## 배운 점 / 메모

- ROS 2 토픽과 Publisher가 보인다고 실제 메시지가 흐른다는 뜻은 아니다.
- 진단은 토픽, 드라이버, 운영체제 장치, UART 바이트, 물리 배선 순서로 계층을 내려가야 한다.
- 센서가 회전한다는 사실은 전원과 PWM만 증명할 뿐 데이터 TX의 정상 여부를 증명하지 않는다.
- UART는 송신 장치 TX를 수신 장치 RX에 연결하고 공통 GND가 필요하다.
- `/dev/serial0` 같은 별칭과 실제 장치 `/dev/ttyS0`를 구분해야 한다.
- `timeout`의 종료 코드 124는 문맥에 따라 장애가 아니라 의도된 검사 종료일 수 있다.
- 짧은 바이트 몇 개보다 데이터량과 정상 패킷 헤더 반복을 함께 확인해야 한다.
- 하드웨어 예외를 코드에 영구 하드코딩하지 말고 로봇별 설정으로 분리해야 한다.

## 완료 체크리스트

- [x] ROS 2 Humble 동작 확인
- [x] TurtleBot3 Burger 및 LDS-02 패키지 확인
- [x] OpenCR Burger 펌웨어 갱신
- [x] OpenCR 및 직렬 포트 권한 확인
- [x] `ROS_DOMAIN_ID=42` 적용
- [x] TurtleBot3 주요 노드 확인
- [x] `/odom` 실제 메시지 확인
- [x] `/battery_state` 실제 메시지 확인
- [x] `/joint_states`, `/tf`, `/tf_static`, `/cmd_vel` 토픽 존재 확인
- [x] LDS-02 TX 물리 결함 식별
- [x] GPIO UART 원시 패킷 검증
- [x] `/scan` 데이터 수신 복구
- [ ] `/scan` 발행 주기 수치 기록
- [ ] LiDAR 점퍼 배선을 영구 하네스로 수리
- [ ] 드라이버 포트를 launch 인자로 일반화
- [ ] 바퀴 수동 주행과 안전 정지는 Phase 2에서 검증

## 복습 문제와 정답

### 1. `/scan`의 Publisher 수가 1인데도 센서가 정상이라고 단정할 수 없는 이유는 무엇인가?

정답: 노드가 토픽 Publisher를 생성한 것만 확인할 수 있고 실제 LaserScan 메시지 발행 여부는 확인하지 못하기 때문이다.

이유: 드라이버가 직렬 포트를 열었더라도 센서 바이트를 받지 못하면 Publisher만 존재하고 메시지는 없을 수 있다.

### 2. LDS-02가 회전했는데도 `/scan` 데이터가 없었던 이유는 무엇인가?

정답: 전원, PWM과 GND는 연결돼 있었지만 데이터 출력 TX 선이 빠져 있었기 때문이다.

이유: 모터 회전 경로와 거리 데이터 UART 경로는 서로 다른 신호다.

### 3. UART에서 LDS-02 TX를 Raspberry Pi TXD가 아니라 RXD에 연결하는 이유는 무엇인가?

정답: LDS-02 TX는 출력이고 Raspberry Pi RXD는 입력이기 때문이다.

이유: UART는 한 장치의 TX를 상대 장치의 RX에 교차 연결한다. 출력끼리 연결하면 통신하지 못하고 전기적 충돌 위험도 생긴다.

### 4. 원시 캡처에서 `CAPTURE_EXIT=124`인데도 성공으로 판단한 이유는 무엇인가?

정답: `timeout 5`가 의도대로 5초 후 계속 실행 중인 `dd`를 종료했기 때문이다.

이유: 종료 코드만 보지 않고 44,105바이트 수신과 정상 헤더 940개라는 검사 내용을 함께 판단했다.

### 5. `/dev/serial0`을 사용하는데 설정 파일에서는 왜 `console=serial0,115200`을 제거했는가?

정답: Linux 시리얼 콘솔이 같은 UART를 사용하면 LiDAR 드라이버와 포트를 공유할 수 없기 때문이다.

이유: `/dev/serial0`은 실제 `/dev/ttyS0`을 가리키는 별칭이며, 커널 콘솔과 센서 입력이 같은 장치를 동시에 사용하면 데이터가 섞이거나 권한과 점유 문제가 생긴다.

### 6. 현재 `/dev/serial0` 하드코딩을 최종 구현으로 두면 안 되는 이유는 무엇인가?

정답: TB2처럼 정상 USB2LDS를 사용하는 로봇은 `/dev/ttyUSB0`이 필요하고 장치별 차이가 코드에 고정되기 때문이다.

이유: 포트를 launch 인자나 로봇별 설정으로 분리해야 같은 코드를 여러 로봇에서 재사용하고 변경을 추적할 수 있다.

## 다음에 할 일

1. `ld08_driver`가 `port` launch 인자를 실제로 사용하도록 수정한다.
2. TB1은 `/dev/serial0`, TB2는 `/dev/ttyUSB0`을 설정으로 분리한다.
3. 수정 결과를 다시 빌드하고 `/scan` 주기와 메시지 표본을 기록한다.
4. Phase 2에서 낮은 속도로 바퀴 수동 제어, 정지와 안전 절차를 검증한다.
5. TB1의 임시 GPIO 점퍼를 진동에 견디는 영구 하네스로 교체한다.

## 관련 커밋

이 문서를 포함하는 커밋에서 갱신한다.
