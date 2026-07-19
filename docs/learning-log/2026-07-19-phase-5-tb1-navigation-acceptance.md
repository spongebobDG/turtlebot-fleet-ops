# 학습 일지: Phase 5 TB1 로컬 Nav2 실차 수용 시험

날짜: 2026-07-19

단계: Phase 5 TB1 로컬 Nav2와 웹 목적지 제어

진행 상태: 실차 수용 시험 완료, 센서 사각과 반복 큰 방향 전환 제한사항 기록

## 오늘의 목표

로봇 없는 환경에서 구현한 Phase 5를 실제 TB1에 배포하고 다음 경계를 끝에서 끝으로
검증한다.

1. 보호 이동으로 실제 지도를 만들고 pose graph와 함께 저장한다.
2. 저장 지도, AMCL과 웹 초기 위치로 `READY`를 만든다.
3. 웹 목표 성공·취소·WARN·중복 거부와 속도 상한을 확인한다.
4. e-stop, Zenoh 단절과 프로세스 장애에서 0 출력과 무재개를 측정한다.
5. 10분 동안 navigation stack의 CPU·메모리 경고 지속 여부를 기록한다.
6. 발견한 실패를 코드·자동 테스트·운영·공부 문서까지 되돌려 반영한다.

## 시험 환경과 안전 기준

- TB1: Ubuntu 22.04 aarch64, ROS 2 Humble, CycloneDDS, domain 42
- 관제 PC: Windows와 WSL2 Ubuntu 22.04, Fleet Gateway, Zenoh 1.9.0
- 연결: TB1 2.4 GHz Wi-Fi, 정확한 주소와 SSID는 로컬 설정에만 보관
- 속도 상한: 0.05 m/s, 0.3 rad/s
- 작업자: 전원 스위치에 접근 가능한 빈 공간에서 현장 확인
- 명령 원칙: 한 번에 하나의 짧은 목표 또는 하나의 장애만 주입

최종 배포 revision은 `4b4e609`이며 TB1에서 다음 결과를 확인했다.

```text
Summary: 223 tests, 0 errors, 0 failures, 0 skipped
```

이 값은 당시 실행 명령이 출력한 역사적 결과다. 같은 날 Phase 6 배포 절차를 package별로
한정해 감사한 결과, 삭제된 `fleet_navigation`의 과거 build 결과가 이 합계에 포함됐음을
확인했다. 현재 소스 기준 TB1 회귀 수치는 144개이며 과거 출력은 원시 기록으로만 보존한다.

실차 원시 evidence는 Git에서 제외되는 다음 로컬 디렉터리에 모았다.

```text
output/tb1-acceptance/20260719-032012/
output/tb1-acceptance/soak-20260719-032628/
```

## 지도 작성과 산출물

일반 teleop 대신 `supervised_motion`의 dry-run, 5 cm 직진과 30도 회전을 사용했다. 각
구간에서 단일 입력 Publisher, 전방 clearance, odom 자세 연속성과 최종 e-stop을 확인했다.
작업자는 최초 5 cm와 30도 회전이 물리적으로 정상임을 직접 확인했다.

저장 결과:

| 항목 | 값 |
| --- | ---: |
| width × height | 58 × 96 cell |
| resolution | 0.05 m/cell |
| origin | (-2.26, -1.06, 0 rad) |
| known cell | 2,971 |
| known ratio | 0.5336 |
| occupied/free/unknown | 294 / 2,677 / 2,597 |
| pose graph 크기 | 7,025,673 byte |
| map data 크기 | 100,899 byte |

`map.yaml`, `map.pgm`, `map.posegraph`, `map.data`를
`~/.local/share/turtlebot-fleet-ops/maps/tb1/`에 저장했다. `MAP_VALIDATION=PASS`와 파일
hash를 evidence에 남겼고 실제 공간 지도는 Git에 넣지 않았다.

## AMCL 초기 위치와 READY

매핑 프로필을 끄고 저장 지도 navigation 프로필을 시작했다. 저상 장애물을 제거한 뒤
LaserScan을 지도에 직접 대조한 위치는 약 `(-0.975, -0.395, 9°)`, AMCL은 약
`(-0.956, -0.356, 9°)`였다. 평면 위치 차이는 약 4.4 cm였다.

