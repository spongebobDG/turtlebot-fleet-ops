# 학습 일지: TB2 무동작 부트스트랩과 격리 테스트

날짜: 2026-07-16
단계: 다중 로봇 준비 - TB2 개발 환경 배포
진행 상태: 프로젝트 clone·빌드·로봇 패키지 133개 테스트 완료, 실차 런타임 미시작

## 목표

- 기존 SSH 호스트 키를 검증한 뒤 TB2에 비대화형으로 접속한다.
- 하드웨어 bringup이나 모터 명령 없이 개발 환경과 소스 revision을 확인한다.
- 현재 기능 브랜치를 배포하고 로봇 패키지를 빌드·테스트한다.
- TB1과 동일한 Cyclone DDS 실행 기반을 설치한다.

## SSH 호스트 키 검증

TB2의 hostname 해석이 일시적으로 실패해 이전 주소로 접속했을 때 비대화형 SSH가
`Host key verification failed`로 중단됐다. 키 검사를 끄거나 새 키를 무조건 등록하지 않고
verbose handshake에서 서버의 ED25519 fingerprint가 기존 `tb2` 항목과 같은지 비교했다.
같은 키임을 확인한 뒤 `HostKeyAlias=tb2`로 기존 hostname 키를 재사용했다.

정확한 주소는 저장소에 기록하지 않는다. 중요한 것은 주소가 아니라 신뢰한 장비의 호스트
키와 현재 장비가 제시한 키가 같다는 검증이다.

## 환경 감사

```text
hostname: tb2
architecture: aarch64
OS: Ubuntu 22.04.5 LTS
memory: 3.7GiB
root filesystem: 15G total, 8.6G available
ROS: Humble
OpenCR: /dev/ttyACM0 present
LDS-02 adapter: /dev/ttyUSB0 present
user groups: dialout included
running robot services: none
serial owners: none
```

`~/turtlebot3_ws`에는 TB1과 같은 TurtleBot3 및 LDS-02 소스 revision이 있었고 overlay를
source한 뒤 다음 패키지를 모두 찾을 수 있었다.

```text
turtlebot3 source: 90a68bd
ld08_driver source: 4c52869
turtlebot3_bringup: OK
turtlebot3_node: OK
turtlebot3_teleop: OK
ld08_driver: OK
```

처음 ROS 패키지가 missing으로 보인 것은 설치 실패가 아니라 현재 audit 셸에서
`~/turtlebot3_ws/install/setup.bash`를 아직 source하지 않았기 때문이다.

## 프로젝트 배포와 첫 실패

현재 기능 브랜치를 `~/turtlebot-fleet-ops`에 clone하고 `robot` 아래 4개 패키지를 모두
빌드했다. 빌드는 성공했지만 첫 테스트는 Cyclone DDS RMW가 설치되지 않아 ROS 노드를 만들기
전에 종료됐다.

```text
build: 4 packages passed
first test: failed before node creation
cause: librmw_cyclonedds_cpp.so missing
```

TB1 운영 서비스와 guard는 Cyclone DDS를 명시하므로 TB2에도
`ros-humble-rmw-cyclonedds-cpp`를 설치했다. Ubuntu mirror의 IPv6·일부 IPv4 연결이
일시적으로 실패했지만 source를 임의 mirror로 바꾸지 않고 공식 mirror의 IPv4 연결을
확인한 뒤 apt에 `Acquire::ForceIPv4=true`와 재시도를 적용해 완료했다.

## 잘못된 격리 도메인 242

RMW 설치 후 테스트 도메인을 242로 지정하자 Cyclone DDS가 다음 이유로 노드를 만들지 못했다.

```text
Failed to create discovery multicast socket for domain 242
resulting port number 67900 is out of range
```

DDS discovery 포트는 domain ID가 커질수록 증가하므로 `0~255`처럼 보이는 모든 값이 실제
UDP 포트 범위에서 유효한 것은 아니다. 프로젝트에서 이미 검증한 격리 도메인 142로
재실행했다. 첫 ROS 초기화가 실패한 뒤 이어진 `Context.init() must only be called once`들은
별도 코드 결함이 아니라 같은 pytest 프로세스에 남은 초기화 실패의 연쇄 결과였다.

