# Phase 7: ROS 2 로그 이상탐지 MLOps

## 목표

TB1의 Nav2·AMCL·agent가 발행하는 `/rosout`을 수집해 반복 가능한 특징 데이터셋과 이상탐지
모델을 만들고, 검토·승격된 Production 모델의 추론 결과를 관제 화면에 표시한다. 모델은 운영
이상을 빨리 찾는 관측 계층이며 정지·주행 허가를 결정하지 않는다. 물리 안전의 최종 권한은
계속 TB1의 watchdog과 명령 arbiter에 있다.

## 데이터 흐름

```text
TB1 Nav2 / AMCL / agents
        │ /rosout → robot_agent rosout_relay → /fleet/rosout
        ▼
TB1 Zenoh bridge ── TCP ──> control Zenoh bridge
                                  │ /rosout
                                  ▼
                         ros2_log_mlops_node
                           │             │
                  raw/live-YYYYMMDD      └─ 최근 5분 특징
                           │                       │
                           ▼                       ▼
               windowed dataset            Production model
                           │                       │
                           ▼                       ▼
                  candidate model ──gate──> status/latest.json
                                                   │
                                                   ▼
                                    Gateway REST → Web Dashboard
```

원시 로그, 데이터셋, 후보·Production 모델과 추론 상태는
`~/.local/share/turtlebot-fleet-ops/mlops/ros2-logs/`에 저장한다. 실제 로그나 학습 산출물은
장비·시각·현장 정보를 포함할 수 있어 Git에 넣지 않는다. 저장소에는 파서, 특징 스키마,
학습·승격 코드, 테스트와 문서만 둔다.

collector 재시작 때는 당일·전일 raw JSONL에서 최근 lookback 창을 복원한 뒤 첫 추론을 게시한다.
전원 차단으로 마지막 JSONL 한 줄이 불완전해도 그 줄만 제외하고 이전 정상 레코드는 유지한다.

## 파이프라인 단계

| 단계 | 입력 | 출력 | 재현성 기준 |
| --- | --- | --- | --- |
| Collect | ROS 2 `/rosout`, 선택적 user journal | 정규화 JSONL | timestamp·severity·logger·message·source 보존 |
| Build | 일별 JSONL | 60초 time-window dataset | 특징 이름·window·record count·SHA-256 기록 |
| Train | dataset artifact | median/MAD candidate | model type·dataset hash·학습 시각·품질 지표 기록 |
| Validate | candidate metrics | gate pass/fail·warning | 최소 5개 window, 20개 record와 timestamp·logger·작업 대표성 검토 |
| Promote | gate-pass candidate | Production registry | 명시적 승격 시각과 stage 기록 |
| Infer | 최근 5분 특징 | score·threshold·원인 상위 3개 | 원자적 `status/latest.json` 게시 |
| Monitor | status REST | NORMAL/ANOMALY/ERROR | 모델·점수·임계값·기여 특징을 UI에 표시 |

## 특징과 모델 선택

첫 모델은 작은 TB1 환경에서 설명 가능하고 학습 의존성이 적은 robust median/MAD 방식이다.
60초 창마다 다음 특징을 만든다.

- 전체 로그 줄 수
- ERROR와 WARNING 비율
- timeout, disconnect/offline 패턴 비율
- navigation goal 실패·중단 패턴 비율
- process restart/lifecycle 오류 비율
- dropped/lost/queue full 패턴 비율

각 특징은 정상 기준의 중앙값과 MAD 기반 scale에서 얼마나 벗어났는지 계산한다. 가장 큰 robust
deviation을 anomaly score로 사용하고 상위 세 특징을 설명으로 남긴다. 이 선택은 딥러닝보다
표현력이 작지만 데이터가 적은 단일 로봇에서 왜 이상으로 판정했는지 설명하고 모델 파일을
감사하기 쉽다. 로그가 충분히 쌓인 뒤 Isolation Forest 같은 후보와 같은 offline dataset으로
비교할 수 있다.

## 공개 인터페이스

