# 학습 일지: TB1 새 장소 클린 매핑 시작

날짜: 2026-07-16
단계: Phase 5 - 실제 지도 작성
진행 상태: 새 기준 시작·보호 이동 완료, SLAM queue 보정 뒤 pose graph 2노드 검증 완료

## 오늘의 목표

- 이전 장소의 지도와 odom 기준을 새 장소로 이어 쓰지 않는다.
- 로봇을 옮기기 전에 SLAM·bringup을 종료하고 e-stop을 유지한다.
- 새 장소에서 odom·SLAM·pose 체크포인트를 모두 새 기준으로 시작한다.
- 첫 이동을 5cm로 제한해 시스템 결과와 사용자 물리 관찰을 함께 확인한다.

## 왜 새로 시작했는가

로봇을 들어 새 장소로 옮기면 wheel encoder는 그 변위를 기록하지 못한다. 이전 pose graph를
계속 사용하면 SLAM 내부 sensor pose와 실제 공간이 달라진다. 따라서 이전 후보 지도는
최종본으로 채택하지 않고, 이동 전에 관련 프로세스를 종료한 뒤 새 odom과 빈 SLAM 지도로
시작했다.

## 안전한 장소 이동

이동 전 원격 검사 결과는 다음과 같았다.

```text
e-stop: true
/cmd_vel: linear.x=0.0, angular.z=0.0
tb1-slam-mapping: stopped
tb1-bringup: stopped
slam_toolbox / scan_normalizer / turtlebot3_ros / ld08_driver: NONE
OpenCR·LiDAR serial owner: NONE
safety_watchdog: active
```

사용자는 새 장소에서 다음 조건을 확인했다.

```text
전방 50cm 이상
회전 공간 확보
케이블 고정
낙하 위험 없음
```

## 새 bringup과 SLAM 기준

bringup을 먼저 시작하고 센서가 올라온 뒤 transient `tb1-slam-mapping.service`를 새로
생성했다. 새 SLAM 실행에서 다음 상태를 확인했다.

```text
tb1-bringup: active
tb1-slam-mapping: active
tb1-safety-watchdog: active
odom position: x=0.0, y=0.0
/scan_normalized: fresh, frame_id=base_scan
/map Publisher: slam_toolbox 1개
map resolution: 0.05m/cell
e-stop: true
/cmd_vel: 0
safe input Publisher: 0
```

## 운영 pose 체크포인트 등록

사용자의 새 장소 안전 확인 뒤 `reset_pose_checkpoint:=true`인 dry-run으로 현재 odom 자세를
운영 기준으로 등록했다. 일반 dry-run을 한 번 더 실행해 같은 기준을 읽을 수 있는지 확인했다.

```text
POSE_CHECKPOINT_RESET: PASS
normal dry-run: PASS
pose deviation: translation=0.0000m, yaw=0.03deg
e-stop release count: 0
```

체크포인트 reset은 원인을 확인한 새 기준에서만 사용한다. 평상시 매 동작은 마지막 성공
종점과 현재 시작 자세를 비교하고, 실제 이동 직전 `motion_in_progress`를 기록한다.

## 새 장소 첫 5cm 보호 직진

```text
target: 0.0500m
speed: 0.0200m/s
guard progress: 0.0508m
elapsed: 2.77s
odom before: x=0.000000, y=0.000000
odom after: x=0.055227, y=0.000389
checkpoint motion_in_progress: false
checkpoint x=0.055227, y=0.000389, yaw=0.007192rad
final e-stop: true
final /cmd_vel: 0
final safe input Publisher: 0
```

사용자는 실제 5cm 이동과 방향이 정상이고 충돌과 케이블 이상이 없다고 확인했다. 이동 후
정면 30도 sector 최소 여유는 약 `0.796m`였다. 지도는 `134 x 191`이고 known cell은
341개(free 309, occupied 32)로 첫 5cm 전후 동일했다. 이는 실패를 뜻하지 않는다. 5cm는
지도 해상도 한 칸이고 같은 시점에서 이미 관측한 범위 안일 수 있으므로, 새 공간 관측은
추가 위치 이동 뒤 다시 비교한다.

