# Fleet Navigation

TB1의 SLAM Toolbox와 Nav2를 로컬 `safety_watchdog` 뒤에서 실행하는 ROS 2 Humble
설정 패키지다. 지도 작성과 저장 지도 기반 자율주행을 별도 launch로 분리한다.

## 속도 명령 경계

```text
Nav2 controller -- cmd_vel_nav --> velocity_smoother
                                         |
                                         v
                              /safety/cmd_vel_in
                                         |
                                  safety_watchdog
                                         |
                                         v
                                     /cmd_vel
                                         |
                                  turtlebot3_node

Nav2 behavior -----------------> /safety/cmd_vel_in
```

Nav2의 controller와 복구 behavior가 `/cmd_vel`을 직접 발행하지 않도록 각 노드의
remapping을 명시한다. Watchdog는 0.05 m/s, 0.3 rad/s 제한, 0.5초 timeout과 e-stop을
최종 집행한다.

## Launch

- `slam.launch.py`: LDS-02의 `/scan`을 고정 360-bin `/scan_normalized`로
  변환하고 `odom -> base_footprint`으로 실시간 지도를 생성한다.
- `navigation.launch.py`: 저장 지도, AMCL과 Nav2를 시작한다.

LDS-02 드라이버는 회전마다 `/scan` 배열 길이와 시작·끝 각도가 달라질 수 있다.
`scan_normalizer`는 원본 토픽을 보존하면서 각 측정값을 가장 가까운 1도 격자에
배치한다. 같은 격자에 측정이 겹치면 더 가까운 장애물을 선택하고, 관측되지 않은
각도는 `+inf`로 발행한다. SLAM Toolbox, AMCL과 Nav2 costmap은 모두
`/scan_normalized`만 사용한다.

지도 생성 중에는 Nav2 Goal을 보내지 않는다. 저장 지도를 검토한 뒤에만
`navigation.launch.py`를 사용한다.

## 저장 지도 검사

`validate_map`은 Nav2 시작 전에 YAML·PGM 구조와 최소 관측량을 fail-fast로 검사한다.

```bash
ros2 run fleet_navigation validate_map \
  maps/tb1_lab.yaml \
  --min-known-cells 100 \
  --min-known-ratio 0.01 \
  --require-pose-graph
```

지도 이미지는 YAML이 있는 디렉터리 안의 상대 경로여야 한다. 이 검사는 파일 일관성을
보장하지만 벽 정합, loop closure나 AMCL 수렴은 보장하지 않는다.
