# TB1 maps

실차 매핑 전에는 예제 지도를 커밋하지 않는다. 검증한 지도만 다음 이름으로 저장한다.

- `tb1_lab.yaml`: Nav2 Map Server 메타데이터
- `tb1_lab.pgm`: 점유 격자 이미지
- `tb1_lab.posegraph`: SLAM Toolbox 재개용 pose graph
- `tb1_lab.data`: pose graph 보조 데이터

지도 YAML의 `image`는 저장소 안의 상대 경로를 사용한다. 정확한 건물명, 출입 통제
정보나 민감한 공간 구조는 Public 저장소에 올리지 않는다.
