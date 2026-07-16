# 학습 일지: TB1 잔류 텔레옵 명령 안전 Incident와 모션 가드

날짜: 2026-07-16
단계: Phase 5 TB1 실차 매핑
진행 상태: Incident 조치·소프트웨어 개선·TB1 실제 graph dry-run 완료, 저속 실물 검증 전

## 한 줄 결론

e-stop이 0속도를 출력 중이라는 사실만 확인하고 원시 안전 입력의 잔류 명령을 확인하지
않아, e-stop 해제 시 TB1이 예상하지 않은 직진을 시작했다. 즉시 전체 실험 데이터를
폐기하고 모터 bringup까지 중지했으며, 텔레옵과 공존하지 않는 fail-closed 전용 모션
가드와 48개 패키지 테스트를 추가했다.

## 오늘의 목표

- 1m × 1m 안전 구역에서 TB1의 작은 기능 검증용 지도를 만든다.
- 사용자가 직접 저속 텔레옵을 경험하되 watchdog 안전 경계를 유지한다.
- 이동량과 지도 품질을 수치와 이미지로 검증한다.
- 문제가 생기면 결과를 성공으로 포장하지 않고 원인과 재발 방지를 기록한다.

## Incident 요약

| 항목 | 실제 결과 |
| --- | --- |
| 영향 로봇 | TB1 |
| 사람 피해 | 없음 |
| 충돌 | 없음 |
| 장비 파손·분리 | 없음 |
| 사용자 조치 | 갑작스러운 전진을 직접 잡아 정지 후 중앙 재배치 |
| 잘못 기록된 오도메트리 | 원점 기준 약 1.8239m |
| 폐기한 데이터 | 케이블 구속 및 잔류 명령 중 생성된 지도와 자세 기록 |
| 최종 안전 상태 | e-stop 활성, 텔레옵·SLAM·bringup 중지, OpenCR 포트 소유자 없음 |

## 정상적으로 검증한 부분

Incident 전 새 기준에서 오도메트리를 0으로 초기화하고 전방 LiDAR 최소 거리 0.754m를
확인했다. 첫 직진은 별도 거리 가드로 다음처럼 정상 종료했다.

- 목표 거리: 0.1000m
- 가드 감지 거리: 0.1010m
- 최종 오도메트리 x: 0.1088m
- 약 8.8mm 정지 오차
- 종료 뒤 `/cmd_vel`: 0
- e-stop: 활성
- SLAM 오류: 없음

이 결과는 시간 추정이 아니라 오도메트리 feedback으로 정지한 작은 폐루프 검증이었다.

## 사고 전개

### 1. e-stop 상태에서 downstream만 확인

watchdog가 `/cmd_vel`에 0을 발행하고 있다는 것을 확인했다. 그러나 e-stop은 upstream의
비영점 입력을 가려 0으로 바꾸므로, 이 결과만으로 텔레옵 내부 목표가 중립이라는 사실은
증명되지 않는다.

### 2. 텔레옵 프로세스가 계속 존재

`teleop_keyboard`는 키를 한 번 누를 때만 단순 pulse를 보내는 도구가 아니라 목표 선속도와
각속도를 내부 상태로 유지하는 조작기다. 이전 직진 목표가 남아 있으면 e-stop 해제 후 다시
비영점 입력이 전달될 수 있다.

### 3. 회전 가드가 e-stop을 해제

회전 가드는 중립 메시지를 별도로 발행한 뒤 e-stop을 해제했다. 중립 메시지는 watchdog의
재무장 조건은 만족시켰지만, 다른 Publisher인 텔레옵의 내부 목표를 바꾸지는 못했다.

### 4. 실제 증거

회전 가드 준비 직후 다음 값이 관측됐다.

```text
linear.x = 0.05
angular.z = 0.0
```

의도한 회전이 아니라 직진이었다. 이후 오도메트리는 원점에서 약 1.8239m 이동한 것으로
기록됐다. 사용자가 로봇을 직접 잡았고 충돌과 파손은 없었다.

### 5. 회전 진행량 계산도 잘못됨

