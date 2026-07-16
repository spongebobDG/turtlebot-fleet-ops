# 사례 연구: ROS Publisher 존재가 아닌 실제 freshness로 장애 감지

## 한 줄 요약

로봇 source process를 실제로 중단해 odom·scan·battery가 설정된 timeout 순서로 stale
전환되고, bringup 재시작 후 Robot Agent가 자동으로 OK로 복구되는 것을 검증했다.

## 상황

Phase 1에서는 `/scan` Publisher가 존재해도 실제 데이터가 나오지 않는 장애를 경험했다.
따라서 Phase 3 관제 상태는 노드나 topic 이름 존재만으로 정상 판정하면 안 됐다.

## 설계

각 source에 다음 세 상태와 두 시간 정보를 뒀다.

- received: 시작 후 한 번이라도 callback을 받았는가
- fresh: 마지막 callback age가 timeout 안인가
- valid: 최신 값 자체가 의미 있는가
- last_received: 로그·화면용 ROS timestamp
- age_sec: monotonic clock 기반 장애 판정용 경과시간

Timeout은 odom 1초, scan 2초, battery 5초로 설정했다.

## 첫 시험이 충분하지 않았던 이유

백그라운드 `ros2 launch` 부모에 SIGINT를 보냈지만 `ld08_driver`와 `turtlebot3_ros`가
계속 실행됐다. Agent는 계속 fresh 데이터를 받았고 `level=0`을 유지했다.

“정지 명령을 실행했다”는 사실이 아니라 source process와 실제 메시지가 중단됐는지를
확인해야 한다. 이 시험은 실패가 아니라 장애 전제 조건이 만들어지지 않은 불충분한
실험이었다.

## 재시험

두 source process에 TERM을 보내 실제 발행을 중단했다. Agent log는 다음 순서로 바뀌었다.

```text
ODOM_STALE
ODOM_STALE, SCAN_STALE
ODOM_STALE, SCAN_STALE, BATTERY_STALE
```

최종 snapshot은 `level=2`, 세 fresh false, 세 stale fault를 포함했다. last received와
age도 함께 남아 어떤 데이터가 언제 끊겼는지 설명할 수 있었다.

## 복구

bringup을 다시 시작하자 Agent를 재시작하지 않아도 callback이 재개되고 fault가 사라졌다.
최종 상태는 `level=0`, fault 없음으로 돌아왔다.

## STAR 면접 답변

### Situation

Publisher 존재만 확인하면 데이터가 멈춘 장애를 정상으로 오판할 수 있었다.

### Task

센서·주행 source가 실제로 갱신되는지를 판정하고 중단과 복구를 재현 가능하게 검증해야
했다.

### Action

received, fresh, valid를 분리하고 monotonic age 기반 timeout을 구현했다. 첫 SIGINT 시험에서
자식 process가 살아 있음을 확인해 장애가 재현되지 않았다고 판단했고, source process를
정확히 종료해 다시 시험했다. 이후 bringup을 재시작해 자동 복구까지 확인했다.

### Result

odom 1초, scan 2초, battery 5초 순서로 stale fault가 발생했고 전체 ERROR로 전환됐다.
source 재시작 후 Agent 재시작 없이 OK로 복구됐다. 정상·장애·복구 전 구간에 실제 메시지와
transition log를 남겼다.

## 1분 모범 답변

“ROS graph에서 Publisher가 보이는 것만으로 데이터가 정상이라고 판단하지 않았습니다.
각 source에 received, fresh, valid와 마지막 수신 age를 두고 monotonic timeout을
적용했습니다. 실제 TB1에서 처음에는 launch 부모에 SIGINT를 보냈지만 자식 driver가 살아
있어 상태가 계속 OK였습니다. 장애 조건이 성립하지 않았다고 판단해 driver process를
정확히 종료했고, odom 1초, scan 2초, battery 5초 순서로 stale fault와 ERROR가 발생하는
것을 확인했습니다. bringup 재시작 후에는 Agent를 재시작하지 않고도 OK로 자동
복구됐습니다. 명령 실행 여부가 아니라 실제 시스템 상태를 증거로 검증한 사례입니다.”

## 남은 개선

- systemd unit으로 PID와 lifecycle을 명확히 관리
- Fleet Gateway에서 RobotStatus heartbeat 중단 감지
- 실제 Wi-Fi 단절과 재연결 시간 계측
- fault 발생·복구 event를 SQLite에 영속화
