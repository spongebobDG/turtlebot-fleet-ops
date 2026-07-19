# TB1 웹 수동 조종·순찰·매핑 운영 절차

이 절차는 Phase 8 코드를 TB1에 배포한 뒤 사용한다. 로봇 주변을 비우고 작업자가 전원 스위치와
e-stop에 접근할 수 있을 때만 움직임 검증을 수행한다.

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
상태여서 WSL이 약 0.57초 늦었다. 현재 WSL은 `ntpdate`로 보정되어 NTP offset 0.013초 이하와
새 bridge PID의 timestamp 오류 0건을 확인했다. Windows 또는 WSL 재부팅 뒤에는 다음을 먼저
실행하고 bridge와 Gateway를 재시작한다.

```bash
ntpdate -q ntp.ubuntu.com
sudo ntpdate -u ntp.ubuntu.com
systemctl --user restart fleet-control-zenoh.service fleet-gateway.service
```

Windows Time의 영구 동기화는 관리자 권한으로 별도 설정한다. offset이 0.5초 이상인 상태에서는
실차 이동 검증을 시작하지 않는다.

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
2. 초기 위치를 드래그하거나 yaw 숫자를 입력해 적용한다.
3. LiDAR overlay와 벽이 맞고 navigation 상태가 `READY`가 될 때까지 기다린다.
4. 목적지 모드에서 위치를 누르고 로봇이 도착해 바라볼 방향으로 드래그한다.
5. 표시된 rad/degree와 지도 화살표를 확인하고 전송한다.

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
ros2 param get /behavior_server max_rotational_vel
ros2 param get /behavior_server min_rotational_vel
ros2 param get /behavior_server rotational_acc_lim
ros2 param get /bt_navigator default_server_timeout
ros2 topic info /cmd_vel --verbose
```

TB1 기준 DWB 최소값은 `min_speed_theta=0.05`, `min_speed_xy=0.02`이고 상한은 계속
`0.3 rad/s`, `0.05 m/s`이다. `/cmd_vel`이 non-zero인데 odometry가 변하지 않으면 motor deadband를
의심한다. 먼저 실제 적용 파라미터와 raw controller/smoother/arbiter/watchdog 출력을 비교하며,
최대 속도를 올리거나 watchdog을 우회해서 해결하지 않는다. 시험이 끝나면 목표를 취소하고
e-stop을 다시 활성화한다.

TB1 적용값은 behavior 회전 `0.05~0.3 rad/s`, 회전 가속도 `0.6 rad/s²`, BT server
acknowledgement `2000 ms`이다. raw `/cmd_vel_nav`가 `1.0 rad/s`이면 TurtleBot3 Humble의 예전
`recoveries_server` 설정이 현재 `behavior_server`에 적용되지 않은 상태이므로 배포 commit과 실제
parameter dump를 함께 확인한다. planner acknowledgement 지연과 fleet lease 만료를 혼동해
lease·authorization·watchdog timeout을 늘리지 않는다.

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

## 5. 새 환경 지도 만들기

1. e-stop을 활성화한다.
2. 웹에서 `새 지도`를 눌러 `MAPPING` 프로필로 전환한다.
3. 프로필 상태가 MAPPING이고 Nav2/AMCL이 실행되지 않는지 확인한다.
4. e-stop을 해제하고 deadman 수동 조종으로 천천히 공간을 한 바퀴 이상 스캔한다.
5. loop closure와 지도 벽 정합을 확인한다.
6. 다시 e-stop을 활성화한 뒤 `지도 저장`을 누른다.
7. map yaml/pgm과 pose graph가 모두 생성됐는지 확인한다.
8. `주행` 프로필로 전환하고 초기 위치를 다시 적용한다.

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