웹 초기 위치 요청 뒤 새 `/amcl_pose`를 받은 경우에만 `localization_ready=true`가 됐다.
AMCL은 로봇이 정지하면 이동량 임계값 때문에 같은 pose를 계속 발행하지 않을 수 있다.
따라서 초기 위치 이후 첫 유효 pose를 latch하도록 수정했고 정지 12초 뒤에도 `READY`가
유지되는 것을 재시험했다. 새 초기 위치 요청과 agent 재시작은 이 latch를 다시 초기화한다.

## 웹 목표와 API 계약

### 성공 목표

| 시험 | 결과 |
| --- | --- |
| 가까운 전진 목표 | 약 13.6초, 약 18.7 cm 이동, recovery 0, `SUCCEEDED` |
| 장애물 제거 후 재검증 | 약 5.6초, 약 9.6 cm 이동, recovery 0, `SUCCEEDED` |

`/motion/navigation/cmd_vel`, arbiter 출력과 최종 `/cmd_vel`에서 관찰한 최대값은 모두
0.05 m/s와 0.3 rad/s 이하였다. ROS graph의 `/cmd_vel` Publisher는 다음 하나뿐이었다.

```text
/safety_watchdog  safety_watchdog_guard
```

### 명시적 취소

이동 중 DELETE 요청을 보내고 약 0.978초 뒤 `CANCELED`, 빈 active command와 0 출력을
확인했다. 취소 뒤 새 요청 없이 이동이 다시 시작되지 않았다.

### WARN 확인과 중복 목표

CPU 부하 프로세스 세 개로 제어된 `HIGH_CPU` WARN을 만들었다. CPU가 약 93.4%인 상태에서
다음 계약을 확인한 뒤 부하 unit을 모두 제거했다.

| 요청 | HTTP 결과 |
| --- | --- |
| `confirm_warnings=false` | 409 |
| `confirm_warnings=true` | 202, 목표 성공 |
| 활성 목표 중 새 목표 | 409 |

새 목표는 기존 목표를 자동 교체하지 않았고 잘못된 command ID의 취소도 현재 목표의
소유권을 바꾸지 않았다.

## e-stop 실차 전이

주행 중 e-stop은 watchdog 서비스를 먼저 잠그고 그 뒤 lease와 action을 정리했다.

| 측정 | 값 |
| --- | ---: |
| watchdog 비영점→0 | 약 0.003초 |
| Gateway 요청 응답 | 약 0.295초 |
| API 요청→안전 terminal | 약 0.983초 |

결과는 `CANCELED`, active command와 lease 없음이었다. 해제 뒤 policy는
`WAITING_NEUTRAL`에서 시작했고 arbiter의 IDLE 0으로 재무장했다. 10초 동안 이전 목표가
자동 재출발하지 않았고 최종 odom 속도는 사실상 0이었다.

## Zenoh 단절과 lease 만료

활성 주행 중 로봇과 관제 사이 Zenoh 경로를 끊었다. 수신 측 monotonic 시각으로 마지막
lease부터 측정한 결과다.

| 사건 | 마지막 lease 이후 |
| --- | ---: |
| 최종 `/cmd_vel=0` | 2.112초 |
| `LEASE_EXPIRED` | 2.263초 |

요구사항인 2초 lease 만료와 단절 뒤 2.5초 이내 0을 모두 충족했다. 연결 복구 뒤 이전
action과 lease는 살아나지 않았고 새 목표만 받을 수 있었다.

## 프로세스 장애 주입

각 시험은 한 번에 하나의 PID만 종료하고 새 PID, action terminal, `/cmd_vel`, odom과
자동 재개 여부를 확인했다.

| 장애 | 실제 결과 |
| --- | --- |
| navigation agent | launch 전체 종료 후 systemd 재시작, 약 14.54초에 새 main, 잔존 목표 취소, 무재개 |
| `bt_navigator` | action server 부재 뒤 `FAILED`, 첫 0 약 1.901초, process respawn, 무재개 |
| motion arbiter | 약 0.43초 command timeout 0, 새 arbiter IDLE, odom 안정 확인에 e-stop 추가 |
| Python watchdog policy | guard가 첫 0을 약 0.270초에 발행, 목표 취소, 무재개 |
| C++ watchdog guard | 약 0.105초에 재생성, 첫 0 약 0.955초, 목표 취소, 무재개 |

