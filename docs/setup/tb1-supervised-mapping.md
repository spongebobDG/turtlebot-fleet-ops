# TB1 보호 이동 기반 매핑 Runbook

이 문서는 TB1을 움직여야 하는 SLAM 실기에서 `supervised_motion`만 안전 입력을 소유하게
하고, 한 번에 짧은 거리나 각도만 실행하는 절차다. 잔류 텔레옵 명령 Incident 이후
텔레옵은 이 매핑 절차에 사용하지 않는다.

## 역할 구분

사용자가 현장에서 직접 확인할 항목:

- 로봇 전방·회전 반경의 장애물, 계단과 낙하 위험
- LDS-02 임시 GPIO 배선과 전원 케이블 고정
- 로봇이 중앙에 있고 바퀴가 자유로운지
- 명령 뒤 실제 이동 방향과 충돌·파손 여부

Codex가 원격으로 확인·수행할 항목:

- ROS graph, 센서 freshness, e-stop과 최종 0속도
- 텔레옵·Zenoh 속도 발행 경로 중단
- dry-run과 한 번의 제한 이동 실행
- odometry 결과, 로그, 지도 산출물, Git과 학습 일지 기록

현장 준비를 명시적으로 확인하기 전에는 이동 명령을 실행하지 않는다. 비정상 움직임이
발생하면 로봇을 손으로 잡지 말고 안전하게 접근할 수 있을 때 전원 스위치를 끈다.

## 1. 모든 터미널의 공통 환경

```bash
source /opt/ros/humble/setup.bash
source ~/turtlebot3_ws/install/setup.bash
source ~/turtlebot-fleet-ops/install/setup.bash

export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export TURTLEBOT3_MODEL=burger
export LDS_MODEL=LDS-02
```

`RMW_IMPLEMENTATION`을 생략하지 않는다. 이 프로젝트의 TB1 서비스는 Cyclone DDS로
실행한다. 토픽이 보이더라도 다른 DDS RMW의 ROS 2 서비스 request/reply가 정상이라고
판단할 수 없다. `supervised_motion`은 변수가 없거나 다른 값이면 시작 단계에서 종료한다.

## 2. 무이동 안전 상태

```bash
systemctl --user stop tb1-zenoh-bridge.service
pkill -INT -f 'teleop_keyboard|turtlebot3_teleop|ros2 topic pub' || true

ros2 service call \
  /safety_watchdog/set_estop \
  std_srvs/srv/SetBool \
  '{data: true}'

ros2 topic echo \
  /safety/estop_active \
  --once \
  --qos-durability transient_local

ros2 topic info /safety/cmd_vel_in --verbose
ros2 topic echo /cmd_vel --once
```

통과 기준:

- e-stop 응답이 `success=True`
- `/safety/estop_active`가 `data: true`
- `/safety/cmd_vel_in` Publisher가 0개
- `/cmd_vel`의 `linear.x`와 `angular.z`가 모두 0
- 텔레옵과 `ros2 topic pub` 프로세스가 없음

하나라도 다르면 실차 이동을 실행하지 않는다.

watchdog은 e-stop 상태를 transient-local QoS와 2Hz heartbeat로 발행한다. 따라서 늦게
시작한 점검 도구도 마지막 상태를 받고, 상태 발행이 계속 살아 있는지도 확인할 수 있다.

## 3. 실제 graph dry-run과 자세 체크포인트

`supervised_motion`은 기본적으로 이전 성공 동작의 최종 odom 자세를 로봇별 상태 파일에
보관한다. 다음 실행의 시작 자세가 3cm 또는 5도보다 달라지면 사람이 밀거나 돌린 것 또는
odom 재시작으로 판단하고 e-stop을 풀지 않는다. 실제 이동 직전에는 체크포인트를
`motion_in_progress`로 먼저 표시하며, 성공한 최종 자세만 이 표시를 해제한다. 따라서 이동
중단이나 프로세스 강제 종료는 실제 변위가 작아도 다음 실행을 거부한다.

최초 배포, bringup 재시작, 또는 승인된 수동 이동 뒤에는 현장 상태를 확인한 다음 아래
명령으로 기준을 한 번만 등록한다. 이 명령은 dry-run이므로 바퀴를 움직이지 않는다.

```bash
ros2 run fleet_navigation supervised_motion --ros-args \
  -p dry_run:=true \
  -p reset_pose_checkpoint:=true \
  -p mode:=translate \
  -p target_distance_m:=0.05 \
  -p speed:=0.02 \
  -p timeout_sec:=5.0 \
  -p minimum_clearance_m:=0.30
```

정상 로그에는 `POSE_CHECKPOINT_RESET`과
`SUPERVISED_MOTION_DRY_RUN_SUCCESS`가 함께 나온다. `reset_pose_checkpoint`는
일반 이동에서 사용할 수 없으며, 자세 불일치 원인을 확인하지 않고 반복해서 기준을
덮어쓰면 안 된다. 로봇을 들어 옮기거나 바퀴가 미끄러져 활성 SLAM의 pose 전제가
깨졌다면 체크포인트만 재등록하지 말고 SLAM 지도도 새로 시작한다.

