# 학습 일지: Phase 7 ROS 2 로그 MLOps와 지도 뷰포트

날짜: 2026-07-19

진행 상태: 소프트웨어 구현·TB1 데이터 수용 확인, 정상 기준 데이터 장기 수집 전

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

수량 gate 통과는 승격의 필요조건이지 충분조건이 아니다. 정상 Nav2·AMCL 주행 데이터를 15~30분
더 수집해 logger·작업 상태의 대표성과 timestamp 경고가 없는 후보를 다시 검토해야 한다. 따라서
현재 `MODEL_NOT_READY`는 수집 장애가 아니라 편향된 기준 모델의 승격을 막은 정상 상태이며
Phase 7 전체 완료로 기록하지 않는다.

## 배운 점

1. OccupancyGrid cell 수와 화면 canvas pixel 수는 같은 개념이 아니다.
2. 확대된 화면에서 정확한 click pose를 얻으려면 draw와 inverse transform이 같은 viewport를
   공유해야 한다.
3. 로그 이상탐지는 모델 하나가 아니라 dataset·feature·quality gate·promotion·monitoring의
   수명주기로 설명해야 MLOps가 된다.
4. 설명 가능한 작은 baseline이 데이터가 부족한 단일 로봇에서는 복잡한 모델보다 검증하기 쉽다.
5. ML 관측과 deterministic motion safety의 권한을 분리해야 false positive가 위험 동작을 만들지
   않는다.