agent만 node respawn하면 같은 launch 안의 Nav2 프로세스와 오래된 endpoint가 남고 Zenoh의
service route도 stale해졌다. agent 종료가 launch 전체를 닫게 하고 systemd
`Restart=always`와 `ExecStartPost`의 Zenoh bridge 재시작으로 새 graph를 다시 광고하도록
바꿨다. 새 agent는 IDLE과 Nav2 cancel-all 응답을 확인한 뒤에만 ready가 된다.

## 가장 중요한 실패: watchdog Publisher 공백

### 최초 현상

처음 구조는 Python `safety_watchdog` 하나가 정책 판단과 `/cmd_vel` 발행을 모두 담당했다.
활성 목표 중 이 프로세스를 종료한 결과 child respawn은 약 0.761초에 감지됐지만 첫
`/cmd_vel=0`은 종료 뒤 3.491초에 나타났다. 그 사이에는 0을 내는 Publisher 자체가 없었고
목표가 끝날 수도 있었다.

“메시지를 더 이상 발행하지 않는다”는 것은 “명시적으로 0을 발행한다”와 다르다. base가
마지막 명령을 얼마나 유지하는지에 의존하므로 최종 안전 경계의 단일 고장점이었다.

### 보강 설계

```text
motion_arbiter
  -> /safety/cmd_vel_in
Python safety_watchdog_policy
  -> /safety/watchdog_cmd_vel
C++ safety_watchdog guard
  -> /cmd_vel
```

C++ guard는 `/cmd_vel`의 유일한 Publisher다. policy 입력을 0.25초 동안 받지 못하면 0을
발행하고, 0.05 m/s·0.3 rad/s clamp와 시작 후 중립 조건을 다시 적용한다. guard가
재시작하면 transient-local `/safety/watchdog_guard_restarted`를 발행해 늦게 시작한
policy도 반드시 `WAITING_NEUTRAL`로 되돌린다.

최종 장애 주입에서는 guard 재생성 약 0.105초, 관찰된 첫 0 약 0.955초, 목표
`CANCELED`, 빈 active command와 무재개를 확인했다. 자동 테스트에는 guard unit test,
ROS graph integration, 재시작 중립 계약과 sole Publisher 검사를 추가했다.

## 저상 장애물 Incident

첫 위치추정·주행 시도에서 로봇 앞의 낮은 장애물이 LiDAR 스캔 평면보다 아래에 있었다.
local costmap에는 장애물이 보이지 않아 recovery 회전과 위치추정 발산처럼 보이는 현상이
나타났다. 즉시 e-stop을 걸어 0과 빈 active command를 확인했다.

작업자가 장애물을 제거한 뒤 scan-map 위치를 다시 계산하고 AMCL을 재초기화했다. 이후 약
9.6 cm의 짧은 목표는 5.6초, recovery 0으로 성공했다. 이 사건의 결론은 다음과 같다.

- LiDAR가 관측하지 못하는 물체는 costmap도 회피할 수 없다.
- 지도 자유 셀 검사는 로봇 높이 전체의 물리적 자유 공간을 증명하지 않는다.
- 첫 주행 전 바닥의 케이블·문턱·낮은 물체는 사람이 별도로 확인해야 한다.
- software e-stop은 중요하지만 물리 전원 차단과 같은 계층은 아니다.

## 10분 navigation-stack 자원 soak

5초 간격으로 120개 표본을 기록했다.

| 지표 | 최소 | 평균 | 최대 | 90% 이상 표본 |
| --- | ---: | ---: | ---: | ---: |
| CPU | 59.80% | 69.14% | 85.20% | 0 |
| 메모리 | 20.50% | 20.63% | 20.70% | 0 |

이 시험은 navigation stack을 10분간 유지하면서 실제 목표와 fail-safe를 포함한 soak다.
완벽한 연속 왕복 주행으로 과장하지 않는다.

- 첫 목표는 약 5초에 성공했다.
- 큰 방향 전환 왕복 목표는 recovery 12회 뒤 status stale로 fail-safe `CANCELED`됐다.
- script가 다음 목표를 접수한 직후 추가 회전을 막기 위해 e-stop을 유지했다.
- 한 표본에서 `SCAN_STALE`이 관찰됐지만 지속되지 않았고 active 목표는 fail-safe로 닫혔다.
- 시험 종료 후 e-stop을 해제하고 IDLE 0으로 재무장했으며 이전 목표는 재개되지 않았다.

