# 사례 연구: 가변 LDS-02 스캔을 SLAM Toolbox 입력으로 정규화

## 한 줄 요약

`/scan` Publisher와 데이터가 모두 존재했지만 LDS-02의 배열 길이와 각도 범위가 회전마다
바뀌어 SLAM Toolbox가 스캔을 거부했다. 원본을 고정 길이로 자르지 않고 각도 기준
360-bin 스캔으로 재투영해 지도를 생성했다.

## 상황

TB1 bringup, `/scan`, `/odom`과 TF는 정상인데 SLAM Toolbox에서 `/map` 메시지가
나오지 않았다. 로그에는 다음 형태의 오류가 반복됐다.

```text
LaserRangeScan contains 218 range readings, expected 219
```

토픽 이름과 Publisher 수만 보면 센서는 정상처럼 보였지만 SLAM 소비자가 요구하는
메시지 내부 계약은 만족하지 못한 상태였다.

## 측정한 증거

실제 `/scan` 100개를 수집해 메시지별 배열과 각도 메타데이터를 비교했다.

- `ranges`와 `intensities` 길이: 207~219
- 가장 자주 나온 길이: 216, 211, 215
- `angle_min`: 약 0.148~0.324 rad
- `angle_max`: 약 5.919~6.199 rad
- `angle_increment`: 약 0.02745~0.02767 rad
- 한 회전 시간: 약 0.0987~0.0995초

배열 길이뿐 아니라 시작·끝 각도도 함께 변했으므로 단순 pad/truncate는 빔의 실제 각도를
틀리게 만들 수 있었다.

## 선택한 해결책

`fleet_navigation/scan_normalizer`를 추가했다.

```text
ld08_driver /scan
        |
        v
scan_normalizer
        |
        v
/scan_normalized: 0~359도, 360 bins
        |
        +--> SLAM Toolbox
        +--> AMCL
        `--> Nav2 costmap
```

처리 규칙은 다음과 같다.

1. 원본 샘플의 실제 각도를 `angle_min + index * angle_increment`로 계산한다.
2. 각도를 0~2π 범위로 감싼다.
3. 가장 가까운 1도 bin에 측정값을 배치한다.
4. 같은 bin에 둘 이상이 들어오면 더 가까운 거리를 선택한다.
5. 관측되지 않은 bin과 유효 범위 밖 측정은 `+inf`로 둔다.
6. 원본 `/scan`은 Robot Agent와 장애 분석을 위해 그대로 보존한다.

`+inf`는 가짜 거리나 0을 넣는 것보다 안전하다. 0은 로봇 바로 앞 장애물로 해석될 수
있고, 임의 보간은 센서가 보지 않은 장애물 정보를 만들어 낼 수 있다.

## 단순 잘라내기를 선택하지 않은 이유

첫 메시지 길이에 맞춰 뒤를 자르거나 채우면 배열 크기는 일정해지지만 각 index가 뜻하는
방향이 회전마다 달라질 수 있다. SLAM은 각 거리와 각도의 조합으로 점을 배치하므로 이
오류는 벽을 휘거나 겹치게 만든다. 각도 기준 재투영은 배열 위치와 물리 방향의 계약을
유지한다.

## 검증 결과

- 새 단위 테스트 7개 통과
- TB1 `fleet_navigation` 15개 테스트 통과
- 실제 `/scan_normalized` 20개 모두 길이 360
- 고정 `angle_min=0`, `angle_increment=1도`, `angle_max=359도`
- 정지 상태 지도: 0.05m 해상도, 160×192 cells
- `map -> odom` TF 출력
- `/cmd_vel`: 선속도·각속도 모두 0
- SLAM journal의 `expected`, `error`, `fatal`, `exception`: 없음

## 남은 한계와 다음 검증

- 정지 상태 지도 생성은 확인했지만 이동 중 loop closure와 벽 정합은 아직 확인 전이다.
- 1도 격자의 빈 bin은 보간하지 않으므로 costmap과 실제 지도 품질을 실차에서 확인한다.
- GPIO 임시 점퍼의 기계적 신뢰성은 소프트웨어 정규화로 해결되지 않는다.
- 장시간 CPU·메모리 사용량과 scan drop도 실제 매핑 중 측정한다.

## 면접 모범 답변

> `/scan` 토픽이 존재하는데도 SLAM 지도가 나오지 않아 메시지 내부 형상을 100회
> 측정했습니다. LDS-02 드라이버가 207~219개의 가변 배열과 서로 다른 시작·끝 각도를
> 발행했고 SLAM Toolbox가 첫 스캔 형상과 다른 입력을 거부하는 문제였습니다. 단순
> padding은 각도 의미를 깨므로 실제 각도를 계산해 고정 360-bin으로 재투영하는 ROS 2
> 노드를 만들었습니다. 관측되지 않은 각도는 `+inf`, 중복 bin은 가까운 장애물을
> 선택했고, 20회 고정 형상과 실제 `/map`, TF, 0속도를 검증했습니다.
