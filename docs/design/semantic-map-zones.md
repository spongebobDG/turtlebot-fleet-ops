# TB1 의미 기반 운영지도

## 현재 구현 범위

기존 SLAM 점유지도는 위치 추정용 원본으로 유지하고, 사용자가 만든 공간
정책을 별도 레이어로 저장한다. 운영구역은
`~/.local/share/turtlebot-fleet-ops/map-annotations.json`에 원자적으로
저장되며 지도 화면 위에 항상 겹쳐 표시된다.

| 객체 | 웹 표시 | Gateway 강제 정책 | TB1 Nav2 정책 |
| --- | --- | --- | --- |
| 가상 벽 | 붉은 선과 로봇 안전 폭 | 목적지·웹 WASD 차단 | Keepout mask |
| 금지구역 | 주황색 다각형 | 목적지·웹 WASD 차단 | Keepout mask |
| 개인정보 보호구역 | 보라색 다각형 | 강제 진입 차단, `NO_CAPTURE_NO_STORAGE` 정책 기록 | Keepout mask |
| 충전 위치 | 녹색 위치·방향 | 저장된 서버 목적지로만 이동 | 일반 Nav2 목적지 |

가상 벽과 구역에는 TB1 Burger 반경과 근접 여유를 포함한 기본 0.16m
안전 여유가 적용된다. 구역 변경 중 활성 목적지, 순찰 또는 수동 세션이
있으면 API가 변경을 거부한다. 현재 로봇 위치를 포함해 로봇을 가두는
구역도 저장할 수 없다.

## 웹 사용법

1. `http://localhost:8000`을 새로고침한다.
2. 지도 상단의 `운영구역 편집`을 누른다.
3. 다음 방법으로 그린다.
   - 가상 벽: 시작점에서 끝점까지 드래그한다.
   - 금지구역·개인정보: 지도에서 꼭짓점을 세 개 이상 누른다.
   - 충전 위치: 위치에서 충전 도크를 바라볼 방향으로 드래그한다.
4. 이름을 확인하고 `저장·적용`을 누른다.
5. 잘못 만든 구역은 편집 창 목록의 `삭제`로 제거한다.

배터리가 20% 이하이거나 `LOW_BATTERY` 경고가 발생하면 지도 아래가
주황색으로 강조된다. 충전 위치가 지정되어 있으면 `충전하러 가기`를
눌러 해당 위치로 이동할 수 있다. 현재 단계에서는 도착 후 사람이
충전기를 직접 연결해야 한다.

## 강제 차단 계층

Gateway는 다음 요청을 서버에서 다시 검증하므로 브라우저 검사만
우회해서 금지구역에 들어갈 수 없다.

- 즉시 목적지와 저장 작업
- 순찰점 생성과 실행
- 충전 위치 이동
- 웹 WASD 전진·후진의 단기 예측 위치

회전 명령은 위치를 바꾸지 않으므로 허용한다. 직진 명령이 구역 경계에
닿으면 Gateway가 먼저 0 속도를 전송한 뒤 요청을 거부한다.

TB1에는 `map_annotation_filter` 노드를 추가했다. 이 노드는 제어 PC가
보낸 벡터 구역과 로컬 `/map`을 결합해 다음 토픽을 만든다.

- `/tb1/map_annotations/filter_mask`
- `/tb1/map_annotations/filter_info`

전역·지역 Costmap 모두 `nav2_costmap_2d::KeepoutFilter`를 사용한다.
따라서 로봇 패키지가 배포된 뒤에는 Nav2가 가상 벽을 실제 장애물처럼
우회한다.

## 이 PC에서 남은 배포 단계

현재 제어 PC에는 TB1 전용 SSH 키가 없어 Gateway와 웹만 배포됐다.
로봇 측 Keepout 필터를 활성화하려면 먼저 전용 키를 준비한다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\control-pc\setup_tb1_ssh.ps1 -GenerateOnly
```

키 등록 후 변경사항을 Git에 커밋·push하고 정식 배포 스크립트를 사용한다.
이 배포는 먼저 e-stop을 적용하고 Nav2를 중지한 뒤 빌드와 테스트를
수행하며, 완료 후 로봇을 IDLE 상태로 둔다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\control-pc\prepare_tb1_acceptance.ps1 `
  -Action Deploy -RequireMap
```

배포 후 다음을 확인한다.

```bash
ros2 node list | grep map_annotation_filter
ros2 topic echo --once /tb1/map_annotations/filter_info
ros2 topic echo --once /tb1/map_annotations/filter_mask
```

## 아직 구현하지 않은 항목

- 자석·포고핀 충전 도크와 충전 전원회로
- 자동 배터리 충전 시작과 충전 완료 판정
- 카메라·마이크가 장착된 다른 로봇의 센서 차단
- 시간제 구역, 저속구역, 일방통행과 다중 로봇 충전 예약

이 항목들은 현재 TB1 하드웨어로 바로 검증할 수 없으므로 이번 범위에
포함하지 않았다.
