# robot_agent

`robot_agent` subscribes to the robot's battery, odometry, and LiDAR topics,
adds Raspberry Pi resource metrics, evaluates source freshness, and publishes a
single `fleet_interfaces/msg/RobotStatus` snapshot.

## Default data path

```text
/battery_state ─┐
/odom ──────────┼─> robot_agent ─> /fleet/robot_status
/scan ──────────┤
Linux resources ┘
```

Host resources include CPU, memory, disk, load, uptime, and Linux wireless
interface signal. Each ROS source exposes both a wall/ROS receipt timestamp and
a monotonic age used for timeout decisions.

The future fleet gateway can determine robot connectivity from the age of this
1 Hz status heartbeat. The Robot Agent does not publish an `online=true` claim
about itself because a stopped process cannot publish `online=false`.

## Build and run

```bash
source /opt/ros/humble/setup.bash

colcon build \
  --base-paths robot \
  --packages-up-to robot_agent \
  --symlink-install

source install/setup.bash
ros2 launch robot_agent robot_agent.launch.py
```

Inspect one status:

```bash
ros2 topic echo /fleet/robot_status --once
```

The TB1 configuration is checked in at `config/tb1.yaml`. Robot-specific values
remain parameters so TB2 can reuse the same code later.

## Health policy

- Missing, invalid, or stale odometry and scan data produce `LEVEL_ERROR`.
- Battery availability, validity, freshness, and low charge produce warnings.
- CPU, memory, or disk usage at the configured thresholds produce warnings.
- Fault codes are stable identifiers intended for dashboards and alert rules.

This status is observability data, not a certified safety controller. Motion
stopping remains the responsibility of the independent safety watchdog and
lower hardware layers.
