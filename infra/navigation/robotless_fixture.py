#!/usr/bin/env python3
"""Provide a lightweight TB1 fixture for headless Nav2 smoke tests."""

import json
import math
import os
from pathlib import Path
import time

from fleet_interfaces.msg import RobotStatus
from geometry_msgs.msg import (
    PoseWithCovarianceStamped,
    TransformStamped,
    Twist,
)
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster


TB1_RAW_SCAN_YAW_OFFSET_RAD = math.pi


def _yaw_from_quaternion(z_value: float, w_value: float) -> float:
    """Return planar yaw from a normalized-or-normalizable quaternion."""
    norm = math.hypot(z_value, w_value)
    if norm <= 1.0e-12:
        return 0.0
    z_value /= norm
    w_value /= norm
    return math.atan2(
        2.0 * w_value * z_value,
        1.0 - 2.0 * z_value * z_value,
    )


def _square_room_scan_ranges(
    x_value: float,
    y_value: float,
    yaw: float,
    sample_count: int = 360,
    wall_coordinate: float = 1.975,
    sensor_yaw_rad: float = TB1_RAW_SCAN_YAW_OFFSET_RAD,
) -> list:
    """Ray-cast raw TB1 scan angles against the fixture map boundary."""
    ranges = []
    increment = 2.0 * math.pi / max(1, sample_count - 1)
    for index in range(sample_count):
        angle = yaw - math.pi + index * increment + sensor_yaw_rad
        direction_x = math.cos(angle)
        direction_y = math.sin(angle)
        candidates = []
        if abs(direction_x) > 1.0e-12:
            wall_x = wall_coordinate if direction_x > 0.0 else -wall_coordinate
            candidates.append((wall_x - x_value) / direction_x)
        if abs(direction_y) > 1.0e-12:
            wall_y = wall_coordinate if direction_y > 0.0 else -wall_coordinate
            candidates.append((wall_y - y_value) / direction_y)
        ranges.append(min(value for value in candidates if value > 0.0))
    return ranges


