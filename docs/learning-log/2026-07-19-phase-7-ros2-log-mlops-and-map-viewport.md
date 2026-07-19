# 학습 일지: Phase 7 ROS 2 로그 MLOps와 지도 뷰포트

날짜: 2026-07-19

진행 상태: TB1 정상 기준·Production 승격·정상/오류 replay 실차 수용 완료

## 문제와 목표

실제 지도는 58×96 cell인데 웹 canvas도 같은 픽셀로 만든 뒤 크게 늘려 표시했다. OccupancyGrid
자체 해상도가 낮은 것은 정상이나 pose 화살표와 클릭 좌표까지 저해상도 캔버스에 묶여 깨져
보였고, 화면의 여백·확대 상태를 명시적으로 다룰 수 없었다. 동시에 프로젝트의 로그·장애 분석을
MLOps 주제로 발전시키기 위해 ROS 2 로그 데이터에서 모델 승격까지 이어지는 수명주기가 필요했다.

## 구현한 내용

지도는 source occupancy bitmap과 고해상도 화면 canvas를 분리했다. 화면 device pixel ratio로
backing store를 만들고, fit·zoom·pan 행렬을 그리기와 역변환에 함께 사용한다. 클릭은 row-major
OccupancyGrid cell로 환산해 free value 0만 허용하고 cell 중앙 world pose로 고정한다. 서버도
origin yaw와 resolution을 사용해 같은 pose를 다시 검증한다.

로그 경로는 TB1 `/rosout` → Zenoh → control PC collector로 설계했다. collector는 일별 JSONL을
Git 밖에 저장하고 최근 5분을 Production median/MAD 모델로 분석한다. offline CLI는 60초 dataset,
SHA-256 lineage, candidate 품질 gate와 명시적 promote를 제공한다. Gateway는 최신 상태를 REST로
노출하고 단일 화면에 model ID, score/threshold와 상위 원인 특징을 표시한다.

## 현재 검증 증거

- Node 지도 변환 테스트: origin 회전, round-trip, 지도 밖 fail-closed, zoom bound와 pan
- Python 테스트: journal/ROS console 파싱, dataset hash, 품질 gate, anomaly 설명, 승격 거부·성공
- FastAPI 테스트: 모델 없음의 `MODEL_NOT_READY`, 게시 상태 반환, 정적 viewport asset allowlist
- JavaScript syntax와 Python compile 확인
- WSL Humble 전체 결과: `208 tests, 0 errors, 0 failures, 0 skipped`
- ShellCheck, systemd unit 검증, domain 142 운영·Nav2·Zenoh 액션 무로봇 스모크 모두 통과
- 1280×720 실제 Dashboard: 문서 높이와 viewport 높이가 모두 720px여서 세로 스크롤 없음
- 58×96 실지도 자유 셀 29,48 클릭: 기대 좌표와 입력 좌표가 모두 `(-0.785, 1.365)`이고
  156% 확대 뒤에도 선택 pose가 유지됨
- TB1 `/rosout` → relay → 두 Zenoh bridge → collector → REST 수용 확인: 누적 raw 45건,
  서비스 재시작 후에도 새 로그와 REST 추론 입력 복구 확인
- relay가 DDS discovery에서 이탈한 상태를 발견했고 `tb1-robot-agent.service` 재시작 뒤 publisher
  route와 수집이 복구되는 것을 확인함
- ROS stamp 0인 수용 프로브가 1970년 window를 만드는 문제를 발견했다. collector는 이제 이런
  stamp를 수신 시각으로 보정하고 dataset builder는 기존 0·비유한 시각 레코드를 제외한다.
- 최종 후보 `ros2-log-mad-2026-07-19T054758.458802+0000-39a30b17`: 유효 7개 60초 창·35건으로
  수량 gate는 통과했지만 잘못된 시각 10건 제외 경고와 robot agent·수용 프로브 편중을 확인했다.
  Nav2·AMCL 정상 주행 기준을 대표하지 못하므로 Production에는 승격하지 않음

