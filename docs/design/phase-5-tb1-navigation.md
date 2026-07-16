# Phase 5 설계: TB1 SLAM과 안전 Nav2

## 목적

TB1의 `/scan`, `/odom`, TF로 2D 지도를 만들고, 검증한 저장 지도에서 Nav2
`NavigateToPose` Goal을 수행한다. Nav2가 생성하는 모든 속도 명령은 로봇 내부
`safety_watchdog`를 통과해야 하며 웹 연동은 터미널 Goal이 실차에서 검증된 뒤 추가한다.

## 단계 분리

| 단계 | 실행 노드 | 이동 방식 | 완료 산출물 |
| --- | --- | --- | --- |
| 5A 환경 준비 | 기존 bringup, watchdog | 이동 없음 | 패키지, 설정, 자동 테스트 |
| 5B 지도 작성 | SLAM Toolbox | 저속 수동 teleop | PGM, YAML, pose graph |
| 5C 저장 지도 주행 | Map Server, AMCL, Nav2 | `NavigateToPose` | 성공·취소·실패 증거 |
| 5D 웹 연동 | Fleet Gateway Action Client | 웹 Goal | 진행 상태, 결과, 취소 API |

지도 작성과 저장 지도 기반 AMCL 주행은 동시에 실행하지 않는다. 두 노드가 모두
`map -> odom` TF를 발행하면 좌표계 권한이 충돌하기 때문이다.

## 좌표계와 데이터 흐름

```text
SLAM 또는 AMCL
    map -> odom
              |
              v
turtlebot3_node: odom -> base_footprint
robot_state_publisher: base_footprint -> base_link -> base_scan
ld08_driver: /scan (variable geometry, frame_id=base_scan)
    -> scan_normalizer: /scan_normalized (fixed 360 bins)
```

SLAM 단계에서는 SLAM Toolbox가 `map -> odom`을 발행한다. 저장 지도 주행에서는
Map Server가 점유 격자를 제공하고 AMCL이 같은 변환을 담당한다. 바퀴 odometry는
짧은 시간의 상대 이동에 강하고, AMCL은 지도 기준의 누적 오차를 보정한다.

LDS-02의 실제 `/scan`은 회전마다 배열 길이와 시작·끝 각도가 달라졌다. SLAM과 Nav2는
원본 index를 자르지 않고 각도 기준으로 재투영한 `/scan_normalized`를 사용한다. 원본은
Robot Agent와 장애 분석을 위해 보존한다.

## 속도 안전 경계

```text
Nav2 controller -- cmd_vel_nav --> velocity_smoother
                                         |
                                         v
                              /safety/cmd_vel_in
                                         |
Nav2 behavior ---------------------------+
                                         |
                                  safety_watchdog
                      clamp + timeout + e-stop + neutral re-arm
                                         |
                                         v
                                      /cmd_vel
                                         |
                                  turtlebot3_node
```

Nav2 기본 launch를 그대로 사용하면 `velocity_smoother`가 `/cmd_vel`을 직접 발행해
watchdog와 Publisher가 둘이 될 수 있다. `fleet_navigation`은 디버깅하기 쉬운
non-composed 노드를 명시적으로 실행하고 다음 remapping을 적용한다.

- controller `cmd_vel` → `cmd_vel_nav`
- velocity smoother `cmd_vel_smoothed` → `/safety/cmd_vel_in`
- recovery behavior `cmd_vel` → `/safety/cmd_vel_in`
- watchdog만 최종 `/cmd_vel` 발행

Nav2 설정 한도도 0.05 m/s와 0.3 rad/s로 맞추지만 최종 권한은 watchdog에 있다.
설정 실수, Nav2 장애 또는 네트워크 단절 때도 0.5초 입력 timeout으로 정지한다.

Zenoh 브리지는 `/cmd_vel`을 중계하지 않는다. 관제에서 오는 모든 수동·자율 속도는
`/safety/cmd_vel_in`만 통과하며, 운영 graph에서 최종 `/cmd_vel` Publisher는
`safety_watchdog` 하나여야 한다.

## 실행 위치

- TB1: sensor bringup, SLAM Toolbox, AMCL, Nav2, Safety Watchdog
- WSL: Zenoh bridge, Fleet Gateway, 웹, RViz 운영 화면
- 브라우저: 상태 표현과 명시적 Goal·취소·e-stop 요청

주행 판단을 TB1에 두면 관제 네트워크가 끊겨도 로컬 장애물 회피와 정지가 동작한다.
WSL은 계산이 무거운 관제·저장·시각화 책임을 맡는다.

## 지도 산출물

| 파일 | 의미 | 사용 시점 |
| --- | --- | --- |
| `tb1_lab.pgm` | 셀별 점유 확률 이미지 | Map Server, AMCL |
| `tb1_lab.yaml` | 해상도, 원점, 임계값과 이미지 경로 | Map Server |
| `tb1_lab.posegraph` | SLAM 제약 그래프 | 매핑 재개·수정 |
| `tb1_lab.data` | pose graph 센서 보조 데이터 | 매핑 재개·수정 |

PGM·YAML은 자율주행용 결과이고 pose graph는 향후 지도를 이어서 만들기 위한 원본에
가깝다. Public 저장소에는 민감한 공간 구조를 올리지 않는다.

## 웹 Action 경계

터미널 검증 뒤 Fleet Gateway에 로봇별 `NavigateToPose` Action Client를 추가한다.

```text
POST Goal -> action goal accepted/rejected
WebSocket  -> distance remaining, navigation time, recovery count
POST cancel -> cancel accepted/rejected
terminal state -> SUCCEEDED | ABORTED | CANCELED | TIMEOUT
```

HTTP 요청 thread가 ROS action 완료까지 무한 대기하지 않는다. Goal ID별 상태를 저장하고
WebSocket으로 진행 상태를 전달한다. e-stop은 Goal 취소와 별개로 로봇 watchdog가 즉시
정지시키며, e-stop 해제만으로 이전 Goal을 자동 재개하지 않는다.

## 완료 조건

- [x] TB1 Nav2, SLAM Toolbox와 rosdep 설치
- [x] `/scan`, `/odom`, TF와 기존 운영 서비스 사전 점검
- [x] Nav2 속도 경계와 저속 설정 자동 테스트
- [x] 로컬 전체 83개, navigation 19개와 TB1 navigation 15개 테스트 통과
- [x] TB1에서 고정 360-bin 스캔과 `/map`, `map -> odom` 무이동 검증
- [x] Zenoh 최소 권한과 watchdog 단일 `/cmd_vel` Publisher 검증
- [ ] 안전한 공간 저속 매핑과 지도 저장
- [ ] 지도 품질 검토와 AMCL 초기 위치 검증
- [ ] 터미널 Goal 성공·취소·실패·e-stop 검증
- [ ] Fleet Gateway Action Client와 웹 진행 상태 구현
- [ ] systemd 운영과 프로세스 복구 검증
- [ ] Phase 5 PR CI와 squash merge

## 참고

- [Nav2 Tuning Guide](https://docs.nav2.org/tuning/index.html)
- [Nav2: Navigating while Mapping](https://docs.nav2.org/tutorials/docs/navigation2_with_slam.html)
- [SLAM Toolbox Humble 문서](https://docs.ros.org/en/humble/p/slam_toolbox/)