원래 완료 조건은 기존 90% CPU·메모리 경고가 10분 동안 지속되는지 기록하는 것이었다.
두 지표 모두 90% 표본이 0이므로 이 조건은 통과했다. 반복 큰 방향 전환의
recovery·stale는 별도 controller·costmap tuning 후보로 남긴다.

## 완료 판정

Phase 5의 필수 항목인 지도·pose graph, AMCL READY, 낮은 속도의 목표 성공, 명시적 취소,
WARN 확인, 단일 Publisher와 속도 상한, e-stop, lease 만료, agent·Nav2·arbiter·watchdog
장애, systemd 복구와 10분 자원 기록을 모두 실제로 실행했다. 실패에서 발견한 watchdog
Publisher 공백도 구조와 테스트로 보강하고 재배포했다.

따라서 Phase 5는 **실차 수용 시험 완료**로 판정한다. 다음 두 관찰은 숨기지 않고 운영
제한과 후속 tuning으로 유지한다.

1. LiDAR 평면보다 낮은 장애물은 작업 전 육안 점검이 필요하다.
2. 큰 방향 전환을 반복하는 왕복 경로는 recovery·stale 재현과 tuning이 필요하다.

## 후속 회귀: 제자리 방향 목표 비수렴과 로컬 감시 보강

Phase 7 재부팅 수정 배포 뒤 웹 경로를 다시 확인했다. 첫 제자리 시계 방향 약 90도 목표
`ef055833980d4675a79a83a57c0c6cf0`는 `READY → ACTIVE → SUCCEEDED`, recovery 0회,
Nav2 error 0으로 약 6초 안에 종료됐다. 두 번째 원래 방향 복귀 목표
`1c074134f54e4431b4319682c5fc86c8`는 같은 위치에서 yaw만 바꾼 요청이었지만 76.4초 동안
`ACTIVE`로 남았다. controller journal은 약 1.3초마다 `Passing new path to controller`를
기록했고 map-frame 자세는 목표 yaw로 수렴하지 않았다. odom은 계속 변했기 때문에 설치된 Nav2
progress checker는 실패를 선언하지 않았다.

운영자 취소 요청은 `ACTIVE → CANCELED`로 수락됐고 active command가 비었으며 최종 odom은
선속도 0, 각속도 약 0.001rad/s였다. 추가 이동은 하지 않았다. 당시 라이다 최단 거리가 다시
0.162m까지 줄어 현장 여유도 충분하지 않았다.

동시에 수집한 명령 경로는 다음과 같다.

| 토픽 | 표본 | 비영점 표본 | 최대 선속도 | 최대 각속도 | Publisher |
| --- | ---: | ---: | ---: | ---: | --- |
| `/motion/navigation/cmd_vel` | 782 | 782 | 0.05m/s | 0.3rad/s | velocity smoother·behavior server |
| `/safety/cmd_vel_in` | 908 | 782 | 0.05m/s | 0.3rad/s | motion arbiter |
| `/cmd_vel` | 909 | 781 | 0.05m/s | 0.3rad/s | safety watchdog 1개 |

속도 clamp와 단일 actuator Publisher는 정상이어도 목표 수렴 실패를 별도로 닫아야 한다는 증거다.
navigation agent에 map-frame 거리·yaw material progress 20초, feedback 3초, 전체 180초 감시를
추가했다. 거리 0.05m 또는 yaw 0.1rad가 개선될 때만 진척 창을 갱신하며, 초과 시 downstream을
취소하고 custom action `FAILED`, motion `IDLE`로 종료한다.

검증 결과는 Windows 지도·뷰포트 10개, 빠른 새 테스트 17개, navigation agent 97개, 전체
Humble workspace 218개 모두 실패 0이다. domain 142 navigation·Zenoh action·operations smoke와
ShellCheck·systemd·Windows 스크립트 검증도 통과했다. 별도 계측 노드 시작 순간 CPU 93.7%는
30초 재측정에서 최소 61.6%, 평균 65.15%, 최대 70.5%, 90% 이상 0회로 일시적이었다.

첫 TB1 배포에서는 새 stalled 통합 테스트가 lease 갱신용 ROS timer를 executor 실행 중 제거하면서
간헐 race를 만들었다. control PC와 CI에서는 통과했지만 TB1에서 executor thread가
`InvalidHandle`로 끝나 다음 action 응답이 timeout 됐다. 배포 스크립트는 즉시 실패하고 motion
서비스를 정지한 채 종료했다. timer entity를 제거하는 대신 별도 갱신 thread를 event로 멈추도록
바꾸고 격리 domain에서 같은 통합 테스트를 5회 연속 통과시켰다.

