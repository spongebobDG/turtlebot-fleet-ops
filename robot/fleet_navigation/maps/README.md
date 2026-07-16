# TB1 maps

실차 매핑 전에는 예제 지도를 커밋하지 않는다. 검증한 지도만 다음 이름으로 저장한다.

- `tb1_lab.yaml`: Nav2 Map Server 메타데이터
- `tb1_lab.pgm`: 점유 격자 이미지
- `tb1_lab.posegraph`: SLAM Toolbox 재개용 pose graph
- `tb1_lab.data`: pose graph 보조 데이터

지도 YAML의 `image`는 저장소 안의 상대 경로를 사용한다. 정확한 건물명, 출입 통제
정보나 민감한 공간 구조는 Public 저장소에 올리지 않는다.

저장 직후 다음 검사로 메타데이터, PGM 구조, 관측 cell 수와 pose graph 쌍을 확인한다.

```bash
ros2 run fleet_navigation validate_map tb1_lab.yaml \
  --min-known-cells 100 \
  --min-known-ratio 0.01 \
  --require-pose-graph
```

`MAP_VALIDATION=PASS`는 파일이 일관되고 최소 데이터 기준을 충족한다는 의미다. 벽 이중선,
끊김, loop closure와 실제 공간 일치 여부는 RViz에서 별도로 검토해야 한다.

지도 저장 명령에는 `--free 0.196 --occ 0.65`를 명시한다. Humble 기본
`free_thresh=0.25`로 저장하면 trinary unknown 회색 205가 Map Server 재로드 때 free로
분류될 수 있으며, `validate_map`은 이를 실패로 처리한다.