## 재부팅 직후 목적지 지연 사건과 수정

TB1 재부팅 후 웹 초기 위치와 목표를 새로 보냈지만 처음에는 움직이지 않다가 뒤늦게 주행했다.
Gateway 상태에서 목표·lease·Nav2·AMCL·safety는 모두 준비됐으므로 명령 전달 실패는 아니었다.
첫 목표는 162.7초 동안 7회 recovery 뒤 목표 3.5cm 앞에서 운영자 취소로 종료됐다. 이어 보낸
목표는 27.8초 동안 22회 recovery 후 `FAILED`가 됐다. 당시 LiDAR 최소 거리는 약 0.163m였고
TB1 journal에는 다음 신호가 함께 있었다.

- `Behavior Tree tick rate 100.00 was exceeded`
- `Control loop missed its desired rate of 10.0000Hz`
- `Failed to make progress`
- `failed to generate a valid path`
- `Collision Ahead - Exiting Spin/DriveOnHeading`

원인은 한 가지가 아니었다. 가까운 장애물·부정확한 초기 pose 때문에 planner와 recovery가 충돌
방지에 걸렸고, Humble 기준의 10ms Behavior Tree loop가 TB1에서 경고 로그 폭주와 CPU 부하를
키웠다. 저장소 overlay에 `bt_loop_duration: 100`을 추가해 BT를 10Hz로 낮췄다. 저속 상한과
watchdog 경로는 바꾸지 않았다.

웹에서는 실패·취소된 과거 target을 계속 노란 활성 목표처럼 그렸고, 새 선택이 없어도 기본
입력 `(0,0,0)`을 보낼 수 있었다. 이제 활성 command ID가 있을 때만 활성 목표를 표시한다. 자유
셀의 새 후보가 있어야 전송 버튼이 켜지고 모드 변경·지도 재로딩·성공 접수 뒤 후보를 폐기한다.
58×96, 5cm/cell이라는 원본 지도 품질도 화면에 표시해 픽셀화와 좌표 오차를 구분한다.

MLOps 추론은 검토된 정상 baseline이 없어 계속 `MODEL_NOT_READY`로 유지했다. 대신 최근 로그의
제어 지연·경로 실패·충돌 방지·진척 실패·메시지 유실을 `operational_signals`로 집계해 모델
승격 전에도 사건 원인을 Dashboard에서 설명한다. 이는 motion authority가 아니며 안전 판단은
계속 watchdog과 arbiter가 담당한다.

저장된 incident 구간 411건을 새 분석기로 replay한 결과는 제어 주기 지연 20회, 경로 생성 실패
7회, 센서 메시지 지연·유실 3회, 충돌 방지 개입 2회였고 `navigation_failure_rate`는 약
0.0170이었다. 이 값은 정상 baseline과 비교한 anomaly score가 아니라 사건 파서 수용 증거다.

진단 도중 collector를 재시작하자 메모리의 최근 5분 창이 비어 직전 사건 신호가 사라지는 문제도
발견했다. 시작 시 당일·전일 raw JSONL에서 lookback 창을 복원하고, 전원 차단으로 마지막 줄이
부분 기록됐을 때는 그 줄만 건너뛰도록 변경했다. 따라서 “갑자기 껐다 켠 경우 무엇이 로그에
남는가”를 서비스 메모리가 아니라 append-only raw artifact로 설명할 수 있다.

첫 TB1 재배포는 원격 Git 갱신용 PowerShell here-string의 CRLF 때문에 Bash가 `pipefail\r`을
잘못된 옵션으로 읽어 코드 동기화 전에 중단됐다. 기존 streamed script는 CR 제거 경로가 있었지만
Git 갱신 블록은 직접 ssh 인수로 전달해 누락된 것이 원인이었다. 원격 명령 블록도 CR을 제거한 뒤
전송하도록 수정했다.

