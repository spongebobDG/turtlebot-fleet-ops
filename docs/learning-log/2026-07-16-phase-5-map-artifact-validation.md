# 학습 일지: Phase 5 저장 지도 검증 CLI 구현

날짜: 2026-07-16
단계: Phase 5B TB1 지도 작성
진행 상태: CLI와 자동 테스트 완료, 실차 지도 저장 대기

## 오늘의 목표

- SLAM으로 저장한 YAML·PGM이 Nav2 입력으로 사용할 최소 구조를 갖췄는지 자동 검사한다.
- pose graph와 data 파일의 누락을 배포 전에 찾는다.
- 자동 검사의 범위와 RViz 육안 검토의 범위를 구분해 기록한다.

## 왜 이 작업을 했는가

`map_saver_cli`가 종료 코드 0을 반환해도 YAML이 잘못된 이미지 경로를 참조하거나 PGM이
잘렸거나 pose graph 한 파일이 누락될 수 있다. 이런 오류를 AMCL 시작 뒤에 발견하면 원인
범위가 Map Server, 파일, TF와 localization 전체로 넓어진다. 저장 직후 fail-fast 검사하면
문제를 지도 산출물 단계에서 차단할 수 있다.

반대로 픽셀 수가 맞고 파일을 읽을 수 있다는 사실만으로 벽이 실제 공간과 일치한다고 할 수는
없다. 따라서 자동 구조 검사와 RViz·현장 품질 검사를 서로 다른 gate로 둔다.

## 구현한 기능

`fleet_navigation`에 `validate_map` CLI를 추가했다.

- YAML 필수 필드와 숫자 유한성 검사
- 저장소에서 재현 가능한 상대 `image` 경로 강제
- `../` 또는 symlink로 map 디렉터리를 벗어나는 이미지 경로 거부
- 현재 운영 기준인 `trinary` 지도 모드 강제
- 양수 해상도와 `x, y, yaw` 원점 검사
- `0 <= free_thresh < occupied_thresh <= 1` 검사
- P2·P5 PGM, 8비트·16비트 raster 크기와 픽셀 범위 검사
- map-server 임계값으로 occupied/free/unknown cell 계산
- 최소 known cell 수와 비율 검사
- 선택적으로 `.posegraph`, `.data` 쌍 검사
- 성공 시 `MAP_VALIDATION=PASS`, 실패 시 종료 코드 2와 원인 출력

실행 예시는 다음과 같다.

```bash
ros2 run fleet_navigation validate_map \
  robot/fleet_navigation/maps/tb1_lab.yaml \
  --min-known-cells 100 \
  --min-known-ratio 0.01 \
  --require-pose-graph
```

## 테스트 과정과 실제 결과

첫 실행에서는 4개 테스트가 실패했다.

```text
fleet_navigation: 62 tests
4 failures
```

검사 코드가 아니라 합성 fixture의 회색값 선택이 원인이었다. 픽셀 205는
`free_thresh=0.25`에서 점유확률 약 0.196이므로 free cell이다. unknown을 의도한
fixture를 점유확률 약 0.502인 픽셀 127로 수정했다. 또한 다른 해석 규칙을 조용히
오분류하지 않도록 `trinary` 이외의 mode를 명시적으로 거부했다.

재실행 결과는 다음과 같다.

```text
fleet_navigation: 64 passed
workspace total: 128 tests
errors: 0
failures: 0
skipped: 0
installed executable: fleet_navigation validate_map
GitHub Actions PR #6 Humble build and test: pass
```

다룬 경계 조건은 정상 P5, 주석이 있는 P2, 16비트 PGM, negate 반전, 절대 경로,
상대 경로 이탈, 이미지 누락, 임계값 역전, 미지원 mode, 잘린 raster, 최소 관측량과
pose graph 누락이다.

## 자동 검사가 보장하는 것과 보장하지 않는 것

자동 검사가 보장하는 것:

