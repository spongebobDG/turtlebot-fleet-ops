# navigation_agent

TB1에서 Nav2 목표를 소유하고 Gateway lease와 로봇 안전 상태가 유효한 동안에만
Nav2 속도 명령을 watchdog 입력으로 전달하는 패키지다.

```text
mapping: teleop -> /motion/manual/cmd_vel -> motion_arbiter
navigation: Nav2 -> /motion/navigation/cmd_vel -> motion_arbiter
                                                    |
                                           /safety/cmd_vel_in
                                                    |
                                             safety_watchdog
                                                    |
                                                 /cmd_vel
```

실제 `/cmd_vel`은 계속 `safety_watchdog`만 발행한다. arbiter는 선택하지 않은 입력,
0.5초 넘게 갱신되지 않은 입력, 또는 0.5초 넘게 갱신되지 않은 navigation
authorization을 모두 0으로 바꾼다.
저장소 소유 non-composed Nav2 launch는 controller의 `cmd_vel`을 내부
`cmd_vel_nav`로 보내고, `velocity_smoother`의 `cmd_vel_smoothed`와
`behavior_server` recovery의 `cmd_vel`만 `/motion/navigation/cmd_vel`로 보낸다.
노드별 remap으로 smoothing 경로와 실제 `/cmd_vel`을 모두 분리한다.

## 실행 프로필

- `tb1_mapping.launch.py`: SLAM Toolbox async와 MANUAL arbiter만 실행한다.
- `tb1_navigation.launch.py`: 저장 지도, AMCL, Nav2, IDLE arbiter와
  `navigation_agent`를 실행한다.
- 두 systemd 서비스는 `Conflicts=`로 동시에 실행되지 않는다.

지도 파일은 저장소 밖의
`~/.local/share/turtlebot-fleet-ops/maps/tb1/`에 저장한다.

```bash
ros2 launch navigation_agent tb1_mapping.launch.py
infra/navigation/save-tb1-map.sh
ros2 launch navigation_agent tb1_navigation.launch.py \
  map:="$HOME/.local/share/turtlebot-fleet-ops/maps/tb1/map.yaml"
```

매핑 teleop은 반드시 다음처럼 manual 입력으로 remap한다.

```bash
ros2 run turtlebot3_teleop teleop_keyboard \
  --ros-args -r cmd_vel:=/motion/manual/cmd_vel
```

## 실패 시 안전 동작

- Gateway lease는 0.5초마다 발행되고 2초 동안 오지 않으면 목표를 취소한다.
- agent 프로세스가 죽으면 authorization이 0.5초 안에 만료된다.
- agent 재시작 시 arbiter를 IDLE로 만들고 Nav2의 남은 목표를 모두 취소한다.
- Nav2 action endpoint와 `bt_navigator` lifecycle ACTIVE를 모두 확인한 뒤에만 새
  목표를 받는다.
- Nav2 action 서버가 1초 동안 사라지면 authorization을 닫고 목표를 `FAILED`로
  종료한다.
- e-stop 또는 RobotStatus ERROR가 들어오면 authorization과 motion mode를 먼저
  닫고 Nav2 목표를 취소한다.
- e-stop 해제 뒤 arbiter의 IDLE 0 입력으로 watchdog을 재무장하며 이전 목표는
  재개하지 않는다.
- watchdog 재시작도 `WAITING_NEUTRAL`로 시작해 이전 Nav2 출력을 통과시키지 않는다.

저장소의 `config/tb1_nav2_rewrites.yaml`이 TurtleBot3 Humble Burger 기준 설정 위에
적용된다. Nav2의 DWB와 recovery 회전 상한은 각각 `0.05 m/s`, `0.3 rad/s`로 다시 쓰며,
watchdog도 같은 상한을 독립적으로 강제한다. 5 cm/cell 저장 지도와 저속 운전에 맞춰
AMCL은 5 cm 또는 0.05 rad 이동마다 갱신하고, 웹 목표 허용 오차는 위치 10 cm와 방향
0.15 rad로 고정한다. 따라서 TurtleBot3 기본 위치 허용 오차 25 cm 때문에 짧은 목표가
실제 이동 없이 성공하는 것을 막는다.

운영 및 실차 검증은
[TB1 매핑·Nav2 운영 절차](../../docs/setup/tb1-navigation.md)를 따른다.

로봇 없는 Humble 검증은 실제 Nav2 graph와 Zenoh action 경계를 나눠 실행한다.

```bash
ROS_DOMAIN_ID=142 bash infra/navigation/run-robotless-navigation-smoke.sh
bash infra/navigation/run-robotless-zenoh-action-smoke.sh
```