실패 배포가 통신 bridge까지 정지해 재시도 preflight가 Zenoh 7447을 거부했으므로, motion profile은
정지 상태로 유지하고 `tb1-zenoh-bridge.service`만 먼저 복구했다. 두 번째 배포는 TB1 전체 테스트와
감사 수집을 통과했고 코드 커밋 `cfab5f9`가 설치됐다. 배포 profile은 의도대로 IDLE이어서 저장 지도
navigation profile을 별도로 시작했다. 이전 비수렴 AMCL 자세는 자동 복원하지 않았다. 따라서
초기 pose 전 상태는 `UNAVAILABLE`, active command 없음, 선속도 0이며 목표 API는
`409 Nav2 is not ready`로 거부됐다. 설치 설정에서 20초·3초·180초 supervision 값을 확인했고
`/cmd_vel` Publisher는 watchdog 하나였다.

Phase 5 완료 시점에는 Phase 6가 robotless 상태여서 TB1 전체 MVP를 완료로 표시하지 않았다.
같은 날 이어서 실제 task와 복구를 검증한 결과는
[Phase 6 TB1 작업·복구 수용 시험](2026-07-19-phase-6-tb1-operations-acceptance.md)에 기록했고,
그 후 TB1 단일 로봇 MVP를 완료로 판정했다.

## 로컬 진척 감시 배포 뒤 웹 주행 재수용

보강 커밋을 `main`에 배포하고 navigation profile을 새로 시작한 뒤에는 이전 AMCL pose를 복원하지
않았다. 웹에서 실제 로봇 위치 `(-0.435, -0.485, -0.015rad)`를 다시 지정했고, Gateway는
2026-07-19 18:34:12 KST에 초기 위치 요청을 `202 Accepted`로 기록했다. AMCL의 새 pose와
`map → odom` 변환이 생긴 뒤 `nav2_ready=true`, `localization_ready=true`가 됐다.

이어 웹에서 목표 `(-0.035, 0.115, 1.601rad)`를 보냈다. Gateway command ID는
`23bdde9fa4c5402b86cfcac55fbf42d6`이며 18:34:26에 `202 Accepted`, TB1 Nav2는 18:34:27에
현재 위치 `(-0.44, -0.45)`에서 주행을 시작했다. controller는 recovery 없이 목표에 도달했고
18:34:48에 `Reached the goal!`, navigator는 `Goal succeeded`를 기록했다. 최종 fleet 상태는
다음과 같았다.

| 항목 | 결과 |
| --- | --- |
| 상태 전이 | `READY → ACTIVE → SUCCEEDED` |
| navigation time | 21.6006초 |
| recovery / Nav2 error | 0회 / 0 |
| 종료 뒤 active command | 빈 값 |
| 종료 뒤 motion mode | `IDLE` |
| 최종 map pose | `(-0.171, 0.134, 1.336rad)` |
| 종료 뒤 odom 속도 | 선속도 0, 각속도 약 0 |
| 종료 뒤 LiDAR 최소 거리 | 0.50~0.51m |
| `/cmd_vel` Publisher | `safety_watchdog` 1개 |

이번 재수용은 이전 비수렴 사건 뒤 AMCL을 다시 설정하고 로컬 진척 감시가 설치된 상태에서 웹
초기 위치·목표 경로가 실제 이동까지 이어지는지 확인한 회귀다. 성공한 목표에 20초 무진척
timeout을 억지로 발생시키지 않았으며, stalled fake Nav2 통합 테스트가 그 실패 경로를 담당한다.
목표 종료 뒤 0.5초 간격 6개 snapshot에서도 active command와 fault는 없고 선속도는 사실상 0을
유지했다. 추가 왕복 이동은 새 증거를 만들기 위해 불필요한 물리 위험을 늘리므로 수행하지 않았다.

## Phase 7 경로 회귀에서 발견한 초기 pose 안전 보강