정식 배포 뒤 TB1은 목표 없는 IDLE에서 Nav2를 다시 시작했다. 런타임
`/bt_navigator.bt_loop_duration`은 100ms였고 새 서비스 구간의 기존 100Hz tick 초과 경고는
0회였다. AMCL 초기 위치 전 최근 창은 416건 중 `초기 위치 대기` 335회를 분리했으며, 이는 주행
실패와 다른 lifecycle 상태다. 이 신호로 정상 baseline 수집에서 시작 구간을 제외할 근거를
남겼다.

수량 gate 통과는 승격의 필요조건이지 충분조건이 아니다. 이 중간 판정에서는 정상 Nav2·AMCL
주행 데이터를 15~30분 더 수집해 logger·작업 상태의 대표성과 timestamp 경고가 없는 후보를
다시 검토해야 했다. 따라서 당시 `MODEL_NOT_READY`는 수집 장애가 아니라 편향된 기준 모델의
승격을 막은 정상 상태였고, 그 시점에는 Phase 7 전체 완료로 기록하지 않았다.

## 후속 방향 목표 비수렴과 MLOps 관측

후속 제자리 방향 목표에서는 첫 목표가 성공한 뒤 복귀 목표가 76.4초 동안 map 자세에 수렴하지
않아 운영자 취소로 안전 정지했다. 세 velocity 토픽은 모두 0.05m/s·0.3rad/s 상한을 지켰고
`/cmd_vel` Publisher도 watchdog 하나였으므로, 이 사건은 속도 우회가 아니라 odom 진척과 map
진척의 불일치로 분류했다. 사건 직후 MLOps REST는 최근 82건에서 제어 주기 지연 4회를
`control_deadline_miss`로 표시했다. Production 모델이 없어도 결정론적 운영 신호로 해당 구간을
찾을 수 있었지만 자동 안전 권한은 계속 navigation agent와 watchdog에 남겼다.

Nav2 progress checker가 odom 이동을 진척으로 본다는 한계를 보완하기 위해 agent에 map-frame
거리·yaw 진척 20초, feedback 3초, 전체 목표 180초 상한을 추가했다. 고정 feedback fake Nav2가
자동 cancel·`FAILED`·`IDLE`로 끝나는 통합 테스트를 포함했고, 전체 Humble 결과는 기존 208개에서
`218 tests, 0 errors, 0 failures, 0 skipped`로 늘었다.

## 보강 배포 뒤 정상 웹 주행 관측

새 navigation agent 배포 뒤 AMCL 초기 위치를 다시 지정하고 웹에서 약 0.70m 떨어진 목표를
접수했다. command `23bdde9fa4c5402b86cfcac55fbf42d6`은 21.6006초 만에 recovery 0회,
Nav2 error 0으로 `SUCCEEDED`가 됐다. 종료 시 active command가 비고 arbiter가 `IDLE`로 돌아갔으며,
`/cmd_vel` Publisher는 계속 `safety_watchdog` 하나였다. 이는 수집기가 실패 로그만 보는 것이 아니라
같은 Nav2·AMCL 경로의 정상 성공 구간도 받고 있음을 확인하는 실제 레코드다.

직후 MLOps REST에는 최근 478건이 들어왔지만 그중 443건은 재시작 뒤 AMCL 초기 위치를 기다리던
`initial_pose_wait` 신호였다. `navigation_failure_rate`, `error_rate`, `restart_rate`,
`disconnect_rate`는 모두 0이었지만 이 창은 정상 주행보다 lifecycle 대기 로그에 크게 편향돼 있다.
따라서 수량만 보고 candidate를 승격하지 않고 `MODEL_NOT_READY`를 유지했다. Production 승격에는
초기 위치 대기 구간을 분리한 뒤 여러 정상 목표가 포함된 15~30분 대표 dataset이 여전히 필요하다.

## 잘못된 초기 yaw와 벽 접촉 사건