class RobotlessFixture(Node):
    """Integrate safe velocity output and publish the minimum TB1 sensors."""

    def __init__(self) -> None:
        super().__init__("robotless_tb1_fixture")
        self._x = 0.0
        self._y = 0.0
        self._yaw = 0.0
        self._linear = 0.0
        self._angular = 0.0
        self._max_linear = 0.0
        self._max_angular = 0.0
        self._nonzero_commands = 0
        self._last_update = time.monotonic()
        self._telemetry_path = Path(
            os.environ["ROBOTLESS_TELEMETRY_FILE"]
        )

        self._odom_publisher = self.create_publisher(Odometry, "/odom", 10)
        self._scan_publisher = self.create_publisher(LaserScan, "/scan", 10)
        self._amcl_publisher = self.create_publisher(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            10,
        )
        self._status_publisher = self.create_publisher(
            RobotStatus,
            "/fleet/robot_status",
            10,
        )
        self.create_subscription(Twist, "/cmd_vel", self._on_command, 10)
        self.create_subscription(
            PoseWithCovarianceStamped,
            "/initialpose",
            self._on_initial_pose,
            10,
        )
        self._transform_broadcaster = TransformBroadcaster(self)
        self._static_broadcaster = StaticTransformBroadcaster(self)
        self._publish_static_transforms()
        self.create_timer(0.05, self._tick)

    def _publish_static_transforms(self) -> None:
        stamp = self.get_clock().now().to_msg()
        map_to_odom = TransformStamped()
        map_to_odom.header.stamp = stamp
        map_to_odom.header.frame_id = "map"
        map_to_odom.child_frame_id = "odom"
        map_to_odom.transform.rotation.w = 1.0

        footprint_to_base = TransformStamped()
        footprint_to_base.header.stamp = stamp
        footprint_to_base.header.frame_id = "base_footprint"
        footprint_to_base.child_frame_id = "base_link"
        footprint_to_base.transform.translation.z = 0.01
        footprint_to_base.transform.rotation.w = 1.0

        base_to_scan = TransformStamped()
        base_to_scan.header.stamp = stamp
        base_to_scan.header.frame_id = "base_link"
        base_to_scan.child_frame_id = "base_scan"
        base_to_scan.transform.translation.z = 0.12
        base_to_scan.transform.rotation.w = 1.0
        self._static_broadcaster.sendTransform(
            [map_to_odom, footprint_to_base, base_to_scan]
        )

    def _on_command(self, message: Twist) -> None:
        self._linear = float(message.linear.x)
        self._angular = float(message.angular.z)
        self._max_linear = max(self._max_linear, abs(self._linear))
        self._max_angular = max(self._max_angular, abs(self._angular))
        if abs(self._linear) > 1.0e-4 or abs(self._angular) > 1.0e-4:
            self._nonzero_commands += 1

    def _on_initial_pose(self, message: PoseWithCovarianceStamped) -> None:
        if message.header.frame_id not in ("", "map"):
            return
        self._x = float(message.pose.pose.position.x)
        self._y = float(message.pose.pose.position.y)
        self._yaw = _yaw_from_quaternion(
            float(message.pose.pose.orientation.z),
            float(message.pose.pose.orientation.w),
        )

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = min(max(now - self._last_update, 0.0), 0.1)
        self._last_update = now
        self._x += self._linear * math.cos(self._yaw) * elapsed
        self._y += self._linear * math.sin(self._yaw) * elapsed
        self._yaw += self._angular * elapsed
        stamp = self.get_clock().now().to_msg()
        sin_half = math.sin(self._yaw / 2.0)
        cos_half = math.cos(self._yaw / 2.0)

        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = "odom"
        transform.child_frame_id = "base_footprint"
        transform.transform.translation.x = self._x
        transform.transform.translation.y = self._y
        transform.transform.rotation.z = sin_half
        transform.transform.rotation.w = cos_half
        self._transform_broadcaster.sendTransform(transform)

        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_footprint"
        odom.pose.pose.position.x = self._x
        odom.pose.pose.position.y = self._y
        odom.pose.pose.orientation.z = sin_half
        odom.pose.pose.orientation.w = cos_half
        odom.twist.twist.linear.x = self._linear
        odom.twist.twist.angular.z = self._angular
        self._odom_publisher.publish(odom)

        scan = LaserScan()
        scan.header.stamp = stamp
        scan.header.frame_id = "base_scan"
        scan.angle_min = -math.pi
        scan.angle_max = math.pi
        scan.angle_increment = 2.0 * math.pi / 359.0
        scan.scan_time = 0.05
        scan.range_min = 0.12
        scan.range_max = 3.5
        scan.ranges = _square_room_scan_ranges(
            self._x,
            self._y,
            self._yaw,
        )
        self._scan_publisher.publish(scan)

        amcl = PoseWithCovarianceStamped()
        amcl.header.stamp = stamp
        amcl.header.frame_id = "map"
        amcl.pose.pose.position.x = self._x
        amcl.pose.pose.position.y = self._y
        amcl.pose.pose.orientation.z = sin_half
        amcl.pose.pose.orientation.w = cos_half
        amcl.pose.covariance[0] = 0.01
        amcl.pose.covariance[7] = 0.01
        amcl.pose.covariance[35] = 0.01
        self._amcl_publisher.publish(amcl)

        status = RobotStatus()
        status.header.stamp = stamp
        status.robot_id = "tb1"
        status.hostname = "robotless-fixture"
        status.level = RobotStatus.LEVEL_OK
        status.battery_received = True
        status.battery_fresh = True
        status.battery_valid = True
        status.battery_percent = 80.0
        status.battery_voltage = 11.8
        status.battery_present = True
        status.odom_received = True
        status.odom_fresh = True
        status.odom_valid = True
        status.position_x = self._x
        status.position_y = self._y
        status.yaw = self._yaw
        status.linear_velocity = self._linear
        status.angular_velocity = self._angular
        status.scan_received = True
        status.scan_fresh = True
        status.scan_valid = True
        status.scan_valid_points = 360
        status.scan_min_range = min(scan.ranges)
        status.cpu_percent = 10.0
        status.memory_percent = 20.0
        self._status_publisher.publish(status)
        self._write_telemetry()

    def _write_telemetry(self) -> None:
        payload = {
            "x": self._x,
            "y": self._y,
            "yaw": self._yaw,
            "current_linear": self._linear,
            "current_angular": self._angular,
            "max_abs_linear": self._max_linear,
            "max_abs_angular": self._max_angular,
            "nonzero_commands": self._nonzero_commands,
        }
        self._telemetry_path.write_text(
            json.dumps(payload, sort_keys=True),
            encoding="utf-8",
        )


def main() -> None:
    """Run the robotless fixture until the smoke-test shell stops it."""
    rclpy.init()
    node = RobotlessFixture()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
