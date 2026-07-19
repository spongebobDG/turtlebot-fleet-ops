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
- WSL Humble 전체 결과: `206 tests, 0 errors, 0 failures, 0 skipped`
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