초기 임시 가드는 매 odom 샘플의 yaw 변화량 절댓값을 더했다. 작은 양·음 잡음도 모두 양수로
누적되므로 실제 순회전은 약 2.6°였지만 누적값은 90°에 도달했다. 이 결과 역시 폐기했다.

## 직접 원인과 기여 요인

### 직접 원인

e-stop 해제 시 `/safety/cmd_vel_in`에 잔류 비영점 직진 명령을 내는 Publisher가 존재했다.

### 절차 원인

- e-stop으로 가려진 최종 `/cmd_vel`만 확인했다.
- 원시 안전 입력 값과 Publisher 소유권을 해제 전에 검증하지 않았다.
- 텔레옵과 자동 가드가 같은 입력 토픽을 동시에 소유했다.
- “사용자가 중립 키를 눌렀다”는 절차 확인을 시스템 검증으로 대체하지 못했다.

### 계산 원인

회전 진행량에서 부호 있는 순변위가 아니라 잡음 절댓값의 총합을 사용했다.

### 물리 기여 요인

앞선 시도에서는 임시 LiDAR 점퍼선이 바퀴 이동을 방해했다. 이 구간의 wheel odometry와 지도도
실제 이동을 정확히 나타내지 않으므로 모두 폐기했다.

## 즉시 조치

1. e-stop을 다시 활성화했다.
2. `/cmd_vel` 0을 확인했다.
3. 텔레옵 프로세스를 종료했다.
4. SLAM 세션과 왜곡된 지도를 폐기했다.
5. `tb1-bringup`을 중지해 모터 드라이버 프로세스를 제거했다.
6. `/dev/ttyACM0` OpenCR 포트 소유자가 없음을 확인했다.
7. 사용자가 충돌·파손·분리 없음과 중앙 재배치를 확인했다.

## 재발 방지 설계

`fleet_navigation`에 `supervised_motion` 실행 파일을 추가했다.

### 단독 명령 소유

실행 중 `/safety/cmd_vel_in` Publisher는 `supervised_motion` 하나만 허용한다. 텔레옵 또는
Zenoh 브리지가 발견되면 e-stop을 유지하고 실행을 거부한다.

### 실제 모터 경로 검증

최종 `/cmd_vel` Publisher는 `safety_watchdog` 하나여야 하며, Subscriber는 가드의 0속도
검증 구독과 `turtlebot3_node`만 허용한다.

### 무동작 dry-run

`dry_run:=true`에서는 e-stop 해제 호출을 한 번도 하지 않는다. Publisher 독점권, odom,
LiDAR, 최종 0속도와 ROS graph만 검증하고 성공하면 그대로 잠긴 상태로 종료한다.

### 직진 진행량

단순 직선거리가 아니라 시작 heading에 투영한 부호 있는 이동량을 사용한다.

- 명령 반대 방향 2cm 초과: 실패
- 횡방향 이탈 5cm 초과: 실패
- 전방 sector 최소 거리 30cm 미만: 실패
- odom 또는 scan 0.5초 이상 stale: 실패

### 회전 진행량

각 샘플의 wrapped signed delta를 합산한 뒤 명령 방향으로 투영한다. 양·음 잡음은 상쇄되고
±π 경계도 연속적으로 처리된다. 역방향 회전이 제한을 넘으면 실패한다.

### 모든 종료 경로

- 정상 목표 도달: 0속도 → e-stop → 0속도 확인
- timeout·센서 stale·그래프 변경·예외: 즉시 e-stop → 0속도 반복
- Ctrl-C: fail-closed 정지

## 자동 검증 증거

### 순수 로직 테스트

- ±π 각도 래핑
- 회전 잡음 상쇄
- 역방향 회전 검출
- 직진 heading 투영
- 역방향·횡방향 이동 계산
- LiDAR sector wrap과 invalid range 제외
- 속도 상한과 잘못된 요청 거부

### ROS graph 통합 테스트

가짜 `safety_watchdog`, `turtlebot3_node`, odom, LaserScan을 실제 ROS graph에 구성했다.

