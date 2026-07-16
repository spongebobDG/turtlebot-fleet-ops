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

- `slam.launch.py`: `/scan`, `odom -> base_footprint`으로 실시간 지도를 생성한다.
- `navigation.launch.py`: 저장 지도, AMCL과 Nav2를 시작한다.

지도 생성 중에는 Nav2 Goal을 보내지 않는다. 저장 지도를 검토한 뒤에만
`navigation.launch.py`를 사용한다.