추가 경로 시험 전에 한 직선 목표 `cc81f495c0d04b6284589bd5612501a3`은 9.4초, recovery 0회로
성공했다. 이어 한 바퀴 경로의 첫 목표 `23856f7203644bee8393a06daf8e9fe7`을 보냈을 때 map pose는
실제와 다르게 지도 밖으로 이동했고 Nav2는 planning·spin·wait·backup recovery를 반복했다.
48.4초, recovery 19회 뒤 실패했으며 작업자가 실제 벽 접촉을 보고했다. 19:49:51 KST에 즉시
e-stop을 적용해 active goal과 lease를 폐기했고 선속도 0을 확인했다. 이후의 진단·배포·초기
위치 보정은 모두 e-stop과 `motion_armed=false`에서 수행했다.

정지 상태 scan 100개를 조사한 결과 99개는 330° 이상이었고 각도 span 중앙값 358.35°,
발행 간격 중앙값 0.100초, 최대 gap 0.390초였다. 따라서 한 번의 partial scan은 있었지만 지속적인
LiDAR 유실이 주원인은 아니었다. 당시 최소 거리는 약 0.163m였고, 기존 `robot_radius=0.10m`와
실험적 0.15m clearance는 실제 corner 여유에 부족했다.

가장 큰 원인은 초기 pose 방향이었다. 재적용된 후보 `(0.059,-0.365,-3.059rad)`에 실시간
LiDAR endpoint를 투영하자 지도 밖으로 뻗었고 벽 match는 약 3~8%, 지도 내부는 51~53%였다.
OccupancyGrid 전체 자유 셀·yaw를 탐색한 후보는 `(약 0.12,-0.51,-0.03rad)`였고 match 92~93%,
지도 내부 99~100%였다. 약 180° 뒤집힌 yaw 때문에 실제 이동과 웹 map-frame 이동이 반대로
보였던 것이다.

## 충돌 회귀 뒤 안전·정합 보강

- Gateway가 `/scan`을 sensor QoS로 받아 base-local endpoint를 별도 REST로 제공한다.
- 초기 위치 후보를 움직이는 동안 붉은 LiDAR 점도 함께 움직여 벽 정합을 적용 전에 볼 수 있다.
- `LiDAR 자동 정렬`은 occupied-cell 거리장의 전역 coarse search와 두 단계 refinement로 pose를
  제안한다. 실차 응답시간은 약 5.2초였다.
- 최소 40 endpoint, match 35%, 지도 내부 70%, score 0.20을 만족해야 적용할 수 있다. 잘못된
  yaw의 직접 `PUT initial-pose`는 `422`와 match 8%·inside 51% 설명으로 거부됐다.
- navigation agent는 목표 전·실행 중에 신선한 scan, 최소 거리 0.19m와 현재 AMCL pose의 known
  free cell을 확인한다. 0.19m는 반경 0.14m + 외곽 여유 0.05m이며, 위반 시 목표와
  authorization을 취소한다.
- Nav2 `robot_radius`를 0.10m에서 0.14m로 바꿨다. 저속 상한 0.05m/s·0.3rad/s와 watchdog의
  유일한 실제 `/cmd_vel` 소유 구조는 바꾸지 않았다.
- e-stop 상태에서 localization이 이미 확인됐는데 `LOCALIZING`으로 표시되던 조건도 분리했다.
  이후에는 `IDLE / Localization ready; waiting for motion safety rearm`으로 안전 대기 이유를
  정확히 보여준다.

Gateway 75개와 navigation agent 102개, 합계 177개 source-scoped Humble 테스트가 모두 통과했다.
웹 실제 화면에서도 잘못된 `-3.00rad` 후보를 자동 정렬해 `(0.135,-0.510,-0.026rad)`, match 93%,
inside 100%로 표시한 뒤 초기 위치 적용까지 확인했다. 적용 후 AMCL pose는 약
`(0.07,-0.47,-0.02rad)`였고 e-stop·무재무장·선속도 0은 유지됐다.

