"""ROS graph integration test for the structured RobotStatus output."""

import math
import time
from typing import Callable, List

from fleet_interfaces.msg import RobotStatus
from nav_msgs.msg import Odometry
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import BatteryState, LaserScan

from robot_agent.node import RobotAgent


def _spin_until(
    executor: SingleThreadedExecutor,
    condition: Callable[[], bool],
    timeout_sec: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
        if condition():
            return
    raise AssertionError("condition was not met before timeout")


def test_robot_agent_ros_flow() -> None:
    rclpy.init()
    agent = RobotAgent(
        parameter_overrides=[
            Parameter("robot_id", value="test_robot"),
            Parameter("status_topic", value="/test/fleet/status"),
            Parameter("battery_topic", value="/test/battery"),
            Parameter("odom_topic", value="/test/odom"),
            Parameter("scan_topic", value="/test/scan"),
            Parameter("publish_rate_hz", value=20.0),
            Parameter("battery_timeout_sec", value=0.3),
            Parameter("odom_timeout_sec", value=0.3),
            Parameter("scan_timeout_sec", value=0.3),
        ]
    )
    probe = Node("robot_agent_test_probe")
    executor = SingleThreadedExecutor()
    outputs: List[RobotStatus] = []

    battery_publisher = probe.create_publisher(
        BatteryState,
        "/test/battery",
        10,
    )
    odom_publisher = probe.create_publisher(
        Odometry,
        "/test/odom",
        10,
    )
    scan_publisher = probe.create_publisher(
        LaserScan,
        "/test/scan",
        qos_profile_sensor_data,
    )
    status_subscription = probe.create_subscription(
        RobotStatus,
        "/test/fleet/status",
        outputs.append,
        10,
    )

    executor.add_node(agent)
    executor.add_node(probe)

    try:
        _spin_until(executor, lambda: len(outputs) > 0)
        assert outputs[-1].level == RobotStatus.LEVEL_ERROR
        assert "ODOM_NOT_RECEIVED" in outputs[-1].fault_codes
        assert "SCAN_NOT_RECEIVED" in outputs[-1].fault_codes

        _spin_until(
            executor,
            lambda: battery_publisher.get_subscription_count() == 1
            and odom_publisher.get_subscription_count() == 1
            and scan_publisher.get_subscription_count() == 1,
        )

        battery = BatteryState()
        battery.percentage = 0.75
        battery.voltage = 12.1
        battery.present = True

        odom = Odometry()
        odom.pose.pose.position.x = 1.5
        odom.pose.pose.position.y = -0.5
        odom.pose.pose.orientation.w = 1.0
        odom.twist.twist.linear.x = 0.03
        odom.twist.twist.angular.z = 0.2

        scan = LaserScan()
        scan.range_min = 0.1
        scan.range_max = 10.0
        scan.ranges = [math.inf, 0.05, 2.0, 0.8, 12.0]

        outputs.clear()
        battery_publisher.publish(battery)
        odom_publisher.publish(odom)
        scan_publisher.publish(scan)

        _spin_until(
            executor,
            lambda: any(
                output.battery_fresh
                and output.odom_fresh
                and output.scan_fresh
                for output in outputs
            ),
        )
        status = next(
            output
            for output in outputs
            if output.battery_fresh
            and output.odom_fresh
            and output.scan_fresh
        )
        assert status.robot_id == "test_robot"
        assert status.hostname
        assert status.level == RobotStatus.LEVEL_OK
        assert status.fault_codes == []
        assert status.battery_percent == pytest.approx(75.0)
        assert status.battery_voltage == pytest.approx(12.1)
        assert status.battery_last_received.sec > 0
        assert status.position_x == pytest.approx(1.5)
        assert status.position_y == pytest.approx(-0.5)
        assert status.yaw == pytest.approx(0.0)
        assert status.odom_last_received.sec > 0
        assert status.scan_valid_points == 2
        assert status.scan_min_range == pytest.approx(0.8)
        assert status.scan_last_received.sec > 0

        _spin_until(
            executor,
            lambda: any("ODOM_STALE" in item.fault_codes for item in outputs),
        )
        stale = next(
            item for item in outputs if "ODOM_STALE" in item.fault_codes
        )
        assert stale.level == RobotStatus.LEVEL_ERROR
        assert "SCAN_STALE" in stale.fault_codes
    finally:
        probe.destroy_subscription(status_subscription)
        executor.remove_node(probe)
        executor.remove_node(agent)
        probe.destroy_node()
        agent.destroy_node()
        executor.shutdown()
        rclpy.shutdown()