## 최종 테스트 결과

```text
ROS_DOMAIN_ID=142
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
fleet_interfaces: build passed
safety_watchdog: 18 passed
robot_agent: 33 passed
fleet_navigation: 82 passed
robot packages total: 133 tests, 0 errors, 0 failures, 0 skipped
deployed commit: f8c144b
robot runtime processes: none
OpenCR/LDS-02 serial owners: none
```

CI의 전체 146개는 control PC용 `fleet_gateway` 13개까지 포함한다. TB2에서는 `robot` 경로만
테스트했으므로 133개가 정확한 기대값이다.

## 오늘 꼭 기억해야 할 것

1. **SSH 키 오류가 나면 `StrictHostKeyChecking=no`부터 쓰지 말고 fingerprint를 비교한다.**
2. **ROS overlay를 source하지 않은 package missing과 실제 미설치를 구분한다.**
3. **모든 ROS domain ID가 DDS UDP 포트 범위에서 유효한 것은 아니다.**
4. **첫 원인 실패 뒤의 연쇄 오류를 각각 독립 결함으로 세지 않는다.**
5. **두 번째 로봇 배포는 빌드·테스트와 실차 런타임 시작을 분리한다.**
6. **TB2 런타임은 watchdog을 먼저 올리고 e-stop 상태를 확인한 뒤 bringup을 시작한다.**

## 면접에서는 이렇게 설명한다

> 두 번째 로봇을 추가할 때 첫 로봇의 명령을 그대로 복사해 바로 bringup하지 않았습니다.
> SSH 호스트 키, 하드웨어 장치, overlay revision, 통신 RMW를 무동작 상태에서 먼저 감사했습니다.
> 프로젝트 4개 패키지는 빌드됐지만 Cyclone DDS 누락을 발견해 TB1과 같은 RMW를 설치했고,
> domain 242가 계산 포트 67900을 만들어 실패한 문제는 유효한 격리 domain 142로 교정했습니다.
> 최종적으로 로봇 패키지 133개 테스트를 통과했고 serial owner가 없는 상태에서 종료했습니다.

## 복습 문제와 정답

### 1. 주소가 같은데 SSH 호스트 키 검증이 실패하면 어떻게 해야 하는가?

정답: 키 검사를 끄지 않는다. 기존에 신뢰한 hostname 키와 서버가 현재 제시한 fingerprint,
네트워크 장비 식별 정보를 비교한다. 일치가 확인되면 HostKeyAlias처럼 기존 신뢰 항목을
사용하고, 불일치하면 콘솔에서 서버 키를 확인하기 전까지 접속하지 않는다.

### 2. `/opt/ros/humble`을 source했는데 TurtleBot3 패키지가 missing인 이유는 무엇인가?

정답: TurtleBot3가 apt가 아닌 `~/turtlebot3_ws` overlay에 빌드돼 있기 때문이다. underlay인
Humble 뒤에 overlay의 `install/setup.bash`도 source해야 한다.

### 3. domain 242 실패 뒤 여러 테스트에서 rclpy Context 오류가 나온 이유는 무엇인가?

정답: 첫 테스트가 유효하지 않은 DDS 포트로 ROS context 초기화 중 실패했고 정리되지 않은
상태가 같은 프로세스에 남았다. 후속 오류 수보다 최초의 DDS 포트 오류를 먼저 해결해야 한다.

### 4. TB2 테스트가 133개이고 CI가 146개인 것은 누락인가?

정답: 아니다. TB2는 `robot`의 safety watchdog 18개, robot agent 33개, navigation 82개를
실행해 총 133개다. CI는 control의 fleet gateway 13개를 더 실행해 146개다.

## 다음 단계

- TB1 새 SLAM 설정의 두 번째 그래프 노드 검증을 마친다.
- Phase 5 PR을 완료한 뒤 별도 다중 로봇 브랜치에서 TB2용 `robot_id`, 서비스와 namespace
  설정을 추가한다.
- TB2에서는 watchdog을 먼저 시작하고 e-stop·0속도를 확인한 뒤 OpenCR firmware와 bringup을
  각각 별도 acceptance gate로 검증한다.
- 사용자의 현장 안전 확인 전에는 TB2 모터 이동을 실행하지 않는다.