최종 커밋 `07e77e5`를 TB1에 fast-forward하고 navigation agent 102개 테스트를 로봇에서 다시
통과시켰다. 재시작으로 이전 localization을 폐기한 뒤 자동 정렬한 pose는
`(0.115,-0.510,-0.044rad)`, match 90.625%, 지도 내부 98.75%였고 새 `/amcl_pose`를 받았다.
최종 NavigationStatus는 `IDLE`, `nav2_ready=true`, `localization_ready=true`,
`safety_ready=false`, 메시지는 `Localization ready; waiting for motion safety rearm`이었다.
e-stop true, motion armed false, active command 없음, 선속도 0을 유지했다. ROS graph에서
`/cmd_vel` Publisher는 `safety_watchdog` 1개, `/safety/cmd_vel_in` Publisher는 arbiter 1개였다.

raw 저장소에는 이 시점 누적 10,334건이 있으나 사고·배포·초기 위치 대기 로그가 섞여 있다.
dataset builder에 `since_timestamp`와 `until_timestamp`, CLI·스크립트의 `--since-epoch`와
`--until-epoch`을 추가하고 범위 밖 제외 건수를 lineage에 기록했다. 이 기능으로 과거 10,334건을
지우지 않으면서 검증된 정상 주행 구간만 새 baseline으로 만들 수 있다. 현재는 안전한 대표 주행
구간이 아직 없었으므로 이 검증 시점에는 Production 모델을 승격하지 않았고
`MODEL_NOT_READY`가 올바른 상태였다.

실제 collector root에 최근 10분 범위 `1784460943..1784461543`을 지정해 end-to-end candidate도
생성했다. `ros2-log-mad-2026-07-19T114545.088973+0000-253de624`는 범위 안 123건·60초 창 2개,
범위 밖 제외 10,324건, 잘못된 timestamp 제외 10건을 기록했다. 최소 5개 창 gate를 통과하지
못해 `gate_passed=false`였고 Production registry는 계속 존재하지 않았다. 이는 시간 필터가 실제
raw에서 작동하고 부족·비대표 구간을 자동 승격하지 않는다는 수용 증거다.

## 정상 기준 수집과 Production 수용

물리 주변 확인 뒤 e-stop을 해제하고 자동 재출발이 없는지 3초 감시했다. 첫 정상 목표는
`SUCCEEDED`, 이어 실제 이동이 시작된 목표를 명시적으로 취소해 `DELETE 202`, `CANCELED`,
활성 command 없음과 정지를 확인했다. 다음 목표의 감시용 PowerShell 한 줄에 공백이 빠져
snapshot 필터가 실패했고 같은 e-stop 요청이 반복된 운영 오류도 발생했다. 로봇 로컬 watchdog은
유지됐고 즉시 e-stop을 재적용해 목표는 `CANCELED`, 선속도 약 -0.0005m/s, 미재무장으로
끝났다. 이 구간은 baseline에서 제외하고 재사용 가능한 `invoke_tb1_monitored_goal.ps1`과
`collect_tb1_normal_baseline.ps1`을 작성해 parser 검증과 e-stop 사전 거부를 통과시켰다.

새 clean 범위 `1784467870..1784468785`는 915초(15분 15초)이며 수동 감시 목표 3개와 자동
간격 목표 8개, 합계 11개를 모두 정상 종료했다. 자동 구간의 8개는 recovery 0이었고 최소
LiDAR 0.204m, idle 선속도 최대 0.000523m/s, idle 각속도 최대 0.002434rad/s였다. goal 감시에서
관측한 odom 선속도 순간 최대는 0.055787m/s였으며 이는 앞서 실제 command 경로에서 검증한
0.05m/s clamp와 구분해 기록한다. `UNTIL_EPOCH`을 먼저 고정한 뒤 e-stop을 활성화해 종료
정지 로그가 기준 구간에 들어가지 않게 했다.

