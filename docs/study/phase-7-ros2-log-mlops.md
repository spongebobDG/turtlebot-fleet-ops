# Phase 7 공부: ROS 2 로그 분석 MLOps

## 반드시 이해할 개념

### 로그 분석과 MLOps의 차이

정규식으로 ERROR를 찾는 것만 로그 분석이다. MLOps는 데이터 수집 버전, 특징 스키마, 학습
dataset hash, 모델 artifact, 품질 gate, Production 승격, 실시간 추론, 관측과 재학습을 하나의
재현 가능한 수명주기로 관리한다. 이 프로젝트는 `/rosout`을 일별 JSONL로 보존하고 60초 특징
dataset과 model ID를 연결한다.

### 왜 지도학습이 아닌 비지도학습인가

TB1에는 “정상·장애” 라벨이 충분하지 않다. 임의로 라벨을 만들면 정확도 숫자는 높아도 실제
의미가 없다. 먼저 정상 운전 분포의 중앙값과 MAD를 기준으로 벗어난 패턴을 찾고, 운영자가
원인 특징과 실제 event를 대조해 라벨 후보를 쌓는다. 데이터가 늘면 supervised 후보를 별도
평가할 수 있다.

### Median과 MAD

평균과 표준편차는 몇 개의 큰 오류 burst에 크게 끌린다. 중앙값은 순서의 가운데 값이고 MAD는
중앙값에서 떨어진 거리의 중앙값이라 outlier에 강하다. 특징값 `x`의 robust deviation은 대략
`abs(x - median) / (1.4826 * MAD)`다. MAD가 0인 작은 데이터에서는 feature별 최소 scale을 둬
0으로 나누거나 작은 변화가 무한 점수가 되는 문제를 막는다.

### Data drift와 concept drift

data drift는 로그의 양·비율 같은 입력 분포가 바뀌는 것이고, concept drift는 같은 로그 패턴의
운영 의미가 바뀌는 것이다. Nav2 버전이나 logger 문구가 바뀌면 정규식 특징도 바뀔 수 있다.
따라서 모델만 새로 학습하지 말고 pipeline version, 특징 스키마와 소프트웨어 변경을 함께
기록해야 한다.

### 모델 품질과 안전 품질은 다르다

이상탐지 false negative가 있어도 watchdog은 독립적으로 lease·authorization·e-stop을 검사한다.
반대로 모델 ANOMALY만으로 모터를 갑자기 정지시키면 false positive가 물리 동작을 방해한다.
현재 모델은 관측과 진단 우선순위를 제공할 뿐 motion authority를 갖지 않는다.

### 모델이 준비되기 전의 결정론적 로그 신호

MLOps를 도입했다고 모든 진단을 모델에 맡기면 안 된다. `Collision Ahead`나
`Control loop missed`처럼 의미가 명확한 로그는 즉시 횟수와 문맥을 보여주고, 같은 레코드를
버전된 특징 데이터에도 넣는다. 전자는 현재 사건을 설명하는 규칙 기반 관측이고 후자는 정상
기준에서의 편차를 학습하는 MLOps 입력이다. 둘을 구분하면 `MODEL_NOT_READY`를 장애 은폐로
오해하지 않으면서도 검토되지 않은 모델을 서둘러 Production에 올리지 않을 수 있다.

## 이 프로젝트의 MLOps 수명주기

1. TB1 relay가 `/rosout`을 `/fleet/rosout`으로 바꾸고 Zenoh allowlist로 전달한다.
2. collector가 공통 `LogRecord` 스키마로 정규화하고 Git 밖에 저장한다.
3. 60초 창 특징과 SHA-256 dataset hash를 만든다.
4. median/MAD candidate와 calibration score를 계산한다.
5. 최소 window·record gate를 통과하고 timestamp 품질·logger·작업 대표성을 검토한 candidate만
   명시적으로 Production에 승격한다. 숫자 gate는 필요조건이지 충분조건이 아니다.
6. 최근 5분 점수와 threshold, 원인 특징을 REST와 Dashboard에 표시한다.
7. 승격 전에는 같은 로그의 결정론적 운영 신호로 현장 원인을 설명한다.
8. false positive, 미탐과 software 변경을 근거로 새 dataset/model lineage를 만든다.

## 자주 하는 틀린 설명

