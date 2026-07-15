# TB1 ROS 2 Bringup 및 LDS-02 GPIO UART 구성

기준일: 2026-07-15

상태: Phase 1 기본 bringup 완료, LDS-02 포트 하드코딩은 후속 개선 필요

이 문서는 TB1의 실제 bringup 결과와 하드웨어 예외 구성을 재현하기 위한 운영 기록이다. 정확한 사설 IP, Wi-Fi 정보와 인증 정보는 기록하지 않는다.

## 확인된 구성

| 항목 | 값 |
| --- | --- |
| 로봇 | TurtleBot3 Burger |
| SBC | Raspberry Pi 4, Ubuntu 22.04 |
| ROS 2 | Humble |
| ROS 도메인 | `42` |
| OpenCR | `/dev/ttyACM0` |
| LiDAR | LDS-02 |
| LiDAR 데이터 포트 | `/dev/serial0` -> `/dev/ttyS0` |
| LiDAR UART | 115200 bps, 8N1, 흐름 제어 없음 |
| 작업공간 | `~/turtlebot3_ws` |

TB1의 LDS-02 TX 선이 원래 커넥터에서 이탈해 USB2LDS의 CP2102 경로로 데이터가 전달되지 않았다. 센서 TX를 Raspberry Pi GPIO15에 연결해 UART 수신 경로를 복구했다.

## GPIO 배선 예외

전원을 완전히 끈 상태에서만 배선을 변경한다.

```text
LDS-02 TX  -> Raspberry Pi GPIO15, 물리 핀 10(RXD)
LDS-02 GND -> Raspberry Pi GND, 물리 핀 6
```

- Raspberry Pi 물리 핀 8(TXD)은 연결하지 않는다.
- LDS-02의 5V와 PWM은 기존 공급 경로를 유지한다.
- Raspberry Pi GPIO는 3.3V 전용이므로 5V를 GPIO15에 입력하지 않는다.
- 현재 점퍼 연결은 진동에 약하므로 최종 운용 전 커넥터 또는 하네스를 수리해야 한다.

## UART 운영체제 설정

Ubuntu의 기본 시리얼 콘솔이 `/dev/serial0`을 사용하고 있어 다음 변경을 적용했다.

1. `/boot/firmware/cmdline.txt`를 백업했다.
2. `console=serial0,115200`을 제거했다.
3. `serial-getty@ttyS0.service`를 마스킹했다.
4. `enable_uart=1`은 유지했다.
5. 재부팅 후 `/dev/ttyS0`의 그룹이 `dialout`이고 포트 소유 프로세스가 없는지 확인했다.

적용 후 확인된 상태는 다음과 같다.

```text
/dev/serial0 -> ttyS0
/dev/ttyS0 owner/group: root:dialout
kernel console: console=tty1 only
UART owner process: none
```

백업 파일은 다음 경로에 남겼다.

```text
/boot/firmware/cmdline.txt.bak-before-lds-uart
```

시리얼 콘솔을 복구해야 할 때는 백업을 되돌리고 getty 마스크를 해제한 다음 재부팅한다.

```bash
sudo cp -a \
  /boot/firmware/cmdline.txt.bak-before-lds-uart \
  /boot/firmware/cmdline.txt

sudo systemctl unmask serial-getty@ttyS0.service
sudo reboot
```

## 원시 LiDAR 데이터 검증

드라이버를 실행하지 않은 상태에서 다음과 같이 GPIO UART 입력을 검증했다.

```bash
stty -F /dev/serial0 \
  115200 raw -echo -crtscts cs8 -cstopb -parenb \
  min 1 time 0

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
LDS header 54 2c count=940
```

`CAPTURE_EXIT=124`는 `timeout 5`가 5초 후 정상적으로 캡처를 종료했다는 뜻이다. 44,105바이트와 LDS-02 헤더 940개를 확인했으므로 센서 TX, GPIO15, 공통 GND, 115200bps 설정이 정상임을 검증했다.

## 현재 드라이버 예외 수정

공식 Humble `ld08_driver`는 USB 장치 목록에서 제품명이 `CP2102`인 포트를 찾아 사용한다. TB1은 GPIO UART를 사용하므로 `~/turtlebot3_ws/src/ld08_driver/src/main.cpp`에서 포트를 `/dev/serial0`으로 지정하고 CP2102 검색 결과가 이를 덮어쓰지 않도록 임시 수정했다.

수정 전 원본은 다음 경로에 백업했다.

```text
~/turtlebot3_ws/src/ld08_driver/src/main.cpp.bak-before-gpio-uart
```

수정 후 `ld08_driver`만 다시 빌드했다.

```bash
cd ~/turtlebot3_ws
source /opt/ros/humble/setup.bash

colcon build \
  --symlink-install \
  --packages-select ld08_driver

source ~/turtlebot3_ws/install/setup.bash
```

현재 하드코딩은 TB1 동작 검증용이다. 후속 작업에서 `port`를 ROS 2 launch 인자로 제공하도록 변경해야 한다.

권장 최종 형태:

```text
tb1 LDS port: /dev/serial0
tb2 LDS port: /dev/ttyUSB0
```

## Bringup

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash

export TURTLEBOT3_MODEL=burger
export LDS_MODEL=LDS-02
export ROS_DOMAIN_ID=42

ros2 launch turtlebot3_bringup robot.launch.py
```

확인된 주요 노드:

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

`/odom`과 `/battery_state`의 실제 메시지를 확인했고, 배터리 측정값은 12.06V 및 86.66%였다. GPIO UART와 드라이버 수정 후 `/scan` 메시지 수신 성공을 확인했지만 정확한 발행 주기는 기록하지 못했다.

## `/scan`은 보이지만 데이터가 없을 때

토픽 이름과 Publisher 수만으로 센서 데이터 수신을 판정하지 않는다.

확인 순서:

1. 센서 QoS로 실제 메시지를 기다린다.
2. 드라이버 프로세스와 직렬 포트 소유자를 확인한다.
3. `/proc/<PID>/io`에서 읽기 카운터가 증가하는지 확인한다.
4. 드라이버를 중지하고 원시 직렬 데이터를 검사한다.
5. 원시 데이터가 없으면 전원, GND, TX 배선과 커넥터를 확인한다.

이번 장애에서는 `/scan` Publisher가 1개였지만 메시지가 없었고, CP2102 경로의 읽기 카운터가 증가하지 않았다. 흐름 제어를 켜고 끈 원시 검사도 모두 시간 초과됐다. 물리 점검에서 LDS-02 TX 선 이탈을 발견했고 GPIO UART 우회로 정상 패킷을 확인했다.

## 다음 개선

- `ld08_driver`에 `port` 매개변수를 추가하고 하드코딩 제거
- TB1과 TB2의 포트를 로봇별 설정으로 분리
- GPIO 점퍼를 진동에 견디는 크림프 단자 또는 교체 하네스로 수리
- systemd 자동 시작은 수동 bringup과 안전 주행 검증 후 적용