Phase 5 완료 뒤 Phase 7의 추가 한 바퀴 경로 시험에서 약 180° 뒤집힌 초기 yaw 때문에 map pose와
실제 이동이 반대로 보였고 벽 접촉이 발생했다. 즉 “초기 pose가 free cell이고 AMCL pose가 한 번
나왔다”는 조건만으로 물리 정합을 보장할 수 없었다. 즉시 e-stop으로 목표와 lease를 폐기한 뒤
실시간 LiDAR endpoint overlay와 scan-map 자동 정렬을 추가했다.

잘못된 후보는 match 8%, 지도 내부 51%로 `422` 거부됐고 보정 후보는 match 92~93%, 지도 내부
99~100%였다. 이 회귀에 따라 Nav2 반경을 0.14m, 로컬 scan clearance를 0.20m로 높이고 현재
AMCL pose가 known free cell을 벗어나면 실행 중 목표도 취소하게 했다. Phase 5의 기존 수용 증거를
삭제하지 않되, 이후 주행은 자동 정렬 gate를 통과한 초기 pose에서만 수행한다. 상세 사건·측정은
[Phase 7 학습 일지](2026-07-19-phase-7-ros2-log-mlops-and-map-viewport.md)에 기록했다.

## CI 회귀: LiDAR 정합을 반영한 무로봇 fixture

초기 pose의 scan-map 정합 gate를 추가한 뒤 GitHub Actions의 무로봇 navigation smoke가
`422 Map has no occupied cells for LiDAR alignment`로 실패했다. 제품 코드의 오동작이 아니라
기존 fixture가 80×80 전체를 free cell로 만들고 모든 LiDAR ray를 3.5m로 고정했던 것이
원인이었다. 이 입력은 새 안전 gate가 검증하려는 실제 환경 관계를 표현하지 못한다.

fixture 지도를 4m 정사각형의 점유 경계와 자유 내부로 바꾸고, 현재 모의 pose에서 네 벽까지
ray-cast한 360개 LaserScan range를 발행하도록 수정했다. 격리 domain 142 재시험에서 READY,
목표 성공, 명시적 취소, e-stop 목표 취소, 해제 후 자동 재개 방지, watchdog 속도 상한
`0.05m/s`·`0.3rad/s`, 최종 0 입력을 모두 통과했다. 따라서 CI는 정합 검사를 우회하지 않고
지도와 LiDAR가 일치하는 정상 경로를 계속 회귀 검증한다.

별도의 task/fault mock도 RobotStatus에 scan 정상 플래그만 넣고 실제 `/scan`은 발행하지 않아
초기 pose가 `503 LiDAR scan unavailable`로 거부됐다. 이 mock에도 같은 점유 경계 지도와
pose 연동 LaserScan을 추가하고 smoke client가 40개 이상의 fresh point를 확인한 뒤 초기
pose를 전송하게 했다. Gateway 77개 테스트와 task 성공·취소·재시도·실패·fault/audit E2E가
통과했으며 마지막 상태는 의도대로 e-stop이었다.

## 실차 재개: 5cm 외곽 여유의 안전한 해석

TB1을 다시 배치한 뒤 e-stop 상태에서 6개 scan을 확인했다. 최소 거리는 0.215~0.224m였고
가장 가까운 반사는 로봇 기준 오른쪽 약 -90°였다. 전역 자동 정렬은 match 90.6%, 지도 내부
99.4%, score 0.900으로 `(0.125, -0.490, -0.035rad)` 후보를 제안했고 초기 pose 적용 뒤
Nav2·localization ready와 motion unarmed를 확인했다.

사용자가 요청한 “안전기준 5cm”는 로봇 외곽에서 장애물까지의 여유로 해석했다. LiDAR 중심
기준 0.05m는 TB1 footprint 반경 0.14m보다 작아 충돌 뒤에도 허용되는 값이므로 사용할 수 없다.
따라서 navigation agent의 scan 차단값은 `0.14m + 0.05m = 0.19m`로 설정했다. e-stop은 새 설정
배포와 정적 재검증이 끝날 때까지 유지한다.

커밋 `2ab6405`를 TB1에 fast-forward하고 navigation agent 102개 테스트를 통과시켰다. 실행 중
PID 23538의 명령행은 설치된 `config/tb1.yaml`을 직접 참조했고 해당 파일의 값은
`navigation_min_clearance_m: 0.19`였다. 서비스 재시작 직후에는 이전 목표를 복원하지 않고
AMCL 초기 pose를 다시 요구하며 `UNAVAILABLE`에 머무는 fail-closed 전이를 확인했다. e-stop
상태에서 다시 자동 정렬한 결과 match 88.8%, 지도 내부 99.4%, score 0.892였고 초기 pose 적용
후 `IDLE`, Nav2·localization ready, motion unarmed로 돌아왔다.