- 단독 Publisher에서 목표 거리 도달 후 e-stop 활성: 통과
- dry-run의 e-stop 해제 호출 0회와 이동량 0: 통과
- 가짜 `teleop_keyboard` Publisher 존재 시 이동 거부와 위치 0: 통과

### 결과

```text
fleet_navigation: 48 tests, 0 errors, 0 failures, 0 skipped
전체 5개 패키지: 111 tests, 0 errors, 0 failures, 0 skipped
```

GitHub Actions의 공식 ROS Humble Jammy 컨테이너에서도 의존성 설치, 전체 빌드와 테스트가
모두 성공했다.

## TB1 실제 graph dry-run

TB1을 커밋 `377cb64`로 업데이트하고 로봇 자체에서 `fleet_navigation` 48개 테스트를 다시
실행해 모두 통과했다. 그 뒤 다음 조건으로 실제 graph dry-run을 수행했다.

- `tb1-bringup`: active
- `tb1-slam-mapping`: active
- `tb1-zenoh-bridge`: inactive
- 텔레옵 프로세스: 없음
- dry-run 시작 전 `/safety/cmd_vel_in` Publisher: 0
- e-stop: active

실제 결과는 다음과 같다.

```text
DRY_RUN_EXIT=0
SUPERVISED_MOTION_DRY_RUN_SUCCESS e-stop remains active
종료 후 /safety/cmd_vel_in Publisher count=0
종료 후 /cmd_vel linear.x=0.0 angular.z=0.0
```

따라서 실제 배포된 노드 이름, endpoint 집합, odom·scan freshness, watchdog 서비스와 최종
0속도 계약은 바퀴를 움직이지 않고 검증됐다.

## RMW 불일치 실차 사전 차단

첫 5cm 검증 시 원격 셸의 `RMW_IMPLEMENTATION`이 `UNSET`인 상태에서 서비스를 호출했다.
TB1 watchdog와 bringup은 `rmw_cyclonedds_cpp`였기 때문에 일반 토픽과 endpoint는 보였지만
e-stop 서비스 응답이 반환되지 않았다. watchdog에는 해제 요청이 도착했으나 guard에는 응답이
돌아오지 않아 비영 이동 명령 전 단계에서 멈췄고, odometry 진행량도 관찰되지 않았다.

명시적으로 다음 값을 설정하자 같은 e-stop 서비스가 즉시 성공했다.

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

재발 방지를 위해 watchdog은 시작부터 e-stop을 활성화하고 transient-local 상태 토픽
`/safety/estop_active`를 발행한다. `supervised_motion`은 Cyclone DDS 환경이 아니면 ROS node를
시작하기 전에 종료하고, 서비스 성공뿐 아니라 상태 토픽 전이까지 확인한다.

```text
safety_watchdog + fleet_navigation: 69 tests passed
전체 테스트 결과: 115 tests, 0 errors, 0 failures, 0 skipped
```

## 5cm 보호 이동 시스템 검증

사용자가 전방 30cm 이상, 케이블 고정, 중앙 배치와 바퀴 자유 상태를 확인한 뒤 첫 저속
직진을 실행했다. 실행 환경은 `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`였고 Zenoh와 텔레옵은
중단했으며, 시작 전 `/safety/cmd_vel_in` Publisher는 0개였다.

```text
실행 커밋: 42851f2
목표: 0.0500 m
속도: 0.0200 m/s
guard progress: 0.0520 m
guard elapsed: 2.87 s
독립 odom delta x: 0.056323 m
독립 odom delta y: 0.001453 m
guard exit: 0
종료 e-stop: true
종료 /cmd_vel: linear.x=0.0, angular.z=0.0
종료 /safety/cmd_vel_in Publisher: 0
```

시스템 측정은 목표 전진과 작은 횡이탈, 자동 정지를 증명했다. 사용자는 실제로 약 5cm를
정상 방향으로 이동했고 충돌과 케이블 이상이 없었다고 확인했다.

그 뒤 e-stop 상태를 2Hz heartbeat로 재발행하는 커밋 `edcbf87`을 TB1에 배포했다. TB1의
`safety_watchdog` 18개 테스트와 GitHub Actions가 통과했고, 늦게 시작한 CLI가 서비스 재호출
없이 `/safety/estop_active data:true`를 수신했다.