dataset은 60초 창 13개, INFO 77건이며 ERROR·WARNING은 0건이었다. logger는
controller_server 42, bt_navigator 20, motion_arbiter 14, AMCL 1건이다. dataset hash는
`49fb354ef4bd32779fdb0694a5dccd7ceaf381ea947f9a87c0d450254b9654ae`, 범위 밖 제외
11,039건, 잘못된 timestamp 제외 10건이다. 품질 gate를 통과한 model
`ros2-log-mad-2026-07-19T134802.259185+0000-6576983b`를 Production으로 승격했다. live REST는
`model_stage=production`, `NORMAL`, score 9.0, threshold 55.75를 반환했다.

live status를 바꾸지 않는 `replay` CLI도 추가했다. clean 5분 구간 3개는 score 25·14·20으로
모두 NORMAL이어서 이 표본의 false positive는 0/3이다. transform timeout 구간은 score 80,
`timeout_rate=0.8`, `initial_pose_wait` 34회로 ANOMALY였다. 과거 충돌·제어 지연 구간도 score
80 ANOMALY였고 control deadline miss 19회, collision guard 2회, message drop 2회, planning
failure 1회를 원인 신호로 분리했다.

현재 raw 2개 파일은 11,126행·2.741MiB다. 이 과밀 시험일을 단순 30일로 투영하면 약
82.2MiB다. raw JSONL은 30일 보존하고 dataset·candidate model·Production registry는 lineage를
위해 자동 삭제하지 않는다. `prune_ros2_log_raw.sh`는 기본 dry-run이며 현재 삭제 후보 0개를
확인했다. 이 증거로 Phase 7을 완료로 판정한다.

## 방향 표시와 현재 위치 재정합

완료 직전 사용자가 지도 방향 선의 어느 쪽이 로봇 앞인지 모호하고 실제 위치와 웹 위치가 다시
다르다고 보고했다. 기존 canvas는 pose 중심에 원을 그리고 앞방향으로 선만 뻗었지만 끝에
화살촉이 없어 원을 앞쪽 표식으로 오해할 수 있었다. 선 끝에 채운 삼각형을 추가하고 도움말을
`원=로봇 중심`, `드래그 끝 삼각형=로봇 앞`으로 바꿨다. 드래그 yaw는 canvas Y 반전과
OccupancyGrid origin yaw를 거쳐 world yaw로 계산하며, 원점 yaw 0과 90도 지도에서 삼각형 끝
방향과 전송 yaw가 일치하는 회귀 테스트를 추가했다.

당시 웹 현재 pose `(-0.248,-0.466,-0.645rad)`를 실시간 scan으로 재검증하자 match 13.125%,
inside 51.25%여서 화면 변환이 아니라 AMCL pose 자체가 틀린 상태임을 확인했다. e-stop과
`motion_armed=false`를 유지한 채 전역 정렬한 후보 `(-0.830,-0.150,-0.916rad)`는 match
90.625%, inside 100%였다. 이를 초기 위치로 적용한 뒤 새 AMCL pose
`(-0.817,-0.122,-0.905rad)`를 받았고 재검증 match 88.75%, inside 100%였다. 웹에서도 붉은
LiDAR endpoint가 지도 벽과 다시 겹쳤으며 active command 없음과 e-stop을 유지했다.

## 후속 물리 방향 시험: 센서 전방축 180° 불일치

초기 위치를 다시 적용한 뒤 5cm 앞 목표는 Nav2의 10cm 위치 허용오차 안이라 실제 이동 없이
성공했다. 15cm 앞 목표에서는 로컬 감시가 odom 각속도 0.323650rad/s를 검출해 즉시 e-stop으로
취소했고, 사용자가 실제 로봇의 전방과 웹 삼각형 전방이 서로 반대라고 확인했다. 목표는 남지
않았고 e-stop 활성, motion unarmed와 0속도를 유지한 채 추가 이동을 중단했다.

