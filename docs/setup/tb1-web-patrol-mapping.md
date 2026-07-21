# TB1 웹 수동 조종·순찰·매핑 운영 절차

이 절차는 Phase 8 코드를 TB1에 배포한 뒤 사용한다. 로봇 주변을 비우고 작업자가 전원 스위치와
e-stop에 접근할 수 있을 때만 움직임 검증을 수행한다.

## 0. 웹 관제 빠른 시작

새 관제 PC에서는 WSL 제어 환경을 한 번만 구성한다. `-RobotAddress`에는 TB1에서 `hostname -I`로
확인한 현재 유선 또는 Wi-Fi 주소를 넣는다. 같은 네트워크에서 `tb1` 이름이 해석되면 주소 대신
기본값을 사용할 수 있다.

```powershell
cd C:\project\turtlebot-fleet-ops
powershell -ExecutionPolicy Bypass -File `
  .\scripts\control-pc\bootstrap_wsl.ps1 `
  -RobotAddress 192.168.x.x
```

이후 평소에는 다음 한 명령만 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\control-pc\open_tb1_web_control.ps1
```

명령은 실제 control bridge, Gateway, 로그 모니터를 시작하고 기본 브라우저에서
`http://127.0.0.1:8000`을 연다. 로봇 없는 mock이 8000번 포트를 사용 중이면 정확히 그 mock을
종료한 뒤 실제 서비스를 시작한다. TB1이 꺼져 있으면 `TB1_WAITING_FOR_POWER`가 표시되지만 웹
관제는 계속 실행된다. 배포 때 활성화한 TB1 bridge와 관제 bridge는 재시작 정책을 사용하므로,
이후 TB1 전원을 켜고 네트워크가 연결되면 페이지를 다시 실행하지 않아도 자동으로 상태가
`ONLINE`으로 바뀐다.

TB1 주소가 바뀐 날만 다음처럼 갱신한다. 주소는 로컬 `control.env`에만 저장되며 Git에는
기록되지 않는다.

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\control-pc\open_tb1_web_control.ps1 `
  -RobotAddress 192.168.x.x
```

웹 지도 오른쪽의 수동 조종은 다음 deadman 계약을 따른다.

- `W`: 전진, `S`: 후진, `A`: 제자리 좌회전, `D`: 제자리 우회전
- 키 또는 화면 버튼을 누르는 동안만 명령을 10 Hz로 갱신하며 놓으면 즉시 정지한다.
- 최대 속도는 선속도 `0.05 m/s`, 각속도 `0.3 rad/s`이다.
- 입력칸 편집 중에는 WASD를 무시하고, 창 포커스 손실·`Space`·`Escape`·통신 오류에는 정지한다.
- `MAPPING` 또는 `NAVIGATION`, safety fresh, e-stop 해제, motion armed, 활성 목적지·순찰 없음일
  때만 수동 조종이 열린다.

새 지도를 만들 때는 웹에서 `MAPPING` 프로필을 선택해 WASD로 주행하고 지도를 저장한다.
저장된 지도에서 목적지·순찰을 실행할 때는 `NAVIGATION` 프로필로 전환한다. 프로필 전환은
e-stop을 체결하고 이전 동작을 재개하지 않으므로 화면 지시에 따라 다시 명시적으로 재무장한다.

## 1. 배포 전 로봇 없는 검증

WSL Ubuntu 22.04에서 실행한다.

```bash
cd /mnt/c/projects/turtlebot-fleet-ops
bash scripts/weekend/verify_workspace.sh
```

성공 조건은 전체 colcon test, operations smoke, 실제 Nav2 robotless smoke, 분리 domain Zenoh
action smoke가 모두 통과하는 것이다.

현재 관제 PC는 기존 dirty WSL 작업 트리를 보존하고
`~/turtlebot-fleet-ops-phase8`의 clean build를 사용하도록 control bridge와 Gateway에 systemd
drop-in을 적용했다. 실차 수용 전 다음 결과가 모두 나와야 한다.