`GET /api/mlops/ros2-logs`는 다음 상태를 반환한다.

```json
{
  "state": "NORMAL",
  "model_id": "ros2-log-mad-...",
  "model_stage": "production",
  "score": 0.8,
  "threshold": 4.0,
  "log_count": 32,
  "top_features": [
    {"feature": "warning_rate", "value": 0.03, "baseline": 0.0, "deviation": 3.0}
  ],
  "message": "최근 ROS 2 운영 로그 패턴이 기준 범위입니다."
}
```

Production 모델이 없으면 HTTP 오류로 숨기지 않고 `MODEL_NOT_READY`를 반환한다. 상태 파일이
손상되면 `ERROR`를 반환한다. 지도·로봇 snapshot WebSocket에는 이 결과를 반복 포함하지 않고
운영 REST polling으로 분리한다.

모델 승격 전에도 현재 장애를 설명할 수 있도록 `control loop missed`, `failed to create plan`,
`Collision Ahead`, `failed to make progress`, sensor message drop을 결정론적 운영 신호로 함께
집계한다. Nav2 기동 후 `map→base_link`가 없는 정상 대기는 `초기 위치 대기`로 별도 구분한다.
이 집계는 학습 모델을 대신하거나 주행을 제어하지 않는다. 모델 lifecycle이 준비되는
동안 현장 로그를 사람이 해석할 수 있게 하고, 같은 문구는 `navigation_failure_rate` 특징에도
반영해 이후 Production 추론과 연결한다.

## 지도 뷰포트 정확도 보강

같은 Phase에서 58×96 OccupancyGrid를 58×96 canvas로 만든 뒤 CSS 확대하던 방식을 제거했다.
캔버스 backing store는 화면 CSS 크기와 device pixel ratio로 만들고, 지도 bitmap과 vector
overlay를 분리한다. fit·zoom·pan 하나의 affine viewport를 그리기와 역변환에 함께 사용한다.

- origin x/y/yaw와 resolution 변환은 기존 `map_math.js`가 담당한다.
- fit·zoom·pan과 screen↔map cell 변환은 `map_viewport.js`가 담당한다.
- 클릭은 자유 셀만 허용하고 선택 pose는 해당 셀 중앙에 고정한다.
- 새로 고른 자유 셀 후보가 없으면 초기 위치·목적지·작업 전송 버튼을 비활성화한다.
- 페이지 재시작의 기본 `(0,0,0)`과 실패·취소된 과거 목표는 전송 후보로 재사용하지 않는다.
- 현재 위치·활성 목표·전송 후보를 서로 다른 색과 라벨로 표시하며 해상도와 cell 수를 노출한다.
- 지도 밖, unknown, occupied 셀은 브라우저에서도 거부하고 서버가 다시 검증한다.
- 휠 확대, Shift+드래그 이동, 커서의 world 좌표·cell·occupancy 값을 제공한다.

클라이언트 검증은 사용성을 높이는 보조 검증이다. 안전·정합의 권위는 계속 Gateway의
`MapRegistry.validate_pose`에 있다.

## 완료 조건

- [x] 로그 파싱·특징·dataset hash·모델 학습·품질 gate·승격 코드
- [x] `/rosout` → `/fleet/rosout` relay, 수집 node와 Zenoh allowlist
- [x] REST 상태와 단일 화면 MLOps 카드
- [x] 확대·이동·고해상도 overlay·셀 중앙 선택 지도 뷰포트
- [x] 단위·API·지도 좌표 회귀 테스트
- [x] TB1 `/rosout` 수신과 일별 raw artifact 실측(2026-07-19, 누적 45건)
- [ ] 정상 운전 기준 후보 학습·품질 검토·Production 승격
- [ ] 알려진 오류 로그 주입에서 ANOMALY와 원인 특징 확인
- [ ] false positive와 데이터 보존 기간을 실측한 운영 기준 확정

실차 데이터와 모델 품질 증거 전에는 Phase 7 전체를 완료로 표시하지 않는다.