정지 상태 진단에서 `base_link→base_scan` TF yaw는 0°였고 `/scan`과 `/scan_normalized`의
frame도 `base_scan`이었다. 그러나 normalizer는 원본 angle에 외부각을 더하지 않았고 Gateway의
`scan_sensor_yaw_rad`도 0이었다. 즉 UI 삼각형은 올바르게 `base_link +X`를 표시했지만 두 scan
소비자는 LDS-02 원본 angle 0을 실제 차체 전방으로 잘못 가정했다. 이전의 180° 전역 정렬 결과는
사용자 yaw 입력만의 문제가 아니라 matcher가 이 센서 축 오류를 pose 회전으로 보상한 결과로
재분류했다.

TB1 `/scan_normalized`에 π rad `angle_offset_rad`를 추가하고 Gateway raw scan overlay에도 같은
π rad를 적용했다. 원본 `/scan`은 진단을 위해 변경하지 않았다. 보정 0의 호환 동작, π에서
angle 0이 180번 bin으로 이동하는 동작, 비유한 offset 거부를 추가했으며 navigation agent
106개와 Gateway 79개, 총 185개 회귀 테스트가 통과했다. 배포 뒤에도 e-stop에서 기존 pose를
폐기하고 scan-map 정합·웹 삼각형·실제 차체 앞을 다시 확인한 다음에만 짧은 전진을 허용한다.

첫 GitHub Actions 실행은 robotless navigation goal이 20초 지도 진척 감시에 걸려 실패했다.
제품의 π 보정은 적용됐지만 fixture가 여전히 raw angle 0을 차체 전방으로 생성해, 가상 센서와
차체 운동의 계약이 실제 TB1과 달랐기 때문이다. robotless fixture와 Dashboard mock도 raw
angle 0이 물리 후방을 뜻하도록 π 센서 외부각을 반영하고, 비대칭 pose에서 raw -π가 전방 벽,
raw 0이 후방 벽 거리를 내는 단위·운영 설정 테스트를 추가했다. 이는 안전 감시를 느슨하게 하지
않고 테스트 장비가 제품의 물리 센서 계약을 그대로 재현하도록 고친 것이다.

## 배운 점

1. OccupancyGrid cell 수와 화면 canvas pixel 수는 같은 개념이 아니다.
2. 확대된 화면에서 정확한 click pose를 얻으려면 draw와 inverse transform이 같은 viewport를
   공유해야 한다.
3. 로그 이상탐지는 모델 하나가 아니라 dataset·feature·quality gate·promotion·monitoring의
   수명주기로 설명해야 MLOps가 된다.
4. 설명 가능한 작은 baseline이 데이터가 부족한 단일 로봇에서는 복잡한 모델보다 검증하기 쉽다.
5. ML 관측과 deterministic motion safety의 권한을 분리해야 false positive가 위험 동작을 만들지
   않는다.
6. free cell 검증만으로 초기 pose의 방향 오류를 잡을 수 없으며, 실제 scan endpoint와 지도 벽의
   정합을 적용 전에 확인해야 한다.
7. 사고 구간을 삭제하는 대신 시간 범위와 제외 건수를 dataset lineage에 남겨야 MLOps 재현성과
   운영 감사를 함께 지킬 수 있다.
8. offline replay는 live status를 오염시키지 않고 같은 Production 모델의 false positive와 알려진
   오류 탐지를 반복 검증하는 안전한 수용 방법이다.
9. 지도 화살표를 그리는 수학이 맞아도 앞쪽 표식이 모호하면 작업자가 yaw를 반대로 입력할 수
   있으므로, 좌표 회귀 테스트와 명확한 방향 기호가 모두 필요하다.
10. scan-map 정합 점수는 센서 외부각의 물리적 의미를 보장하지 않는다. frame 계약과 실제 차체
    전방을 별도로 시험해야 matcher가 180° pose로 센서 축 오류를 숨기는 일을 막을 수 있다.
