# fleet_interfaces

ROS 2 nodes and the future fleet gateway share message contracts from this
package. Keeping interfaces separate from executable nodes lets consumers
depend on the schema without importing robot-side implementation code.

## RobotStatus

`RobotStatus` is the Phase 3 snapshot published by each Robot Agent. It contains
robot identity, source freshness, battery, planar odometry, LiDAR summary,
source receipt timestamps, system and Wi-Fi resources, health level, and stable
fault codes.

Unknown numeric values use `-1.0` instead of NaN so a later JSON gateway can
serialize the status without non-standard floating-point values.

## Phase 5 navigation contracts

- `NavigateRobot.action`: Gateway command ID와 map pose를 Nav2 결과·feedback에 연결한다.
- `NavigationLease.msg`: robot ID와 command ID가 일치하는 원격 소유권 heartbeat다.
- `NavigationStatus.msg`: 준비 상태, active target, 위치·거리·시간·recovery와 lease age다.
- `SafetyStatus.msg`: watchdog mode, e-stop과 중립 재무장 상태다.
- `SetInitialPose.srv`: covariance를 포함한 map-frame 초기 위치를 적용한다.
- `SetMotionMode.srv`: arbiter를 IDLE, MANUAL 또는 NAVIGATION으로 전환한다.

fleet topic은 `robot_id`로 구분하고 TB1 action/service는 `/tb1/navigation/...` 이름을
사용한다. 상세 책임과 timeout은
[Phase 5 설계](../../docs/design/phase-5-tb1-navigation.md)에 정의한다.