## 30도 보호 회전 시스템 검증

사용자가 5cm 이동의 물리 결과와 30도 회전 준비 상태를 확인한 뒤 양의 yaw 방향으로 한 번
회전했다. 시작 전 e-stop은 `true`, 안전 입력 Publisher는 0개, Zenoh와 텔레옵은 중단 상태였다.

```text
실행 커밋: edcbf87
목표: 0.523599 rad (30.000 deg)
속도: 0.100 rad/s
guard progress: 0.5249 rad (30.075 deg)
guard elapsed: 5.80 s
독립 odom yaw delta: 0.545272 rad (31.242 deg)
guard exit: 0
종료 e-stop: true
종료 /cmd_vel: linear.x=0.0, angular.z=0.0
종료 /safety/cmd_vel_in Publisher: 0
```

부호 있는 wrapped yaw 진행량과 독립 odometry가 모두 목표 방향 회전을 증명했다. 사용자는
실제 30도 회전과 방향이 정상이고 충돌과 케이블 이상이 없다고 확인했다. 따라서 짧은 보호
이동만 사용하는 지도 작성 단계로 진행할 수 있다.

## 첫 매핑 구간의 LiDAR 차단 검증

지도 작성을 시작하며 10cm 직진을 요청했지만 guard가 전방 최소 여유 `0.268m`를 감지해
`minimum_clearance_m=0.30` 계약으로 실행을 거부했다.

```text
guard exit: 1
failure: clearance dropped to 0.268 m
odom delta x: 0.000000 m
odom delta y: -0.000000 m
종료 e-stop: true
종료 /cmd_vel: linear.x=0.0, angular.z=0.0
종료 /safety/cmd_vel_in Publisher: 0
```

이는 실차 실패가 아니라 장애물 앞 이동 차단이 의도대로 작동한 검증 결과다. 이동 없이
15도 간격으로 LiDAR 방향별 여유를 계산했고, 현재 정면은 약 `0.296m`, 가장 여유 있는 방향은
로봇 기준 `-45°`에서 `1.452m`였다. 사용자가 시계 방향 45도 회전 반경과 케이블 상태를
확인한 뒤 보호 회전하고, 새 정면 여유를 다시 측정한다.

실제로 시계 방향 45도를 회전한 뒤 정면 여유는 `0.355m`였다. guard 회전은 성공했고
독립 odometry는 `-46.176°`, 종료 e-stop과 0속도도 정상이었지만, 1회 스캔에서 예측한
`1.452m`와 차이가 커서 직진하지 않았다. 이후 30회 스캔의 방향별 최소값을 비교하자
로봇 기준 `-75°`가 최소 `0.962m`, 중앙값 `1.535m`로 가장 안정적이었다. 안전 방향 선택도
한 장의 센서값이 아니라 시간 구간의 보수적 통계로 판단해야 한다.

## 재배치 후 클린 맵 첫 구간

사용자가 전방 50cm 이상 여유가 있는 위치로 로봇을 손으로 재배치했다. 손 이동은 encoder
odometry에 반영되지 않으므로 실행 중이던 SLAM 지도를 계속 사용하면 sensor pose와 motion
prior가 불일치한다. e-stop 상태에서 기존 초기 지도를 폐기하고 `tb1-slam-mapping`을 재시작해
현재 물리 위치를 새 지도 기준으로 삼았다.

30회 LiDAR 전방 sector의 보수적 최소값 `0.677m`를 확인한 뒤 첫 10cm 구간을 실행했다.

```text
목표: 0.1000 m
속도: 0.0200 m/s
guard progress: 0.1012 m
guard elapsed: 5.37 s
독립 odom delta x: 0.105077 m
독립 odom delta y: 0.005871 m
guard exit: 0
종료 e-stop: true
종료 /cmd_vel: linear.x=0.0, angular.z=0.0
종료 /safety/cmd_vel_in Publisher: 0
map known cells: 288
map occupied cells: 51
map unknown: 96.17%
```