## 두 번째 10cm 보호 직진

사용자가 전방 여유와 케이블 상태를 다시 확인한 뒤 같은 방향으로 10cm를 보호 직진했다.

```text
target: 0.1000m
speed: 0.0200m/s
guard progress: 0.1004m
elapsed: 5.33s
odom before: x=0.055227, y=0.000389
odom after: x=0.160073, y=0.002175
checkpoint motion_in_progress: false
checkpoint x=0.159947, y=0.002172, yaw=0.020334rad
front clearance after motion: 0.640m
final e-stop: true
final /cmd_vel: 0
final safe input Publisher: 0
```

명령은 정상 종료했고 오도메트리 기준 실제 진행량도 약 10.48cm였다. 종료 뒤에는 e-stop이
다시 활성화됐고 속도 출력과 잔류 입력 발행자가 없었다. 다만 지도 셀 수는 이동 전후 모두
`known 341, free 309, occupied 32`로 정확히 같았다. 안전 이동 성공과 지도 작성 성공은 서로
다른 검증 항목이므로, 추가 이동부터 계속하지 않고 SLAM의 scan 수신·TF·지도 timestamp와
로그를 먼저 진단하기로 했다.

## 지도 미갱신 진단과 설정 보정

진단 결과 `/scan_normalized`는 약 10.09Hz였고 Publisher와 SLAM Subscriber의 QoS는 모두
best-effort로 일치했다. `/map` timestamp도 계속 갱신됐으며 `base_scan -> odom` TF의 평균
순 지연은 약 2.5ms, 최대 약 14.6ms였다. 반면 pose graph에는 초기 노드 1개만 있었고 현재
그래프 데이터 파일도 약 13KB였다. 즉 센서·TF 전체가 끊긴 것이 아니라 두 번째 스캔이
그래프 노드로 채택되지 않는 상태였다.

이전 실행 로그에는 `Message Filter ... queue is full`이 있었고 설정은 10Hz LDS-02에
`scan_queue_size: 1`이었다. Raspberry Pi의 짧은 스케줄링 변동을 흡수하도록 큐를 10개로
늘렸다. 보호 매핑이 5cm 구간부터 시작하는 작은 공간이므로 `minimum_travel_distance`도
10cm에서 지도 해상도와 같은 5cm로 조정했다. 변경 뒤에는 SLAM을 재시작해 기존 1노드
진단 지도를 폐기하고, 무동작 기준 검사 후 다음 짧은 이동에서 두 번째 그래프 노드와 지도
갱신을 함께 검증한다.

## TB1 배포와 새 그래프 기준

로컬 `fleet_navigation` 82개 테스트와 누적 146개 테스트가 모두 통과한 뒤 커밋
`b1325a6`을 TB1에 fast-forward로 배포하고 패키지를 다시 빌드했다. transient systemd
unit은 stop 뒤 정의가 사라지므로 일반 start가 실패했고, 같은 안전 환경 변수를 가진
`systemd-run --user` 명령으로 `tb1-slam-mapping.service`를 재생성했다.

```text
deployed commit: b1325a6
tb1-bringup: active
tb1-slam-mapping: active
tb1-safety-watchdog: active
scan_queue_size: 10
minimum_travel_distance: 0.05m
/scan_normalized: about 9.9Hz
new pose graph baseline: 1 node
checkpoint dry-run: PASS, translation=0.0002m, yaw=3.28deg
final e-stop: true
final /cmd_vel: 0
final safe input Publisher: 0
```

SLAM 재시작은 지도만 새로 만들고 bringup과 odom은 유지했다. 따라서 운영 pose 체크포인트는
현재 odom과 계속 일치했고 reset 없이 dry-run을 통과했다. 새 그래프는 의도적으로 1노드에서
시작했으며 다음 승인된 짧은 이동 뒤 2개 이상으로 늘어나는지가 설정 수정의 실차 합격 기준이다.

## queue 보정 뒤 5cm 재시험과 합격 판정

