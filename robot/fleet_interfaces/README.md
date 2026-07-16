# fleet_interfaces

ROS 2 nodes and the future fleet gateway share message contracts from this
package. Keeping interfaces separate from executable nodes lets consumers
depend on the schema without importing robot-side implementation code.

## RobotStatus

`RobotStatus` is the Phase 3 snapshot published by each Robot Agent. It contains
robot identity, source freshness, battery, planar odometry, LiDAR summary,
system resources, health level, and stable fault codes.

Unknown numeric values use `-1.0` instead of NaN so a later JSON gateway can
serialize the status without non-standard floating-point values.