시스템은 목표 이동·자동 정지·SLAM 갱신을 증명했다. 사용자는 실제 10cm 전진과 방향이
정상이고 충돌과 케이블 이상이 없다고 확인했다.

같은 방향의 두 번째 10cm 구간은 30회 전방 최소 여유 `0.725m`를 확인한 뒤 실행했다.

```text
목표: 0.1000 m
guard progress: 0.1007 m
guard elapsed: 5.30 s
독립 odom delta x: 0.103833 m
독립 odom delta y: 0.004944 m
guard exit: 0
종료 e-stop: true
종료 /cmd_vel: linear.x=0.0, angular.z=0.0
종료 /safety/cmd_vel_in Publisher: 0
map known cells: 618
map occupied cells: 108
```

지도 격자 범위가 이동에 따라 확장되어 unknown 비율만 단순 비교하지 않고, known·occupied
cell 수와 지도 이미지 품질을 함께 판단한다. 사용자는 두 번째 10cm 전진과 방향이 정상이고
충돌과 케이블 이상이 없다고 확인했다.

세 번째 10cm 구간은 30회 전방 최소 여유 `0.737m`에서 실행했다.

```text
guard progress: 0.1002 m
guard elapsed: 5.34 s
독립 odom delta x: 0.105311 m
독립 odom delta y: 0.004762 m
종료 e-stop: true
종료 /cmd_vel: linear.x=0.0, angular.z=0.0
map known cells: 618
map occupied cells: 108
```

같은 직선 방향을 반복한 뒤 known cell이 늘지 않았으므로 다음 물리 확인 뒤에는 추가 직진보다
새 각도의 스캔을 얻는 방향 전환을 우선한다.

사용자는 세 번째 10cm 전진과 방향이 정상이고 충돌과 케이블 이상이 없다고 확인했다.
회전 반경과 케이블 여유를 다시 확보한 뒤 시계 방향 90도 보호 회전을 실행했다.

```text
목표: 1.570796 rad (90 deg)
속도: -0.100 rad/s (clockwise)
guard progress: 1.5747 rad
guard elapsed: 16.59 s
guard exit: 0
독립 odom yaw delta: -1.594615 rad (-91.365 deg)
종료 e-stop: true
종료 /cmd_vel: linear.x=0.0, angular.z=0.0
종료 /safety/cmd_vel_in Publisher: 0
새 정면 30-scan 최소 여유: 0.672 m
새 정면 30-scan 중앙값: 0.728 m
map size: 180 x 106 at 0.05 m/cell
map known cells: 618 (3.24%)
map occupied cells: 108
```

guard와 별도 odometry가 모두 시계 방향 회전을 증명했고 종료 안전 조건도 통과했다. 제자리
회전만으로 known cell 수는 증가하지 않았다. 이는 같은 위치의 LiDAR가 방향만 바뀌어도 전체
360도 스캔 자체는 이미 같은 주변을 관측하고 있었기 때문이다. 다음 지도 확장은 회전의 사용자
물리 관찰을 확인한 뒤 새 정면 방향으로 짧게 이동해야 한다.

## 병렬 CI 테스트 격리

GitHub Actions에서 `safety_watchdog` 테스트가 `fleet_navigation`의 가짜 watchdog 응답
`fake e-stop updated`를 받아 1회 실패했다. 제품 코드 오류가 아니라 두 패키지 통합 테스트가
같은 절대 서비스 `/safety_watchdog/set_estop`을 ROS domain 142에서 병렬 사용한 경쟁이었다.
가짜 서비스를 `/test/fleet_navigation/set_estop`으로 분리하고 CI와 동일한 5개 패키지 병렬
실행에서 `116 tests, 0 errors, 0 failures`를 확인했다.

## 오늘 꼭 기억해야 할 것

