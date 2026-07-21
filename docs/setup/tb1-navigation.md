# TB1 매핑·Nav2·웹 목적지 운영 및 검증

이 절차는 TB1 한 대를 빈 실습 공간에서 저속으로 검증한다. 작업자는 시험 내내
전원 스위치에 손이 닿는 위치에 있어야 한다. 아래 체크박스는 실제 측정 뒤에만
완료로 바꾼다. 2026-07-19의 체크 표시는 TB1 실차 증거에 근거하며, 재시험 때도 같은
fail-closed 순서를 사용한다.

저장소 자동 검증 기준선은 Draft PR #7의
[Actions 실행 29601662765](https://github.com/spongebobDG/turtlebot-fleet-ops/actions/runs/29601662765)이다.
초기 기준선은 Ubuntu 22.04 ROS 2 Humble에서 5개 패키지 빌드, 격리 domain 142의
183개 테스트와
robotless Nav2 stack smoke, 서로 다른 두 DDS domain 사이의 Zenoh 1.9.0 action smoke,
작업·fault smoke가 통과한 결과다. 최종 구조에는 C++ watchdog guard 패키지를 추가해
6개 패키지 격리 Humble 테스트와 TB1 실차 회귀를 통과했다. 최신 source-scoped 기준은 관제 PC
191개와 TB1 현재 다섯 robot 패키지 144개다. robotless 결과는
실차의 센서 정합, 물리
정지시간, 실제 LAN 단절 또는 자원 사용량을 대신하지 않는다.

## 로봇 없는 자동 통합 검증

Ubuntu 22.04와 ROS 2 Humble에서 workspace를 빌드한 뒤 실행한다.

```bash
ROS_DOMAIN_ID=142 bash infra/navigation/run-robotless-navigation-smoke.sh
bash infra/zenoh/install-standalone.sh
bash infra/navigation/run-robotless-zenoh-action-smoke.sh
```

script는 임시 free map과 TF·odom·scan·AMCL·RobotStatus fixture를 만들고 실제
Nav2·AMCL·navigation agent·arbiter·watchdog policy·C++ guard·Gateway를 실행한다.
웹과 같은 REST
경로로 초기 위치, 목표 성공, 명시적 취소와 e-stop 후 무재개를 확인한다. 마지막에는
`/cmd_vel`의 유일한 publisher, 중간 Nav2 publisher, `0.05 m/s`·`0.3 rad/s` 상한과
최종 0을 검사한다.

Zenoh script는 robot domain 160과 control domain 161을 사용해 DDS 직접 통신을 막고,
두 bridge의 TCP 경로만으로 `NavigateRobot` 목표·feedback·성공 result·cancel과
`NavigationLease`·`NavigationStatus`를 검증한다. fixture가 사용하는 loopback TCP는
실제 LAN 또는 Gateway/bridge 단절 뒤 2.5초 이내 물리 정지를 대신하지 않는다.

이 검증은 launch/parameter/lifecycle/action/REST/topic 연결을 실제 Humble graph에서
검사한다. LiDAR와 지도 정합, 바퀴 미끄러짐, 물리 정지시간, Zenoh 단절, systemd 장애
복구와 Raspberry Pi 자원 사용량은 아래 실차 절차에 남는다.

[Nav2 Getting Started](https://docs.nav2.org/getting_started/index.html)는 TurtleBot3 Gazebo
simulation을 사용하고, [ROBOTIS simulation 안내](https://emanual.robotis.com/docs/en/platform/turtlebot3/simulation/)도
센서가 없는 fake node보다 SLAM·Navigation에는 Gazebo를 권장한다. 이 CI fixture는
Gazebo 대체품이 아니라 ROS graph와 안전 계약을 빠르고 결정적으로 검사하는 계층이다.

## 1. 전제 조건

- TB1: Ubuntu 22.04, ROS 2 Humble, domain 42, CycloneDDS
- 관제 WSL과 TB1: Zenoh 1.9.0 브리지 및 Phase 4 Gateway
- `tb1-bringup`, `tb1-safety-watchdog`, `tb1-robot-agent` 정상
- TurtleBot3 Burger Nav2와 SLAM Toolbox 설치
- 바닥이 평평하고 사람·장애물이 없는 시험 공간

2026-07-18 현재 관제 PC는 WSL2 Ubuntu 22.04, ROS 2 Humble Desktop, CycloneDDS,
Nav2·SLAM Toolbox, Zenoh 1.9.0, Gateway, Windows 로그인 자동 시작과 keepalive까지
검증됐다. TB1 연결 전에는 로봇 부재 경고를 허용하는 점검이 통과해야 한다.

```powershell
cd C:\projects\turtlebot-fleet-ops
powershell -ExecutionPolicy Bypass -File scripts\control-pc\test_tb1_connection.ps1
```

TB1 전원과 LAN을 연결한 직후에는 같은 검사에 `-RequireRobot`을 추가한다. 실패하면
실차 명령을 보내지 않고 LAN·SSH·TB1 Zenoh부터 복구한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\control-pc\test_tb1_connection.ps1 `
  -RequireRobot
```

TB1에서 저장소를 빌드한다.

```bash
cd ~/turtlebot-fleet-ops
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
rosdep install --from-paths robot control --ignore-src -r -y
colcon build --base-paths robot control --symlink-install
source install/setup.bash
```

## 2. 공통 안전 확인

```bash
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 topic info /cmd_vel --verbose
ros2 topic echo /fleet/safety_status --once
```

정상 운용에서 `/cmd_vel` publisher의 node name은 C++ guard인 `/safety_watchdog`
하나여야 한다. Python 정책 노드는 `/safety_watchdog_policy`이며
`/safety/watchdog_cmd_vel`까지만 발행한다. Nav2, teleop, arbiter 또는 policy가
`/cmd_vel`에 직접 보이면 시험을 중단한다.

## 3. 매핑 프로필

수동 실행 시 기존 navigation 프로필을 먼저 정지한다.

```bash
systemctl --user stop tb1-navigation.service 2>/dev/null || true
ros2 launch navigation_agent tb1_mapping.launch.py
```

launch는 원본 `/scan`을 360개 각도 bin의 `/scan_normalized`로 재투영하고 SLAM Toolbox에는
정규화 토픽만 연결한다. 실제 LDS-02에서 관찰한 207~219개 가변 배열이 다시 SLAM 입력을
깨뜨리지 않는지 먼저 확인한다. TB1의 원본 LDS-02 angle 0은 실제 `base_link +X` 전방과
반대이므로 정규화 설정의 `angle_offset_rad=π`가 각 샘플을 물리 차체 기준으로 회전시킨다.
Gateway도 원본 `/scan` overlay에 같은 π를 적용한다. 한쪽만 바꾸면 지도 정합은 높아도 웹
화살표와 실제 이동이 다시 반대가 될 수 있으므로 두 설정은 하나의 센서 외부각 계약이다.

```bash
ros2 topic hz /scan_normalized
ros2 topic echo /scan_normalized --once --field ranges | head
ros2 topic info /cmd_vel --verbose
```

잔류 키 입력을 막기 위해 일반 teleop 대신
[보호 이동 기반 매핑 절차](tb1-supervised-mapping.md)의 dry-run, 5cm 직진과 30도 회전을
반복한다. `supervised_motion`은 `/motion/manual/cmd_vel`만 발행하고 arbiter와 기존
watchdog을 거친다. 각 구간 뒤 `/map`, pose graph, odom과 최종 e-stop을 확인한다.
`scan_queue_size=10`과 `minimum_travel_distance=0.05`는 실제 TB1에서 검증한 기준값이다.
지도 loop closure가 안정된 뒤 저장한다.

```bash
cd ~/turtlebot-fleet-ops
infra/navigation/save-tb1-map.sh
ls -lh ~/.local/share/turtlebot-fleet-ops/maps/tb1/
```

최소한 `map.yaml`, map image, SLAM Toolbox pose graph 파일이 있어야 한다. 이 디렉터리는
저장소 밖이며 실제 공간 지도는 commit하지 않는다. 저장 script는 trinary unknown 셀이
free로 잘못 재분류되지 않게 `free_thresh=0.196`, `occupied_thresh=0.65`로 저장하고,
known cell 비율과 pose graph 산출물을 `validate_map`으로 다시 검사한다.

## 4. 주행 프로필

매핑 프로필과 teleop을 완전히 끝낸 뒤 실행한다.

```bash
systemctl --user stop tb1-mapping.service 2>/dev/null || true
cd ~/turtlebot-fleet-ops
infra/navigation/start-tb1-navigation.sh
```

다음 graph를 확인한다.

```bash
ros2 action info /navigate_to_pose
ros2 action info /tb1/navigation/navigate
ros2 service type /tb1/navigation/set_initial_pose
ros2 service type /tb1/navigation/set_motion_mode
ros2 topic info /motion/navigation/cmd_vel --verbose
ros2 topic info /safety/cmd_vel_in --verbose
ros2 topic info /cmd_vel --verbose
ros2 topic echo /fleet/navigation_status
```

처음에는 `LOCALIZING` 또는 `UNAVAILABLE`이 정상이다. 웹에서 초기 위치를 지정하고
그 이후의 새 `/amcl_pose`가 들어와야 `READY`가 된다.

## 5. 웹 초기 위치와 목적지

관제 PC에서 기존 Gateway와 Zenoh 브리지를 실행하고 `http://localhost:8000`을 연다.

1. 지도에서 `초기 위치` 모드를 선택한다.
2. 로봇의 대략 위치를 클릭하고 진행 방향으로 드래그한다. 붉은 LiDAR endpoint는 선택 후보를
   따라 움직이므로 지도 벽과의 오차를 바로 볼 수 있다. 원은 로봇 중심이고 드래그 끝의
   삼각형은 실제 차체의 앞, 즉 `base_link +X`여야 한다.
3. `LiDAR 자동 정렬`을 누르고 5~6초 기다린다. `정렬 일치`와 `지도 내부` 지표가 녹색으로
   표시되는지, 붉은 점이 지도 벽에 실제로 겹치는지 확인한다.
4. `초기 위치 적용`을 누른다. 자동 정렬을 거치지 않았거나 match 35%·지도 내부 70% 기준을
   만족하지 않으면 버튼 또는 서버 `422`에서 거부된다.
5. 새 `/amcl_pose` 뒤 `localization_ready=true`인지 확인한다. e-stop 중이면 상태는 `IDLE`이며
   `Localization ready; waiting for motion safety rearm`이 정상이다. e-stop을 해제하고 안전 재무장한
   경우에만 `READY`가 된다.
6. `목적지` 모드에서 가까운 자유 셀을 클릭·드래그한다.
7. 최소 LiDAR 거리가 0.19m 이상인지 확인한다. 이는 TB1 반경 0.14m에 요청한 외곽 여유
   0.05m를 더한 값이다. 현재 pose도 known free cell이어야 한다.
8. `목적지 전송` 후 거리, 경과시간, 예상시간, recovery와 lease age를 관찰한다.

스캔 외부각 설정을 변경하거나 navigation agent를 재시작한 뒤에는 이전 AMCL pose를 재사용하지
않는다. e-stop을 유지하고 `LiDAR 자동 정렬`과 초기 위치 적용을 다시 수행한 다음, 삼각형 방향과
실제 차체 앞이 같은지 작업자가 확인해야 한다. 그 확인 전에는 목적지를 보내지 않는다.

로봇 상태 카드의 위치와 방향은 localization 이후 `navigation.current`의 `map` 좌표를 표시한다.
아직 map pose가 없을 때만 `odom` 좌표로 fallback하며 카드 라벨에 사용 frame을 함께 표시한다.

WARN 로봇은 첫 요청이 409로 거부되고 fault 목록 확인 dialog가 나온다. 작업자가
확인한 경우에만 두 번째 요청이 `confirm_warnings=true`로 전송된다. 새 목표는 기존
목표를 자동 교체하지 않는다.

직접 API를 확인할 때는 다음 형태를 사용한다.

```bash
curl http://localhost:8000/api/robots/tb1/map
curl http://localhost:8000/api/robots/tb1/scan
curl -X POST http://localhost:8000/api/robots/tb1/localization/align-pose \
  -H 'content-type: application/json' \
  -d '{"x":0.0,"y":0.0,"yaw":0.0}'
curl -X PUT http://localhost:8000/api/robots/tb1/localization/initial-pose \
  -H 'content-type: application/json' \
  -d '{"x":0.0,"y":0.0,"yaw":0.0}'
curl -X POST http://localhost:8000/api/robots/tb1/navigation/goals \
  -H 'content-type: application/json' \
  -d '{"x":0.5,"y":0.0,"yaw":0.0,"confirm_warnings":false}'
```

좌표는 실제 지도의 자유 셀 값으로 바꾼다. 지도 밖, unknown, occupied 또는 현재 LiDAR와 정합되지
않는 pose는 422여야 한다. 자동 정렬 결과는 후보일 뿐이며 붉은 점과 실제 로봇 방향을 눈으로
확인한 뒤 적용한다.

## 6. systemd 프로필 설치

```bash
mkdir -p ~/.config/systemd/user
cp infra/systemd/user/tb1-mapping.service ~/.config/systemd/user/
cp infra/systemd/user/tb1-navigation.service ~/.config/systemd/user/
systemctl --user daemon-reload
```

둘 중 하나만 enable한다.

```bash
systemctl --user enable --now tb1-navigation.service
systemctl --user status tb1-navigation.service
systemctl --user is-active tb1-mapping.service
```

두 번째 명령은 `active`, 세 번째 명령은 `inactive`여야 한다. 프로필 전환은 다음처럼
명시적으로 수행한다.

```bash
systemctl --user stop tb1-navigation.service
systemctl --user start tb1-mapping.service
```

## 7. 실차 완료 체크리스트

### 실차 수용 시험 결과

2026-07-18에는 새 관제 PC의 SSH·Zenoh 연결, 배포, 217개 robot 테스트와 정지 상태를
사전검증했다. 2026-07-19에는 빈 공간에서 아래 동적 체크리스트를 수행하고 watchdog
구조 보강 후 당시 전체 build 결과 기준 223개가 통과했다. 후속 감사에서 삭제된
`fleet_navigation`의 과거 build 결과가 합계에 섞였음을 확인했으므로 현재 완료 수치는
source-scoped 144개를 사용한다.

| 항목 | 실제 결과 |
| --- | --- |
| 지도 | 58×96, 0.05 m/cell, known 2,971, known ratio 0.5336 |
| 위치추정 | 직접 scan-map 정합과 AMCL 차이 4.4 cm, 정지 12초 뒤에도 READY latch 유지 |
| 짧은 목표 | 약 18.7 cm 및 장애물 제거 후 약 9.6 cm, recovery 0으로 성공 |
| 속도 | navigation·arbiter·guard 모두 최대 0.05 m/s, 0.3 rad/s |
| e-stop | 비영점→0 0.003초, API 요청부터 안전 terminal 0.983초, 무재개 |
| Zenoh 단절 | 0 출력 2.112초, `LEASE_EXPIRED` 2.263초, 재연결 후 무재개 |
| explicit cancel | 취소 요청부터 안전 terminal 0.978초 |
| guard 장애 | 프로세스 재생성 약 0.105초, 관찰된 첫 0 0.955초, 목표 취소·무재개 |
| 자원 10분 | CPU 평균 69.14%/최대 85.20%, 메모리 평균 20.63%/최대 20.70% |

지도 산출물은 `~/.local/share/turtlebot-fleet-ops/maps/tb1/`에만 있고 Git에 넣지 않았다.
로컬 evidence는 Git에서 제외되는 `output/tb1-acceptance/` 아래에 수집했다. 정확한 시각,
command ID와 실패 주입별 결과는
[Phase 5 TB1 실차 수용 시험](../learning-log/2026-07-19-phase-5-tb1-navigation-acceptance.md)에
있다.

한 번의 큰 방향 전환 왕복 목표는 recovery 12회 뒤 상태 stale로 fail-safe 취소됐다.
또한 LiDAR 평면 아래의 낮은 장애물은 costmap에 보이지 않았다. 두 현상 모두 숨기지 않고
운영 제한으로 기록한다. 첫 목표는 짧고 완전히 비어 있는 자유 셀만 사용하고, 저상 장애물은
작업자가 별도 육안 점검한다.

### 목표가 움직이지만 가까워지지 않을 때

Nav2의 기본 progress checker는 odom 이동을 진척으로 볼 수 있다. 로봇이 미끄러지거나 AMCL
정합이 나빠 map pose가 목표에 수렴하지 않아도 odom만 변하면 목표가 오래 `ACTIVE`로 남을 수
있다. 저장소 설정은 다음 로컬 상한으로 이 경우를 닫는다.

| 감시 | 기본값 | 종료 상태 |
| --- | ---: | --- |
| map 기준 거리 0.05m 또는 yaw 0.1rad 개선 없음 | 20초 | `FAILED` |
| 새 Nav2 feedback 없음 | 3초 | `FAILED` |
| 목표 총 실행시간 | 180초 | `FAILED` |

자동 종료를 기다리기 전이라도 로봇이 예상과 다르게 움직이면 웹의 활성 목표 취소를 먼저 누른다.
취소 뒤 `active_command_id`가 비고 odom 속도가 0인지 확인한다. 다시 보내기 전에 라이다 최단
거리, scan-map 정합과 웹 현재 pose를 확인하며, 원인을 확인하지 않은 채 WARN 확인으로 반복하지
않는다. 관련 로그는 다음처럼 찾는다.

```bash
journalctl --user -u tb1-navigation.service --since '-10 min' --no-pager \
  | grep -E 'Failed to make progress|feedback timeout|maximum duration|Goal was canceled'
```

### 지도와 위치추정

- [x] 안전 teleop으로 지도와 pose graph 저장
- [x] 저장 지도 프로필로 재시작
- [x] 웹 초기 위치 적용 뒤 `READY`
- [x] scan-map 직접 정합과 AMCL 위치 차이 4.4 cm를 수치 로그로 기록

### 기본 주행

- [x] 가까운 목표를 `0.05 m/s`, `0.3 rad/s` 이하로 도달
- [x] 활성 목표 명시적 취소와 정지
- [x] WARN 확인 전 409, 확인 후 목표 접수
- [x] 중복 목표 409
- [x] `/cmd_vel` publisher가 C++ watchdog guard 하나뿐

속도 상한은 동시에 기록한다.

```bash
ros2 topic echo /motion/navigation/cmd_vel
ros2 topic echo /cmd_vel
```

### e-stop

- [x] 주행 중 e-stop 직후 `/cmd_vel` 0
- [x] 활성 command와 Gateway lease 제거
- [x] 해제 직후 `WAITING_NEUTRAL`
- [x] IDLE 0으로 재무장한 뒤에도 이전 목표 자동 재출발 없음

### 통신 단절

주행 중 Gateway 또는 WSL Zenoh 브리지를 하나만 정지하고 시간을 기록한다.

```bash
date --iso-8601=ns
systemctl --user stop fleet-gateway.service
ros2 topic echo /fleet/navigation_status
ros2 topic echo /cmd_vel
```

- [x] 2초 후 `LEASE_EXPIRED`
- [x] 단절 시작 2.5초 이내 `/cmd_vel=0`
- [x] 복구 뒤 이전 목표 자동 재개 없음

### 프로세스 장애

각 시험은 한 번에 하나의 PID만 종료하고 systemd의 새 `MainPID`를 기록한다.

- [x] `navigation_agent` 종료: authorization 폐기와 0 출력
- [x] agent 재시작: launch 전체 재시작, 남은 Nav2 목표 취소, IDLE 시작
- [x] Nav2 종료: 안전 정지, 1초 부재 뒤 `FAILED`, systemd 복구
- [x] arbiter 종료: watchdog timeout 정지와 respawn
- [x] Python watchdog policy 종료: guard timeout 0, policy 재시작과 무재개
- [x] C++ watchdog guard 종료: 즉시 재생성, 중립 전 차단, 활성 목표 취소와 무재개

### 자원 사용량

10분 동안 5~10초 간격으로 navigation stack과 시스템 자원을 기록한다. 2026-07-19
수용 시험은 5초 간격 120개 표본을 사용했다.

```bash
pidstat -r -u -p ALL 10 60
free -h
journalctl --user -u tb1-navigation.service --since '-15 min'
```

- [x] CPU 90% 경고가 지속되지 않음
- [x] 메모리 90% 경고가 지속되지 않음
- [x] 평균, 최대, 경고 지속시간을 학습 일지에 기록

## 8. 결과 기록 형식

각 시험에 시작 시각, 종료 시각, 실행 명령, command ID, 기대값, 실제값, 관련
`journalctl` 구간과 판정을 남긴다. 미실행 항목은 `미확인`으로 둔다. 2026-07-19에는
모든 필수 항목을 실행하고 실제값을 학습 일지에 연결했으므로 Phase 5를 완료로 판정했다.
관찰된 실패와 센서 한계는 삭제하지 않고 다음 현장 시험의 preflight와 tuning 입력으로
유지한다.