사용자는 전방 30cm 이상, 케이블 고정, 바퀴 자유, 낙하 위험 없음과 이전 이동의 무이상을
확인했다. 자동 preflight는 서비스 3개가 active이고 Zenoh bridge가 inactive이며 e-stop
`true`, `/safety/cmd_vel_in` Publisher 0, `/cmd_vel` 0임을 확인했다.

첫 dry-run은 마지막 체크포인트와 현재 yaw가 `20.89deg` 달라 이동 전에 차단됐다. 이는 새
장소에서 사용자가 로봇 방향을 바꾼 사실과 일치했다. e-stop·0속도·Publisher 0을 다시 확인한
뒤 `reset_pose_checkpoint:=true`인 무이동 dry-run으로 현재 자세를 명시적으로 등록하고, 일반
dry-run이 같은 기준을 통과한 뒤에만 5cm 1회를 실행했다.

```text
target: 0.0500m
speed: 0.0200m/s
guard progress: 0.0515m
elapsed: 2.76s
odom before: x=0.160200, y=0.002184
odom after:  x=0.212231, y=0.023531
pose graph sphere nodes: 1 -> 2
pose graph total markers: 4 -> 5
final e-stop: true
final /cmd_vel: linear.x=0.0, angular.z=0.0
final safe input Publisher: 0
physical observation: 정상 이동, 충돌 없음, 케이블 이상 없음
```

따라서 `scan_queue_size=10`과 `minimum_travel_distance=0.05` 보정의 실차 합격 조건인
두 번째 pose graph 노드 등록을 확인했다. 이번 결과는 이동 명령 성공뿐 아니라 SLAM이 새
자세를 그래프에 채택했다는 증거다. 다만 2노드는 지도 완성을 뜻하지 않으므로 loop closure와
최종 지도 파일 검증은 계속 남아 있다.

## 오늘 꼭 기억해야 할 것

1. **새 장소로 들어 옮긴 로봇은 이전 odom·SLAM pose graph를 이어 쓰지 않는다.**
2. **로봇을 옮기기 전 e-stop뿐 아니라 센서와 odom 프로세스 종료까지 확인한다.**
3. **체크포인트 reset은 안전장치 우회가 아니라 검토한 새 기준의 명시적 승인이다.**
4. **실차 성공은 guard 숫자와 사용자의 방향·충돌·케이블 관찰이 모두 맞아야 한다.**
5. **짧은 이동 뒤 known cell이 그대로여도 센서·odom·지도 오류라고 즉시 결론 내리지 않는다.**
6. **같은 지도 통계가 반복되면 이동을 더 하기 전에 SLAM 입력과 갱신 여부를 증거로 확인한다.**
7. **10Hz 센서에 queue 1개는 지연 허용량이 0에 가까우므로 임베디드 장비에서 취약하다.**
8. **pose graph 노드 증가는 SLAM이 이동 스캔을 채택했다는 직접 증거지만 지도 완성 증거는 아니다.**

## 면접에서는 이렇게 설명한다

> 매핑 장소를 바꿀 때는 기존 지도 위에서 로봇 좌표만 임의로 바꾸지 않았습니다. e-stop과
> 0속도를 확인한 뒤 SLAM과 하드웨어 bringup을 종료해 serial owner까지 제거하고 로봇을
> 옮겼습니다. 새 장소에서 odom 0, 빈 SLAM 지도, 단일 Map Publisher를 확인하고 무동작
> dry-run으로 pose 체크포인트를 등록했습니다. 첫 동작은 5cm로 제한했고 guard 5.08cm,
> odom 5.52cm, 최종 e-stop과 사용자 물리 관찰을 함께 acceptance evidence로 남겼습니다.
> 이어서 10cm 보호 직진도 성공했지만 지도 셀 통계가 그대로여서, 이동 성공과 매핑 성공을
> 분리해 판단하고 scan·TF·지도 갱신 경로를 먼저 진단했습니다. scan queue와 최소 이동
> 임계값을 보정한 뒤 새 그래프에서 5cm 재시험을 수행했고, pose graph 노드가 1개에서
> 2개로 증가해 SLAM이 이동 스캔을 실제로 채택했음을 확인했습니다.

## 복습 문제와 정답

