# ROS 2 로그 MLOps 운영 절차

이 절차는 관제 PC에서 TB1 `/rosout` 수집, 기준 데이터 학습, Production 승격, 추론 확인과
rollback을 수행한다. 원시 로그와 모델은 Git이 아닌 사용자 로컬 데이터 디렉터리에 저장한다.

## 1. 서비스와 데이터 확인

```bash
systemctl --user is-active \
  fleet-control-zenoh.service \
  fleet-gateway.service \
  fleet-log-mlops.service

ros2 topic info /fleet/rosout -v
curl -sS http://localhost:8000/api/mlops/ros2-logs | jq
find ~/.local/share/turtlebot-fleet-ops/mlops/ros2-logs/raw \
  -maxdepth 1 -type f -name 'live-*.jsonl' -ls
```

처음에는 `MODEL_NOT_READY`가 정상이다. 이는 수집 장애가 아니라 검토·승격된 모델이 아직
없다는 뜻이다. TB1이 online인데 raw 파일이 늘지 않으면 TB1의 `rosout_relay`, 두 Zenoh
allowlist의 `/fleet/rosout`,
publisher/subscriber 수와 `fleet-log-mlops.service` journal을 확인한다.

`MODEL_NOT_READY`에서도 Dashboard와 REST의 `operational_signals`는 최근 5분의 제어 주기 지연,
경로 생성 실패, 충돌 방지 개입, 주행 진척 없음과 메시지 유실 횟수를 보여준다. 이는 규칙 기반
현장 설명이며 anomaly score가 아니다. 활성 목표가 멈췄다면 먼저 이 신호와 `NavigationStatus`의
복구 횟수, LiDAR 최소 거리를 대조하고 같은 목표를 연속 전송하지 않는다.

Nav2 재기동 직후 `초기 위치 대기`는 AMCL 오류가 아니라 웹에서 실제 로봇 pose를 다시 지정해야
한다는 뜻이다. 이 구간의 transform timeout을 정상 주행 baseline에 섞지 않는다.

## 2. 깨끗한 기준 구간 수집

초기 기준은 e-stop·통신 단절·프로세스 종료 시험을 하지 않는 정상 운전 구간으로 잡는다.
최소 품질 gate는 60초 창 5개와 로그 20개지만, 실제로는 15~30분 이상을 권장한다. 기준 구간의
시작·종료, 로봇 상태와 의도한 작업을 학습 일지에 남긴다.

```bash
journalctl --user -u fleet-log-mlops.service --since '10 minutes ago' --no-pager
wc -l ~/.local/share/turtlebot-fleet-ops/mlops/ros2-logs/raw/live-*.jsonl
```

로그 메시지에는 현장 정보가 있을 수 있다. raw 파일을 PR에 첨부하거나 저장소로 복사하지 않는다.

## 3. 후보 데이터셋과 모델 생성

```bash
cd ~/turtlebot-fleet-ops
bash scripts/control-pc/train_ros2_log_baseline.sh
```

스크립트는 모든 일별 raw JSONL을 60초 창으로 만들고 content hash가 있는 dataset과 candidate
model을 생성한다. 출력의 `windows`, `records`, `gate_passed`, `QUALITY_WARNING`과 candidate
경로를 확인한다. 0·비유한 timestamp는 학습에서 제외되고 경고에 제외 건수가 남는다. gate 실패를
데이터 복제나 임계값 완화로 숨기지 말고 깨끗한 데이터를 더 수집한다.

후보 파일에서 다음을 검토한다.

```bash
jq '{model_id,dataset_hash,threshold,quality,centers,scales}' \
  ~/.local/share/turtlebot-fleet-ops/mlops/ros2-logs/models/*.json
```

## 4. Production 승격

정상 기준 구간과 품질 지표를 확인한 뒤 같은 pipeline을 `--promote`로 실행한다.

```bash
bash scripts/control-pc/train_ros2_log_baseline.sh --promote
curl -sS http://localhost:8000/api/mlops/ros2-logs | jq
```

승격은 candidate의 `quality.gate_passed=true`일 때만 가능하지만 숫자 gate 통과만으로 승격하지
않는다. timestamp 경고가 없고 Nav2·AMCL·robot agent logger와 정상 작업 상태가 기준 구간을
대표하는지 검토한다. 승격 후 monitor service가 재시작되고 다음 15초 inference부터
`model_stage=production`과 model ID가 표시되어야 한다.

## 5. 이상 판정 확인

운영 중에는 Dashboard의 `ROS 2 Log MLOps` 카드와 REST를 함께 본다.

```bash
watch -n 2 'curl -sS http://localhost:8000/api/mlops/ros2-logs | \
  jq "{state,model_id,score,threshold,log_count,top_features,operational_signals,message}"'
```

`ANOMALY`는 자동 e-stop이 아니다. 상위 특징을 보고 관련 unit journal, NavigationStatus, safety
status와 `/cmd_vel`을 교차 확인한다. 모델이 NORMAL이어도 watchdog 경고나 e-stop을 무시하면
안 된다.

검증용 오류는 빈 공간에서 활성 목표가 없고 e-stop인 상태에서만 주입한다. 물리 안전 시험을
로그 모델 검증 때문에 임의로 반복하지 않는다. 이미 기록된 오류 JSONL을 별도 test root에서
offline 분석하는 방법을 우선한다.

## 6. Rollback과 재학습

Production 파일은 로컬 registry 한 개다. 잘못 승격한 경우 직전 검토 모델을 다시 promote한다.

```bash
ros2 run fleet_gateway ros2_log_mlops \
  --root ~/.local/share/turtlebot-fleet-ops/mlops/ros2-logs \
  promote --input /path/to/previous-candidate.json
systemctl --user restart fleet-log-mlops.service
```

소프트웨어·Nav2 설정·센서가 바뀌거나 지속적인 false positive가 생기면 새 dataset hash와 모델
ID로 재학습한다. 과거 모델 파일을 덮어쓰지 않고 candidate와 승격 시각을 학습 일지에 기록한다.