e-stop 해제 뒤 3초 정지 감시에서는 선속도 0, 각속도 노이즈 최대 0.00026rad/s로 자동 재출발이
없었다. 이어 현재 방향 0.15m 앞 목표 `eb262a3027434a73a00d8345935a8855`를 전송했다. Nav2의
0.10m goal tolerance를 포함한 실제 관측 이동은 0.071m였고 `SUCCEEDED`, recovery 0이었다.
최대 선속도 0.0342m/s, 최대 각속도 0.1558rad/s, 주행 중 최소 scan 0.225m로 모든 제한을
지켰다. 시험 종료 즉시 e-stop을 다시 걸었으며 motion unarmed, active command 없음이었다.

## 배운 점

1. ROS graph에서 Publisher가 사라지는 것과 0을 계속 발행하는 것은 다르다.
2. 안전 policy와 마지막 actuator Publisher를 분리하면 policy 프로세스 장애도 fail-closed로
   만들 수 있다.
3. systemd respawn은 가용성 복구일 뿐 이전 이동 권한 복구가 아니다.
4. action endpoint 발견, lifecycle ACTIVE, startup cancel-all 완료를 모두 확인해야 ready다.
5. AMCL readiness와 지속적인 pose stream freshness는 같은 조건이 아니다.
6. 장애물 회피 성능은 알고리즘뿐 아니라 센서 장착 높이와 관측 평면에 제한된다.
7. 자원 시험에서 평균과 최대뿐 아니라 threshold 이상 표본 수와 실패 상태도 함께 남겨야
   결과를 과장하지 않는다.

## 복습 문제와 정답

### 1. Python watchdog가 죽으면 아무 명령도 나오지 않으므로 안전한가?

정답: 아니다. base가 마지막 속도 명령을 유지할 수 있으므로 유일한 Publisher가 사라지는
것만으로 명시적 정지를 증명할 수 없다. 독립 guard가 timeout 뒤 0을 계속 발행해야 한다.

### 2. guard도 재시작했는데 왜 중립 입력을 다시 요구하는가?

정답: 재시작 전 비영점 policy 메시지나 이전 목표가 남아 있을 수 있기 때문이다. 프로세스
복구와 이동 권한 복구를 분리하고 IDLE 0을 새로 확인해야 자동 재출발을 막을 수 있다.

### 3. Zenoh 단절에 0.5초 authorization만 사용하지 않고 2초 lease도 쓰는 이유는?

정답: agent가 살아 있으면 로컬 authorization은 계속 갱신될 수 있다. 원격 명령 소유자인
Gateway가 사라진 장애는 별도 lease heartbeat로 감지해야 한다.

### 4. AMCL이 2초 동안 새 pose를 발행하지 않으면 즉시 LOCALIZING으로 돌아가야 하는가?

정답: 아니다. 정지 로봇은 이동량 임계값 아래에서 같은 pose를 반복 발행하지 않을 수 있다.
초기 위치 이후 첫 유효 pose를 latch하고 Nav2 transform·robot·safety·lease freshness를
별도로 검사한다.

### 5. OccupancyGrid의 free cell이면 실제 바닥도 반드시 안전한가?

정답: 아니다. 지도는 LiDAR가 관측한 평면을 기준으로 하므로 그 아래의 낮은 장애물은
free로 보일 수 있다. 센서 한계와 현장 육안 점검이 별도로 필요하다.

### 6. 10분 soak를 성공적인 연속 왕복 주행이라고 말할 수 있는가?

정답: 아니다. navigation stack의 자원 경고 지속 여부는 통과했지만 한 큰 방향 전환 목표는
recovery 후 stale 취소됐고 후반은 e-stop 상태였다. 각각의 기준과 관찰을 분리해 말해야 한다.

## 관련 커밋

- `e96c035 fix: latch confirmed AMCL localization`
- `ae71ecc fix: make TB1 motion recovery fail closed`
- `3ca464e fix: stream TB1 scripts without PowerShell BOM`
- `7d0e3bd fix: guard watchdog output fail closed`
- `13aab7b test: assert guarded watchdog recovery contract`
- `4b4e609 fix: disarm motion across watchdog guard restart`