```bash
systemctl --user show fleet-control-zenoh.service fleet-gateway.service \
  -p ActiveState -p SubState -p ExecStart
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:8000/api/patrols
curl -fsS http://127.0.0.1:8000/api/mlops/ros2-logs/incidents
```

두 `ExecStart`가 `turtlebot-fleet-ops-phase8`을 가리키고 두 서비스가 active/running이며 세 API가
HTTP 200이어야 한다. TB1 배포 전 manual/profile/map-save가 준비되지 않은 상태로 거부되는 것은
fail-closed 동작이다.

관제 bridge에 `incoming timestamp ... exceeding delta 500ms`가 보이면 Windows·WSL·TB1의
NTP 상태와 시각 차이를 먼저 확인한다. 이 PC에서는 Windows가 `Local CMOS Clock` 미동기화
상태여서 WSL이 약 0.64초 늦었다. 관리자 PowerShell에서 저장소 소유 스크립트로 Windows Time을
인터넷 NTP에 고정한다. 최초 offset이 0.2초를 넘으면 스크립트는 한 번 즉시 보정하고 Windows의
원래 점진 보정 정책을 복구한다.

```powershell
powershell -ExecutionPolicy Bypass -File `
  "C:\projects\turtlebot-fleet-ops\scripts\control-pc\configure_windows_time.ps1"
```

설정 뒤 일반 PowerShell과 WSL에서 offset을 확인하고 bridge와 Gateway를 재시작한다.

```bash
ntpdate -q ntp.ubuntu.com
systemctl --user restart fleet-control-zenoh.service fleet-gateway.service
```

`test_tb1_connection.ps1 -RequireRobot`도 외부 NTP 표본이 ±0.2초를 넘으면 실패한다. offset이
0.2초를 넘거나 bridge 오류가 계속되면 실차 이동 검증을 시작하지 않는다.

2026-07-20 이 PC에서는 보정 전 `+0.6038752초`, 보정 후 `+0.0032821초`였고, 서비스 재시작 뒤
새 Zenoh invocation을 70초 감시해 timestamp rejection과 ERROR 0건을 확인했다.

## 2. TB1 배포

e-stop이 활성화되어 있고 바퀴가 지면에서 움직이지 않는지 먼저 확인한다.

```powershell
powershell -ExecutionPolicy Bypass -File `
  "C:\projects\turtlebot-fleet-ops\scripts\control-pc\run_tb1_acceptance.ps1" `
  -RobotUser dg -RobotAddress 192.168.123.32