기준 등록 뒤의 평상시 무동작 점검에서는 reset 없이 실행한다.

```bash
ros2 run fleet_navigation supervised_motion --ros-args \
  -p dry_run:=true \
  -p mode:=translate \
  -p target_distance_m:=0.05 \
  -p speed:=0.02 \
  -p timeout_sec:=5.0 \
  -p minimum_clearance_m:=0.30
```

정상 결과는 `SUPERVISED_MOTION_DRY_RUN_SUCCESS`와 종료 코드 0이다. dry-run은 e-stop을
해제하지 않는다. 짧은 외부 `timeout`으로 프로세스를 자르지 않는다. 노드 내부에 서비스,
센서, 동작 timeout이 있고 모든 실패 경로가 e-stop과 0속도로 끝나도록 구현돼 있다.
체크포인트가 없거나 허용 범위를 넘은 경우에도 같은 fail-closed 경로로 종료한다.

## 4. 5cm 직진 검증

사용자가 다음 문장을 확인한 뒤에만 실행한다.

```text
전방 30cm 이상 여유 / 케이블 고정 / 로봇 중앙 / 관찰 준비 완료
```

```bash
ros2 run fleet_navigation supervised_motion --ros-args \
  -p dry_run:=false \
  -p mode:=translate \
  -p target_distance_m:=0.05 \
  -p speed:=0.02 \
  -p timeout_sec:=5.0 \
  -p minimum_clearance_m:=0.30
```

노드는 시작할 때 e-stop을 걸고, 단독 Publisher·최신 odom·scan·전방 여유·최종 0속도를
확인한다. 그 뒤에만 잠금을 풀어 이동하고, 목표 도달 즉시 0속도와 e-stop을 다시 적용한다.

## 5. 30도 회전 검증

5cm 직진의 시스템 결과와 실제 이동을 모두 확인한 뒤 별도의 현장 준비 확인을 받는다.

```bash
ros2 run fleet_navigation supervised_motion --ros-args \
  -p dry_run:=false \
  -p mode:=rotate \
  -p target_angle_rad:=0.5235987756 \
  -p speed:=0.10 \
  -p timeout_sec:=8.0
```

회전량은 yaw 샘플 절댓값 합이 아니라 `±π`를 보정한 부호 있는 순변화량으로 계산한다.
반대 방향 회전이 제한을 넘거나 odom·scan이 0.5초 이상 stale이면 실패한다.

## 6. 매 동작 뒤 증거

```bash
ros2 topic echo \
  /safety/estop_active \
  --once \
  --qos-durability transient_local
ros2 topic info /safety/cmd_vel_in
ros2 topic echo /cmd_vel --once
ros2 topic echo /odom --once
```

기록할 값:

- guard 종료 코드와 `SUPERVISED_MOTION_SUCCESS` 또는 실패 원인
- 목표 대비 부호 있는 odometry 진행량과 실행 시간
- 시작 자세 체크포인트 편차와 성공 후 `pose checkpoint updated` 로그
- 종료 후 e-stop `true`, 안전 입력 Publisher 0, 최종 속도 0
- 사용자가 본 실제 이동 방향·대략적인 거리·충돌·파손 여부

시스템 수치와 물리 관찰 중 하나라도 맞지 않으면 다음 동작으로 넘어가지 않는다.

## 7. 중단 절차

명령이 실패하거나 예상보다 오래 걸려도 다른 텔레옵을 추가 실행하지 않는다.

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 service call \
  /safety_watchdog/set_estop \
  std_srvs/srv/SetBool \
  '{data: true}'

pkill -INT -f 'supervised_motion|teleop_keyboard|turtlebot3_teleop' || true
```

서비스 응답이 없으면 RMW 변수를 먼저 확인한다. 로봇이 움직이고 있으면 원격 명령을 계속
재시도하기보다 사용자가 안전 거리에서 전원을 차단한다. 로봇을 잡아 세우는 절차는 사용하지
않는다.

## 8. 지도 저장 전 통과 조건

- 짧은 직진과 회전 guard 실기 통과
- 케이블 구속과 wheel slip 없음
- `/map` 갱신과 `map -> odom` TF 정상
- 종료 지점에서 벽 이중선·끊김·비정상 회전 없음
- 지도 PGM/YAML과 pose graph를 함께 저장
- 품질이 깨진 시도의 지도와 odometry는 폐기 사유를 기록하고 재사용하지 않음

관련 분석은 [잔류 텔레옵 명령 Incident](../learning-log/2026-07-16-tb1-residual-teleop-command-incident.md)와
[RMW 혼용 서비스 시간 초과 사례](../case-studies/zenoh-service-timeout-rmw-mismatch.md)를 참고한다.