| 틀린 설명 | 올바른 설명 |
| --- | --- |
| ERROR 로그가 하나면 AI가 장애로 판정한다 | 정상 기준에서 특징 비율이 얼마나 벗어났는지 시간창으로 판단한다 |
| 모델 파일만 있으면 재현 가능하다 | 코드·특징 스키마·dataset hash·품질 지표·승격 기록이 함께 필요하다 |
| 정확도 99%면 좋은 모델이다 | 라벨·class imbalance·시간 누수를 확인하지 않은 정확도는 의미가 없다 |
| Production 승격은 최신 모델 복사다 | 품질 gate와 검토를 통과한 immutable candidate를 명시적으로 승격한다 |
| ANOMALY면 즉시 e-stop해야 한다 | 모델은 관측 계층이고 안전 정지는 deterministic watchdog이 담당한다 |
| 로그 원본을 Git에 넣으면 추적성이 좋아진다 | 민감 정보와 용량 위험이 있어 hash와 manifest만 추적한다 |

## 면접 모범 답변

### 30초 답변

> ROS 2 `/rosout`을 Zenoh로 수집해 60초 단위 오류·경고·timeout·disconnect 특징을 만들고,
> 정상 기준의 median/MAD 이상탐지 모델을 운영했습니다. dataset hash부터 candidate 품질 gate,
> Production 승격, 실시간 점수와 설명 특징까지 추적했습니다. 모델은 진단용이고 로봇 정지는
> 독립적인 watchdog이 담당하도록 안전 경계를 분리했습니다.

### 1분 답변

> 단일 TB1은 장애 라벨이 적어서 처음부터 복잡한 지도학습을 쓰지 않았습니다. `/rosout`을
> 공통 스키마로 정규화하고 60초 창마다 로그량, ERROR·WARNING, timeout, disconnect,
> navigation failure 비율을 계산했습니다. 중앙값과 MAD 모델은 작은 데이터에서도 설명이 쉽고
> outlier에 강합니다. 각 dataset에는 hash, 각 모델에는 dataset hash와 품질 gate, 승격 시각을
> 남깁니다. 추론은 score와 threshold뿐 아니라 기여 특징 상위 세 개를 Dashboard에 보여줍니다.
> 다만 ML 결과를 motion authority에 연결하지 않고 lease, e-stop, authorization은 규칙 기반
> watchdog이 독립적으로 검사합니다.

## 실무형 질문

### 1. 정상 기준에 장애 로그가 섞이면 어떻게 되는가?

모델이 장애를 정상으로 학습해 threshold가 넓어질 수 있다. 수집 구간의 작업·fault event를 함께
검토하고 깨끗한 구간만 candidate 기준으로 사용한다. 이미 섞인 raw는 지우기보다 별도 dataset
선정 규칙과 hash로 lineage를 분리한다.

### 2. false positive를 어떻게 줄이는가?

임계값만 무조건 키우지 않는다. 기여 특징, logger, 운전 상태별 발생을 확인하고 window 크기,
logger별 특징, NORMAL 데이터 범위를 후보별로 offline 비교한다. 변경 전후 dataset과 지표를
남기고 같은 replay data로 회귀한다.

### 3. 시간 누수란 무엇인가?

미래 장애 이후의 로그가 학습 baseline이나 이전 예측 특징에 들어가는 문제다. dataset을
시간순으로 나누고 한 inference window는 그 시점 이전 로그만 사용해야 한다.

### 4. 모델이 없는 상태를 왜 503 대신 MODEL_NOT_READY로 보이는가?

Gateway와 collector가 정상인데 아직 승격 전인 운영 상태이기 때문이다. UI가 이를 숨기지 않고
구분하면 통신 장애, 추론 오류와 모델 lifecycle 대기를 각각 진단할 수 있다.

## 직접 복습 체크리스트

- [ ] raw log, dataset, model, registry, inference status의 차이를 설명한다.
- [ ] median/MAD가 평균/표준편차보다 유리한 상황을 말한다.
- [ ] dataset hash와 model ID로 lineage를 추적하는 이유를 말한다.
- [ ] candidate 품질 gate와 Production 승격을 분리한 이유를 말한다.
- [ ] ANOMALY와 e-stop을 직접 연결하지 않은 안전 이유를 말한다.
- [ ] drift가 생길 때 재학습 전 확인할 항목을 세 가지 말한다.

## 다음 학습 항목

- 시간순 validation set과 장애 replay corpus 구축
- logger·운전 상태별 특징 및 Isolation Forest 후보 비교
- precision/recall, detection latency와 alert fatigue 측정
- artifact 서명, 보존 기간과 접근 제어