```

배포 후 `tb1-profile-manager.service`를 포함한 8개 관리 unit과 navigation/mapping unit 상태를
기록한다. 주소는 DHCP에 따라 달라질 수 있으므로 실제 SSH 주소를 사용한다.

## 3. 목적지와 방향

1. `NAVIGATION` 프로필과 e-stop 상태를 확인한다.
2. 지도 위 `초기 위치` 모드를 선택한다.
3. `LiDAR로 현재 위치 찾기`를 누른다. 시작점을 따로 찍지 않아도 전체 지도에서 정합 후보를
   검색한다.
4. 붉은 LiDAR 점이 지도 벽과 맞는지 확인한 뒤 `초기 위치 적용`을 누른다.
5. 파란 `TB1 현재 위치` 화살표와 `현 위치 map (...)` 표시가 나타나고 navigation 상태가
   `READY`가 될 때까지 기다린다.
6. 주변이 안전할 때만 e-stop을 해제한다.
7. `목적지` 모드에서 위치를 누르고 로봇이 도착해 바라볼 방향으로 드래그한다.
8. 표시된 rad/degree와 지도 화살표를 확인하고 전송한다.

12 px 미만 드래그처럼 방향이 불명확한 목표는 전송하지 않는다. WARN이 있으면 fault 내용을
확인하고 필요한 경우에만 경고 확인 후 다시 보낸다.

초기 위치 적용에서 `Profile status is stale`가 나오면 Gateway의 `mapping` 상태와 TB1 profile
manager를 확인한다.

```bash
systemctl --user status tb1-profile-manager.service
ros2 topic echo /fleet/mapping_status --once
```

TB1 Phase 8 배포 전에는 이 서비스와 토픽이 없어 요청이 fail-closed한다. 배포 후에는 먼저 웹에서
`주행 모드`를 선택해 fresh한 `NAVIGATION` profile을 확인하고 초기 위치를 다시 적용한다. 초기
위치 적용 전 navigation `UNAVAILABLE`과 AMCL의 initial-pose 대기 로그는 정상이다.

### 목표가 접수됐지만 바퀴가 돌지 않을 때

path와 progress timeout 로그만으로 localization 실패라고 결론 내리지 않는다. 짧고 통제된 시험에서
controller부터 odometry까지 같은 구간을 기록한다.

```bash
ros2 param get /controller_server FollowPath.min_speed_theta
ros2 param get /controller_server FollowPath.min_speed_xy
ros2 param get /controller_server controller_frequency
ros2 param get /controller_server FollowPath.vx_samples
ros2 param get /controller_server FollowPath.vtheta_samples
ros2 param get /controller_server FollowPath.sim_time
ros2 param get /controller_server FollowPath.plugin
ros2 param get /controller_server FollowPath.primary_controller
ros2 param get /controller_server FollowPath.angular_dist_threshold
ros2 param get /controller_server FollowPath.angular_disengage_threshold
ros2 param get /controller_server FollowPath.forward_sampling_distance
ros2 param get /controller_server FollowPath.rotate_to_heading_angular_vel
ros2 param get /controller_server progress_checker.plugin
ros2 param get /controller_server progress_checker.required_movement_angle
ros2 param get /behavior_server max_rotational_vel
ros2 param get /behavior_server min_rotational_vel
ros2 param get /behavior_server rotational_acc_lim
ros2 param get /bt_navigator default_server_timeout
ros2 topic info /cmd_vel --verbose
```

TB1 기준 DWB 최소값은 `min_speed_theta=0.05`, `min_speed_xy=0.02`이고 Nav2 상한은
`0.27 rad/s`, `0.05 m/s`이다. `/cmd_vel`이 non-zero인데 odometry가 변하지 않으면 motor deadband를
의심한다. 먼저 실제 적용 파라미터와 raw controller/smoother/arbiter/watchdog 출력을 비교하며,
최대 속도를 올리거나 watchdog을 우회해서 해결하지 않는다. 시험이 끝나면 목표를 취소하고
e-stop을 다시 활성화한다.

TB1 적용값은 behavior 회전 `0.05~0.27 rad/s`, 회전 가속도 `0.6 rad/s²`, BT server
acknowledgement `2000 ms`이다. raw `/cmd_vel_nav`가 `1.0 rad/s`이면 TurtleBot3 Humble의 예전
`recoveries_server` 설정이 현재 `behavior_server`에 적용되지 않은 상태이므로 배포 commit과 실제
parameter dump를 함께 확인한다. planner acknowledgement 지연과 fleet lease 만료를 혼동해
lease·authorization·watchdog timeout을 늘리지 않는다.

TB1 저속 DWB 적용값은 controller `5 Hz`, 표본 `10 × 20`, 예측 `1.0 s`이다. 목표 실행 중
`Control loop missed its desired rate`가 반복되면 e-stop 후 load average와 process별 CPU를
수집한다. 4코어에서 load average가 4를 지속해서 넘는 상태로 장시간 주행 검증을 계속하지 않는다.
controller 주기를 낮추더라도 20 Hz smoother와 watchdog Publisher 단일 소유를 함께 확인한다.

목표가 제자리 회전 중 20초마다 recovery로 바뀌면 global path 첫 구간 heading과 현재 map yaw를
비교한다. TB1 controller는 `nav2_controller::PoseProgressChecker`와 각도 진행 임계값 `0.1 rad`를
사용해야 한다. 최종 목표 yaw 오차가 잠시 커져도 path heading을 맞추기 위한 실제 map yaw 이동은
진행으로 인정하되 전체 목표 상한 180초는 유지한다.

경로 heading이 현재 yaw와 거의 반대라 회전 부호가 반복해서 바뀌면 다음 값도 확인한다.

```text
FollowPath.plugin = nav2_rotation_shim_controller::RotationShimController
FollowPath.primary_controller = dwb_core::DWBLocalPlanner
FollowPath.angular_dist_threshold = 0.6
FollowPath.angular_disengage_threshold = 0.35
FollowPath.forward_sampling_distance = 0.15
FollowPath.rotate_to_heading_angular_vel = 0.2
```

실차 성공 기준은 action `SUCCEEDED`, recovery 0회, 최종 pose 허용오차뿐 아니라 raw controller,
smoother, arbiter, watchdog, `/cmd_vel`의 최대 명령이 모두 0.27rad/s 이하인 것이다. 엔코더 기반
odometry 순간값은 별도 관측치로 남기고, 시험 후 quiet 속도가 다시 0으로 수렴하는지 확인한다.

## 4. Deadman 수동 조종

수동 버튼은 누르고 있는 동안만 사용한다. 전진·후진·좌회전·우회전 버튼을 놓았을 때 즉시
정지해야 한다. 다음 실패 주입도 각각 수행한다.

- 버튼을 누르다 pointer를 화면 밖으로 이동
- 버튼을 누르다 브라우저 탭 종료
- Gateway 중지
- Zenoh 연결 중지

TB1의 manual authorization은 마지막 갱신 후 0.35초에 만료되어야 한다. 최종 `/cmd_vel=0`과
arbiter `IDLE`을 로그로 남긴다. 수동 조종 중에는 navigation 목표나 순찰을 동시에 시작하지
않는다.

2026-07-20 실차 측정에서 단일 갱신 중단, Gateway `SIGKILL`, control Zenoh bridge `SIGKILL`의
최종 non-zero 지속시간은 각각 0.301초, 0.304초, 0.305초였다. 세 시험 모두 이전 manual session은
복구 뒤 재개되지 않았고 시험 직후 e-stop을 다시 활성화했다.

## 5. 새 환경 지도 만들기

1. e-stop을 활성화한다.
2. 웹에서 `새 지도`를 눌러 `MAPPING` 프로필로 전환한다.
   `LIVE MAP` 표시가 켜지면 SLAM 지도가 1초 간격으로 화면에 갱신된다. 사용자가 맞춘 확대·이동은
   유지되며, SLAM이 지도 범위를 확장했을 때만 전체 지도에 맞춰 다시 표시된다.
   SLAM의 `map → base_footprint`가 준비되면 파란 `TB1 현재 위치` 화살표도 함께 갱신된다.
3. 프로필 상태가 MAPPING이고 Nav2/AMCL이 실행되지 않는지 확인한다.
4. e-stop을 해제하고 deadman 수동 조종으로 천천히 공간을 한 바퀴 이상 스캔한다.
5. loop closure와 지도 벽 정합을 확인한다.
6. 다시 e-stop을 활성화한 뒤 `지도 저장`을 누른다.
7. map yaml/pgm과 pose graph가 모두 생성됐는지 확인한다.
8. `주행` 프로필로 전환하고 3절의 LiDAR 자동 정렬로 초기 위치를 다시 적용한다.

운영 산출물 기본 경로는 다음과 같다.

```text
~/.local/share/turtlebot-fleet-ops/maps/tb1/
```

기존 지도를 덮어쓰는 작업은 overwrite를 명시한 경우에만 수행한다.

## 6. 웨이포인트 순찰

1. 웨이포인트 모드에서 위치와 방향을 차례대로 추가한다.
2. loop 수와 지점별 dwell 시간을 입력하고 순찰을 저장한다.
3. 지도 free cell, 각 화살표 방향, 예상 경로를 확인한다.
4. 순찰을 시작하고 각 지점의 `NavigateRobot` 결과를 관찰한다.
5. 실행 중 취소 후 현재 목표가 취소되고 다음 지점이 시작되지 않는지 확인한다.
6. Gateway 또는 navigation agent를 재시작하고 이전 순찰이 자동 재개되지 않는지 확인한다.

## 7. 로그 원인 분석

관제의 MLOps incident 영역에서 다음을 확인한다.

- anomaly 상태와 Production 모델 버전
- localization/TF, collision, progress, lease, sensor, restart, resource, safety 분류
- 원인 후보 confidence
- 원본 node/logger/message 증거
- 작업자 권장 조치

incident는 진단 보조이며 자동 복구 명령이 아니다. 권장 조치를 수행하기 전 실제 ROS graph,
TF, 센서와 systemd 로그를 함께 확인한다.

## 8. 최종 합격 기준과 예상 시간

| 구간 | 예상 시간 |
| --- | ---: |
| 배포·빌드·서비스 확인 | 20~30분 |
| 목표 yaw·평활화·deadman | 20~30분 |
| 매핑·저장·AMCL 재기동 | 35~50분 |
| 순찰·취소·비재개 | 30~45분 |
| e-stop·lease·장애·원인 분석 | 35~50분 |
| 10분 주행과 CPU·메모리 기록 | 20~30분 |

새 결함이 없으면 총 3~4시간이다. localization이나 Zenoh를 다시 조정하면 1~2시간을 추가로
잡는다. 모든 로그와 측정값을 학습 일지에 기록한 뒤에만 Phase 8을 완료로 바꾼다.

### 2026-07-20 최종 실차 수용 기록

- map yaml/pgm과 pose graph 저장·검증, 운영 원본 checksum 복원, NAVIGATION·AMCL 재기동 통과
- 최종 yaw 분리 순찰 한 loop 완료, 명시적 취소와 Gateway 재시작 후 무재개 통과
- 단일 manual 갱신·Gateway·Zenoh 단절 정지: 각각 0.301초, 0.304초, 0.305초
- 600초 순찰: 11개 loop 진행, CPU 30초 표본 66.1~73.6%, 메모리 27.1~27.3%,
  LiDAR 최소 표본 0.519m, fault 0
- 종료: patrol `CANCELED`, navigation `CANCELED`, e-stop active, motion-armed false
- `/cmd_vel`: Publisher 1개 `safety_watchdog`, subscriber 1개 `turtlebot3_node`

첫 장시간 시험 중 로봇을 들어 케이블을 정리하면 LiDAR가 바닥이나 주변 물체를 가까이 감지하고
clearance guard가 목표를 취소하는 것이 정상이다. 이 기록은 센서 노이즈로 필터링하지 않는다.
로봇을 다시 내려놓은 뒤 초기 위치가 실제 위치와 맞는지 확인하고, 물리 개입이 없는 새 600초
구간만 자원 수용 근거로 사용한다.

MLOps incident에서 startup의 `lease timeout` 설정, costmap plugin 초기화나 성공 주행 중 INFO
수준 Rotation Shim transform 메시지가 원인 후보로 보이면 현재 runtime과 규칙 버전을 확인한다.
원본 로그는 보존하지만 localization/progress/network/collision root cause는 WARNING 이상만
운영 incident로 승격한다.

계획된 NAVIGATION→IDLE 전환 뒤에는 다음처럼 Python child가 clean exit했는지 확인한다.

```bash
journalctl --user -u tb1-navigation.service --since '2 minutes ago' --no-pager
```

`manual_control_node`와 `navigation_agent_node`에는 traceback, `KeyboardInterrupt`, 미회수 coroutine,
`context is invalid`, `process has died`가 없어야 한다. Nav2 Humble의 planner lifecycle은 전체
launch context가 동시에 닫히며 transition ERROR를 남길 수 있다. profile `IDLE`, systemd 정상
stop과 요청 시각이 일치할 때만 알려진 종료 제한사항으로 분류하고, 그 외에는 실제 crash로
조사한다.
