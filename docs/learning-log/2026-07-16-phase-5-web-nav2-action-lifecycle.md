# 학습 일지: Phase 5 웹 Nav2 Action 수명주기 구현

날짜: 2026-07-16
단계: Phase 5D 코드 구현
진행 상태: 자동 검증 완료, TB1 웹 Goal 실차 검증 대기

## 오늘의 목표

- Fleet Gateway에서 로봇별 `NavigateToPose` Goal을 전송한다.
- Goal 수락, 진행 feedback, 성공·실패·취소·timeout을 웹에 표현한다.
- e-stop과 Action 취소의 책임을 분리하면서 함께 동작하게 한다.
- 늦은 비동기 callback이 안전 상태를 되돌리지 못하게 한다.
- 작업 내용과 면접에서 설명할 설계 근거를 기록한다.

## 왜 이 작업을 했는가

Nav2 Goal은 한 번 발행하고 끝나는 속도 Topic이 아니다. 수 초에서 수 분 동안 실행되며
서버 수락, 진행 feedback, 운영자 취소와 최종 result가 필요하다. 따라서 HTTP 요청 하나를
목적지 도착까지 계속 열어 두는 방식보다 ROS 2 Action 수명주기를 웹 계약으로 변환해야 한다.

웹은 최종 안전장치가 아니다. 통신이 끊기거나 Nav2 취소가 늦어져도 실제 모터 직전의
`safety_watchdog`가 로봇에서 e-stop과 timeout을 집행해야 한다.

## 구현한 구조

```text
Browser
  POST /navigation/goals
          |
          v
FastAPI validation -- thread pool --> FleetGatewayNode ActionClient
          |                                  |
          |                                  v
          |                         /navigate_to_pose
          |                                  |
          +<-- NavigationRegistry <-- feedback/result
                         |
                         v
                  WebSocket snapshot

timeout / e-stop --> watchdog SetBool + Action cancel
```

### HTTP API

- `POST /api/robots/{robot_id}/navigation/goals`
- `GET /api/robots/{robot_id}/navigation`
- `POST /api/robots/{robot_id}/navigation/cancel`
- `WS /ws/robots`에 navigation snapshot 포함

Goal 요청은 `x`, `y`, `yaw`, `timeout_sec`를 받는다. 모든 숫자는 유한해야 하며 frame은
`map`만 허용한다. 알려지지 않은 로봇은 404, 오프라인 로봇과 중복 활성 Goal은 409,
Action 서버 부재와 ROS 호출 실패는 503으로 응답한다.

### 상태 모델

```text
PENDING -> RUNNING -> SUCCEEDED
                   -> ABORTED
                   -> CANCELING -> CANCELED
                                -> TIMEOUT
PENDING -> REJECTED
```

로봇마다 최신 Goal 하나를 보관한다. 활성 상태는 `PENDING`, `RUNNING`, `CANCELING`이며
이 상태에서 두 번째 Goal은 거부한다. snapshot은 deep copy로 반환해 HTTP thread가 내부
상태를 실수로 바꾸지 못하게 했다.

### HTTP와 Action의 시간 경계

HTTP는 Action 서버가 Goal을 수락하거나 거부할 때까지만 기다린다. 수락되면
`202 Accepted`와 Goal ID를 반환하고, 최종 목적지 도착은 WebSocket이나 상태 조회로
확인한다. HTTP 수락 제한시간과 전체 주행 timeout은 서로 다른 값이다.

### e-stop 규칙

1. e-stop 적용 요청은 watchdog를 먼저 정지 상태로 만든다.
2. 활성 Nav2 Goal이 있으면 이어서 취소를 요청한다.
3. Goal이 활성 상태인 동안 e-stop 해제를 거부한다.
4. Goal timeout이면 watchdog e-stop과 Action 취소를 함께 요청한다.
5. Action 취소 실패나 지연이 있어도 e-stop은 유지한다.

## 코드 리뷰에서 발견한 경합 조건

### 1. 종료된 Goal의 늦은 수락

매우 짧은 Goal timeout 중 Action 수락 응답이 늦으면 registry는 이미 `TIMEOUT`인데
수락 callback이 무조건 `RUNNING`을 기록할 수 있었다. 사용자가 끝났다고 생각하는 Goal이
되살아나는 위험이다.

해결:

- `mark_running()`은 현재 상태가 정확히 `PENDING`일 때만 허용한다.
- 수락 시점에 이미 종료됐으면 Goal을 즉시 취소한다.
- 로컬 e-stop을 적용해 fail-closed를 유지한다.
- 회귀 테스트로 `TIMEOUT -> RUNNING` 전이가 불가능함을 고정했다.

### 2. 이전 result가 새 handle을 삭제하는 경합

로봇 ID만 key로 handle을 보관하고 이전 Goal result callback이 단순 `pop(robot_id)`을 하면,
그 사이 시작된 새 Goal의 handle을 지울 수 있다.

해결:

- `(goal_id, goal_handle)`을 함께 보관한다.
- callback의 Goal ID와 현재 소유 Goal ID가 같을 때만 handle을 삭제한다.
- cancel과 timeout도 일치하는 Goal handle만 사용한다.

### 3. WebSocket disconnect 로그 예외

로컬 미리보기에서 일부 close event에 `code`가 없어 Starlette 내부에서 `KeyError`가
발생했다. close code가 빠진 disconnect도 정상 종료로 처리해 Gateway task exception이
로그에 남지 않도록 했다.

## 웹 화면

로봇 카드마다 다음 항목을 추가했다.

- X, Y, yaw, timeout 입력
- 현재 Goal 상태
- 남은 거리와 예상 시간 feedback
- 목적지 전송과 주행 취소 버튼