### 1. 새 장소에서 SLAM만 재시작하고 bringup은 유지하면 어떤 위험이 있는가?

정답: 로봇을 들어 옮기는 동안 odom 좌표가 실제 변위를 기록하지 못하고 이전 기준이 남을 수
있다. 새 장소에서는 odom과 SLAM을 함께 새 기준으로 시작하는 편이 명확하다.

### 2. 왜 체크포인트 reset을 일반 이동과 동시에 허용하지 않는가?

정답: 자세 불일치를 발견한 실행이 스스로 기준을 덮으면 수동 이동이나 odom 재시작을 숨길 수
있다. reset은 e-stop을 해제하지 않는 dry-run에서만 허용해야 한다.

### 3. guard 5.08cm와 odom 위치 변화 5.52cm가 다른 이유는 무엇인가?

정답: guard가 목표를 넘긴 첫 odom 샘플에서 정지하고 메시지·모터·encoder 갱신 주기가
비동기이므로 약간의 차이가 생길 수 있다. 제한 범위와 최종 정지를 함께 판단한다.

### 4. 5cm 이동 뒤 지도 셀이 늘지 않은 것은 SLAM 실패인가?

정답: 아니다. 같은 주변을 이미 360도 LiDAR로 관측했고 이동량이 지도 한 셀 정도이면 새
관측 영역이 없을 수 있다. 추가 이동·TF·스캔 정합과 장시간 지도 변화를 함께 확인해야 한다.

### 5. 10cm를 더 이동한 뒤에도 지도 통계가 정확히 같다면 다음 행동은 무엇인가?

정답: 이동을 반복해 증상을 키우지 않는다. SLAM 노드의 scan 구독, scan timestamp와 주기,
`map -> odom` TF 변화, 지도 header timestamp, SLAM 로그를 확인해 처리 파이프라인이 실제로
갱신 중인지 검증한다.

### 6. pose graph 노드가 1개에서 2개로 늘면 무엇을 증명하고 무엇은 아직 증명하지 못하는가?

정답: SLAM이 이동 뒤 스캔을 새 자세 노드로 채택했다는 것은 증명한다. 하지만 충분한 공간
범위, 벽 형상 품질, loop closure, 저장·재로드 의미 보존과 Nav2 사용 가능성까지는 증명하지
못하므로 별도 검증해야 한다.

## 완료 체크리스트

- [x] 이전 매핑·bringup 안전 종료
- [x] 사용자 새 장소 물리 안전 확인
- [x] 새 odom·SLAM·Map Publisher 확인
- [x] 운영 pose 체크포인트 무동작 등록·재검증
- [x] 첫 5cm guard 시스템 검증
- [x] 첫 5cm 사용자 물리 관찰
- [x] 종료 e-stop·0속도·입력 Publisher 0 확인
- [x] 다음 10cm 사용자 준비 확인과 보호 이동
- [x] 두 번째 이동 종료 e-stop·0속도·입력 Publisher 0 확인
- [x] scan·TF·pose graph·로그 기반 지도 미갱신 진단
- [x] scan queue와 최소 이동 등록 임계값 설정 보정
- [x] 설정 테스트·TB1 배포·SLAM 새 그래프 재시작
- [x] 배포 후 무동작 dry-run과 최종 안전 상태 확인
- [x] 보정 뒤 5cm 보호 재시험과 사용자 물리 관찰
- [x] 새 pose graph 노드 1개에서 2개로 증가 확인
- [ ] 지도 known cell 증가와 loop closure 검증
- [ ] 최종 지도 저장·round-trip·시각 검수

## 다음에 할 일

1. 현장 준비를 새로 확인한 구간만 보호 이동해 pose graph와 관측 범위를 늘린다.
2. 출발 지점 근처를 다른 방향에서 다시 관측해 loop closure를 검증한다.
3. 지도 YAML·PGM·pose graph를 저장하고 round-trip과 시각 품질을 검사한다.

## 관련 커밋

- `b490da8 feat: guard motion across command boundaries`
- `c35bb07 test: avoid partial ROS node cleanup warning`
- `b1325a6 fix: retain SLAM scans during short mapping steps`