1. **e-stop 중 `/cmd_vel=0`은 upstream 입력이 중립이라는 증거가 아니다.**
2. **e-stop 해제 전 원시 입력 값과 Publisher 소유권을 함께 확인해야 한다.**
3. **상태를 가진 텔레옵과 자동 명령 노드를 같은 입력 토픽에 동시에 연결하지 않는다.**
4. **중립 메시지 하나는 다른 Publisher의 내부 목표를 초기화하지 못한다.**
5. **회전량은 절댓값 합이 아니라 wrapped signed delta의 순합으로 계산한다.**
6. **wheel odometry는 바퀴가 걸리거나 미끄러지면 실제 이동과 달라질 수 있다.**
7. **잘못된 실차 데이터는 보정해서 쓰지 말고 폐기 사유와 함께 다시 측정한다.**
8. **실차 기능은 unit test → ROS 통합 test → 실제 graph dry-run → 저속 실물 순서로 올린다.**
9. **토픽 성공은 서비스 성공의 증거가 아니다. 모든 ROS 터미널의 RMW를 통일한다.**
10. **로봇을 손으로 재배치하면 활성 SLAM의 odometry 전제가 깨지므로 지도를 새로 시작한다.**
11. **ROS 통합 테스트의 절대 topic·service 이름도 패키지 간 격리해야 한다.**
12. **360도 LiDAR의 제자리 회전은 방향을 바꾸지만 반드시 known 영역을 늘리지는 않는다.**

## 면접에서 이렇게 설명한다

### 30초 답변

> SLAM 매핑 중 software e-stop을 해제했을 때 텔레옵의 잔류 직진 명령으로 로봇이 예상하지
> 않게 움직인 incident가 있었습니다. 최종 `/cmd_vel=0`만 확인해 upstream 비영점 입력이
> e-stop에 가려진 것을 놓친 것이 원인이었습니다. 즉시 e-stop, 텔레옵·SLAM·bringup 종료와
> 데이터 폐기를 수행했고, 이후 입력 Publisher 독점권, 무동작 dry-run, odom·LiDAR 기반
> 목표 정지와 fail-closed 종료를 가진 전용 가드를 구현했습니다. 가짜 ROS graph 통합
> 테스트를 포함한 전체 116개 테스트와 저속 실차 guard로 재발 방지를 검증했습니다.

### “왜 사용자 실수로 보지 않았나요?”

> 안전 시스템은 사용자가 올바른 키를 눌렀다는 가정에 의존하면 안 됩니다. 해제 전에 시스템이
> 실제 입력 중립과 Publisher 소유권을 증명하지 못한 것이 설계 문제였습니다. 그래서 절차 안내가
> 아니라 실행 거부 조건으로 바꿨습니다.

### “왜 해당 지도와 odometry를 폐기했나요?”

> 케이블 구속과 wheel slip이 있으면 encoder 기반 odometry가 실제 이동보다 크게 적분될 수 있고,
> SLAM은 잘못된 motion prior로 지도를 왜곡할 수 있습니다. 신뢰 경계가 깨진 데이터는 사후 숫자
> 보정으로 복구할 근거가 없으므로 원인을 기록하고 깨끗한 기준에서 재측정했습니다.

## 복습 문제와 정답

### 1. e-stop 중 `/cmd_vel`이 0이면 왜 안전 입력도 0이라고 결론 내릴 수 없는가?

정답: watchdog가 upstream 비영점 입력을 0으로 덮어 최종 출력에 숨길 수 있기 때문이다.
해제 판단에는 `/safety/cmd_vel_in`과 Publisher 목록을 별도로 확인해야 한다.

### 2. 중립 명령을 한 번 발행했는데 텔레옵 목표가 남을 수 있는 이유는?

정답: 중립 메시지와 텔레옵은 서로 다른 Publisher이며 한 Publisher의 메시지가 다른 프로세스의
내부 상태를 변경하지 않기 때문이다.

### 3. yaw 변화량 절댓값을 계속 더하면 왜 위험한가?

정답: 실제 순회전이 없어도 양·음 센서 잡음이 모두 양수로 누적돼 목표 각도에 도달했다고 오판할
수 있기 때문이다.

### 4. 실차 dry-run이 unit test와 다른 가치는 무엇인가?