0.5초 WebSocket 갱신 때 카드 DOM이 다시 그려져도 입력 초안과 현재 focus가 유지되도록
브라우저 측 상태를 분리했다. 로컬 미리보기에서 TB1 상태와 Nav2 패널 표시, 입력 유지,
온라인·활성 상태에 따른 버튼 활성화를 확인했다. Codex 앱 안정성을 위해 반복 내장 브라우저
검증은 중단했고, 이후 검증은 자동 테스트와 실제 사용자 브라우저로 분리한다.

## 자동 검증 결과

### Gateway 집중 테스트

```text
36 tests, 0 errors, 0 failures, 0 skipped
```

포함 범위:

- registry 상태 전이와 defensive copy
- 중복 Goal, timeout, 취소와 늦은 수락 차단
- HTTP 입력 검증, offline과 상태 코드
- WebSocket navigation snapshot
- pose/yaw quaternion과 feedback 변환
- 가짜 `NavigateToPose` Action Server의 성공·취소·timeout 통합 흐름

### 전체 workspace

```text
5 packages finished
169 tests, 0 errors, 0 failures, 0 skipped
```

패키지별 결과:

- `safety_watchdog`: 18
- `robot_agent`: 33
- `fleet_navigation`: 82
- `fleet_gateway`: 36
- `fleet_interfaces`: 메시지 빌드 완료

JavaScript는 Node.js `--check`도 통과했다. pytest warning은 기존 Python entry point API의
deprecated 경고이며 실패가 아니다.

## 오늘 꼭 기억해야 할 것

1. Goal 수락은 목적지 도착 성공이 아니다.
2. Topic은 스트림, Service는 짧은 요청·응답, Action은 장시간 작업·feedback·취소다.
3. timeout 취소는 협조적 요청이고 e-stop은 로봇 로컬의 강제 안전 경계다.
4. 비동기 callback은 순서대로 도착한다고 가정하면 안 된다.
5. 상태 변경과 resource 정리는 같은 Goal ID의 소유권을 확인해야 한다.
6. 웹 버튼 비활성화만 믿지 말고 서버가 offline·중복 Goal·비유한 입력을 거부해야 한다.

오늘의 한 문장:

> 장시간 로봇 작업은 Goal ID와 상태를 끝까지 추적하고, 통신·취소 실패의 최종 안전은
> 로봇 로컬 watchdog가 책임지게 설계한다.

## 면접 질문과 모범 답변

### “웹에서 Nav2 자율주행을 어떻게 연결했습니까?”

> FastAPI 요청을 ROS 2 `NavigateToPose` Action Client에 연결했습니다. HTTP는 Goal 수락
> 여부까지만 확인해 `202 Accepted`를 반환하고, 진행 feedback과 최종 result는 thread-safe
> registry와 WebSocket으로 전달합니다. 로봇별 활성 Goal은 하나만 허용하고 입력 숫자,
> map frame과 online 상태를 서버에서 검증합니다. timeout이나 늦은 수락에서는 Action
> 취소와 로봇 로컬 e-stop을 함께 사용합니다. 코드 리뷰에서 종료 Goal의 재활성화와 이전
> callback이 새 handle을 삭제하는 경합을 찾아 Goal ID 기반 상태 전이와 소유권 검사로
> 막았고, 가짜 Action Server 통합 테스트를 포함한 전체 169개 테스트를 통과했습니다.

## 복습 문제와 정답

### 1. HTTP Goal 응답이 `202`인 이유는?

정답: 요청이 최종 완료된 것이 아니라 Nav2가 장시간 작업을 시작하도록 수락했기 때문이다.
최종 성공은 Action result로 나중에 결정된다.

### 2. timeout에서 cancel과 e-stop을 함께 실행하는 이유는?

정답: cancel은 Nav2가 처리해야 하는 비동기 협조 요청이고 실패하거나 늦을 수 있다. e-stop은
watchdog가 최종 모터 출력을 즉시 0으로 제한하는 독립 안전 수단이다.

### 3. `PENDING -> RUNNING` 조건을 엄격히 검사하는 이유는?

정답: 이미 취소되거나 timeout된 Goal의 늦은 수락이 종료 상태를 덮어써 다시 실행되는 것을
막기 위해서다.

### 4. handle을 로봇 ID만으로 관리하면 어떤 문제가 생길 수 있는가?

정답: 이전 Goal의 늦은 callback이 같은 로봇의 새 Goal handle을 삭제할 수 있다. Goal ID와
handle을 묶고 소유권이 일치할 때만 정리해야 한다.

### 5. 웹에서 입력을 검사했는데 서버도 검사해야 하는가?

정답: 그렇다. HTTP API는 브라우저 UI 외의 client도 호출할 수 있고 프런트엔드는 우회되거나
오작동할 수 있다. 안전·권한 규칙은 신뢰 경계인 서버에서 다시 강제해야 한다.

## 아직 검증하지 않은 것

- TB1 저장 지도에서 실제 `NavigateToPose` 성공·취소·실패
- Zenoh를 통과한 실제 Goal feedback과 cancel
- 웹 Goal과 실차 e-stop 상호작용
- 네트워크 단절 중 Action 상태 정합과 재연결 정책

## 다음에 할 일

1. 보정된 SLAM queue 설정에서 TB1 pose graph node 증가를 확인한다.
2. 실제 지도를 완성하고 YAML·PGM·pose graph를 자동·시각 검증한다.
3. AMCL 초기 위치를 설정하고 터미널 Goal부터 실차 검증한다.
4. 같은 경로를 웹 Goal API로 검증한다.
5. TB2 namespace와 Action 이름을 격리해 다중 로봇으로 확장한다.

## 관련 커밋

- `b37ecaa feat: add web Nav2 goal lifecycle`
- 문서 커밋: 이 일지를 포함하는 다음 커밋