- Map Server가 읽어야 할 YAML·PGM의 기본 구조가 일관됨
- 상대 이미지 경로로 다른 장비에서도 재현 가능함
- 선언한 cell 수와 실제 raster 크기가 일치함
- 최소한의 관측 데이터와 pose graph 파일 쌍이 존재함

자동 검사가 보장하지 않는 것:

- 벽의 이중선과 끊김이 없음
- loop closure가 올바름
- 실제 공간 축척과 방향이 정확함
- AMCL이 해당 지도에서 수렴함
- Nav2 Goal이 안전하게 성공함

## 오늘 꼭 기억해야 할 것

1. `map_saver_cli` 성공과 지도 품질 통과는 서로 다른 조건이다.
2. YAML의 상대 이미지 경로는 재현 가능한 배포 산출물의 일부다.
3. unknown 비율은 지도 canvas 크기에도 영향을 받으므로 known cell 수와 함께 본다.
4. YAML·PGM은 localization용이고 pose graph·data는 SLAM 재개용이다.
5. 자동 구조 검사 뒤에도 RViz와 실물 공간 비교가 반드시 필요하다.

## 면접에서 이렇게 설명한다

> 지도 저장 성공을 프로세스 종료 코드 하나로 판단하지 않았습니다. YAML 메타데이터와
> 상대 이미지 경로, PGM raster 크기, 점유 임계값, known cell 최소량과 pose graph 쌍을
> 검사하는 CLI를 만들고 경계 조건을 단위 테스트했습니다. 다만 구조적으로 올바른 지도도
> 벽이 겹치거나 loop closure가 틀릴 수 있으므로 자동 검사는 fail-fast gate로 사용하고,
> RViz 시각 검토와 AMCL 실차 수렴을 별도 acceptance gate로 유지했습니다.

## 복습 문제와 정답

### 1. PGM을 읽을 수 있는데도 YAML 검사가 필요한 이유는?

정답: Map Server는 이미지뿐 아니라 해상도, 원점, negate와 점유 임계값을 YAML에서 읽기
때문이다. 이미지가 정상이어도 메타데이터가 틀리면 지도 좌표와 cell 분류가 달라진다.

### 2. known ratio만 사용하지 않고 known cell 수도 확인하는 이유는?

정답: ratio는 canvas 크기에 따라 달라지고, 작은 이미지에서는 높은 비율이어도 관측 cell
절대량이 너무 적을 수 있다. 절대량과 비율을 함께 봐야 최소 데이터 기준을 더 명확히 한다.

### 3. 자동 검사 PASS가 지도 품질 PASS가 아닌 이유는?

정답: 파일 구조와 픽셀 분포만으로는 벽의 이중선, 누적 자세 오차, loop closure와 실제
공간 일치를 판단할 수 없기 때문이다.

### 4. pose graph 파일을 Nav2가 직접 사용하지 않는데 왜 보관하는가?

정답: Nav2 localization은 YAML·PGM을 사용하지만, mapping을 이어서 수정하려면 SLAM의
노드·제약·센서 데이터가 든 pose graph와 data가 필요하기 때문이다.

## 완료 체크리스트

- [x] 지도 메타데이터와 PGM parser 구현
- [x] 관측 cell 통계와 최소 기준 구현
- [x] pose graph 쌍 검사 구현
- [x] 12개 지도 검증 테스트 작성
- [x] WSL ROS 2 Humble에서 128개 전체 테스트 통과
- [x] 운영 절차와 공부·면접 문서 갱신
- [ ] TB1 실차 지도 저장 후 CLI 실행
- [ ] RViz 지도 품질 검토
- [ ] AMCL 초기 위치와 수렴 검증

## 다음에 할 일

1. 사용자 물리 확인 후 안전한 mapping 구간을 계속한다.
2. 완성된 `tb1_lab` 네 파일을 저장하고 `validate_map`을 실행한다.
3. 민감한 공간 정보가 없는지 확인한 뒤 지도 품질과 AMCL 수렴을 검증한다.

## 관련 커밋

- `feat: add saved map artifact validator`