정답: 실제 배포된 노드 이름, Publisher·Subscriber 집합, QoS, 센서 freshness와 e-stop 서비스
연결을 바퀴를 움직이지 않고 검증할 수 있기 때문이다.

### 5. Publisher 단독 소유가 timeout만큼 중요한 이유는?

정답: timeout이 정상적으로 동작해도 다른 Publisher가 계속 새 명령을 보내면 로봇은 멈추지 않을
수 있다. 최종 명령 권한과 stale 정책을 함께 통제해야 한다.

### 6. 로봇을 손으로 옮긴 뒤 SLAM을 재시작한 이유는?

정답: 손 이동은 wheel encoder odometry에 기록되지 않아 SLAM이 가진 sensor pose와 실제 위치가
달라진다. 오염된 pose graph를 이어 쓰지 않고 현재 위치에서 새 기준으로 시작해야 하기 때문이다.

### 7. 각 패키지 테스트는 통과했는데 전체 CI가 실패할 수 있는 이유는?

정답: 같은 ROS domain에서 병렬 실행된 테스트가 동일한 절대 service 이름을 사용하면 다른
패키지의 가짜 서버에 연결될 수 있다. 테스트 전용 namespace나 고유 service 이름으로 graph를
격리해야 한다.

## 완료 체크리스트

- [x] 사용자 충돌·파손·분리 여부 확인
- [x] e-stop·텔레옵·SLAM·bringup 종료 확인
- [x] 잘못된 지도와 odometry 폐기 결정
- [x] 부호 있는 직진·회전 진행량 구현
- [x] 단독 Publisher·센서 freshness·LiDAR clearance 검사 구현
- [x] 무동작 dry-run 구현
- [x] 텔레옵 공존 거부 ROS 통합 테스트
- [x] 전체 116개 로컬 테스트 통과
- [x] TB1 실제 ROS graph dry-run 통과
- [x] Cyclone DDS RMW 불일치 실행 거부 구현
- [x] watchdog 시작 e-stop과 상태 토픽 구현
- [x] 보강 후 115개 로컬 테스트 통과
- [x] 5cm 직진 guard 시스템 측정 통과
- [x] 5cm 직진 사용자 물리 관찰 확인
- [x] 30도 회전 guard 시스템 측정 통과
- [x] 30도 회전 사용자 물리 관찰 확인
- [x] TB1 전용 가드 저속 직진·회전 통과
- [x] 전방 0.30m 미만에서 직진 차단과 무이동 확인
- [x] 병렬 ROS 테스트 service 이름 격리
- [x] 재배치 후 SLAM 재시작과 클린 맵 첫 10cm 시스템 측정
- [x] 클린 맵 첫 10cm 사용자 물리 관찰 확인
- [x] 클린 맵 두 번째 10cm 시스템 측정
- [x] 클린 맵 두 번째 10cm 사용자 물리 관찰 확인
- [x] 클린 맵 세 번째 10cm 시스템 측정
- [x] 클린 맵 세 번째 10cm 사용자 물리 관찰 확인
- [x] 클린 맵 시계 방향 90도 guard 시스템 측정
- [ ] 클린 맵 시계 방향 90도 사용자 물리 관찰 확인
- [x] 지도 크기·known·occupied cell 재측정
- [ ] 깨끗한 지도 저장 및 시각 검수

## 관련 커밋

- `b5cc3e4 fix: declare fleet gateway test dependency`
- `43cf761 feat: add fail-closed supervised motion guard`
- `377cb64 feat: add no-motion guard preflight`
- `22efda6 fix: enforce DDS and e-stop motion contracts`
- `edcbf87 fix: publish e-stop status heartbeat`
- `d9a2671 test: cover low-clearance motion rejection`
- `e4fcdf6 fix: isolate ROS integration service names`
- `dd1f994 feat: add saved map artifact validator`

## 다음에 할 일

1. 시계 방향 90도 회전의 사용자 물리 관찰을 확인한다.
2. 새 정면의 실제 장애물·케이블 여유를 확인하고 짧은 보호 직진으로 지도를 확장한다.
3. 지도와 pose graph를 저장하고 자동·시각 품질을 검수한다.
