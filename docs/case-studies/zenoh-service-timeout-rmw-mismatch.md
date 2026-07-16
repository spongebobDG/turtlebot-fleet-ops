# Zenoh 상태 토픽은 보이지만 비상정지 서비스가 시간 초과된 사례

## 장애 현상

TB1의 `/fleet/robot_status`는 WSL Gateway까지 정상 도착했고 웹 대시보드도 실시간으로
갱신됐다. 그러나 웹에서 비상정지를 요청하면 Gateway가 3초 후 다음 오류를 반환했다.

```text
Emergency-stop service timed out
```

같은 시점의 TB1 `/cmd_vel`은 0이었으므로 로봇은 안전했지만, 웹 명령 성공을 확인할
수 없는 상태였다.

## 처음 세운 가설

1. TB1의 `safety_watchdog` 서비스 서버가 죽었다.
2. Gateway가 잘못된 서비스 이름을 사용했다.
3. 두 호스트의 시각 차이 때문에 Zenoh 응답이 폐기됐다.
4. Fast DDS와 CycloneDDS 혼용에서 서비스 식별자가 호환되지 않았다.

## 증거와 판단

### 서비스 서버 자체는 정상

TB1에서 직접 호출하면 적용과 해제가 모두 성공했다.

```text
Emergency stop activated
Emergency stop released; waiting for a neutral command
```

따라서 watchdog 로직과 서비스 이름은 원인이 아니었다.

### 시각 차이는 실제 문제였지만 최종 원인은 아니었다

초기 Zenoh 로그에는 WSL에서 온 timestamp가 TB1보다 약 1.6초 앞서 500ms 허용 범위를
넘었다는 오류가 있었다. WSL에서 `hwclock -s`로 시계를 다시 맞추고 관제 브리지를
재시작하자 timestamp 오류는 사라졌다. 하지만 서비스 query는 여전히 5초 뒤
`Timeout` 응답을 반환했다.

즉 시각 드리프트는 반드시 고쳐야 하는 별도 장애였지만, 서비스 시간 초과의 최종
원인은 아니었다.

### 서비스 query가 로봇 브리지에서 끝나지 않았다

관제 브리지의 debug 로그는 다음 사실을 보여 줬다.

- TB1의 `/safety_watchdog/set_estop` 서버를 발견했다.
- WSL Gateway의 service client를 발견했다.
- 로컬 DDS request를 Zenoh query로 변환했다.
- 원격 브리지가 5초 후 `Timeout`을 반환했다.

발견과 라우팅 생성까지는 성공했지만, TB1의 서비스 응답을 Zenoh reply로 바꾸는
구간이 끝나지 않은 것이다.

## 근본 원인

TB1의 ROS 노드는 기본 Fast DDS로 실행됐고, `zenoh-bridge-ros2dds`는 CycloneDDS
기반이었다. 일반 토픽은 DDS 표준 상호 운용으로 통과했지만 ROS 2 서비스의
request/reply 식별자 처리에서는 이 조합이 안정적으로 동작하지 않았다.

공식 Zenoh ROS 2 DDS 브리지는 CycloneDDS를 사용하며
`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` 조합으로 검증되어 있다. TB1의
`safety_watchdog`을 CycloneDDS RMW로 재시작하고 브리지를 다시 연결하자 같은 웹
요청이 즉시 성공했다.

## 해결

TB1에 CycloneDDS RMW를 설치했다.

```bash
sudo apt-get install -y ros-humble-rmw-cyclonedds-cpp
```

ROS 노드를 다음 환경으로 실행했다.

```bash
export ROS_DISTRO=humble
export ROS_DOMAIN_ID=42
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

로봇 브리지에도 `ROS_DISTRO=humble`과 `ROS_DOMAIN_ID=42`를 명시했다. 이 설정은
systemd 사용자 서비스에 고정해 재부팅 후에도 같은 조합을 사용한다.

## 해결 후 검증

웹 비상정지 적용 결과:

```json
{
  "success": true,
  "robot_id": "tb1",
  "engaged": true,
  "message": "Emergency stop activated"
}
```

TB1의 실제 안전 출력:

```text
linear.x: 0.0
angular.z: 0.0
```

추가로 로봇 브리지를 중단했을 때 Gateway는 3초 timeout 뒤 `online=false`로 바뀌고,
오프라인 상태의 비상정지 해제를 HTTP 409로 거부했다. 브리지 복구 후에는 다시
온라인이 되었고, 해제 뒤 중립 명령을 받아 안전하게 재무장했다.

## 실무 교훈

- 토픽 성공만으로 서비스와 액션도 성공한다고 판단하면 안 된다.
- 분산 시스템에서는 양쪽 시각 동기화도 통신 전제조건이다.
- DDS 구현의 표준 토픽 상호 운용과 ROS 2 서비스의 완전한 호환성은 별개다.
- 공식 검증 조합을 기준선으로 두고 다른 조합은 통합 테스트로 증명해야 한다.
- 웹 버튼 비활성화만 믿지 말고 서버도 오프라인 해제를 거부해야 한다.
