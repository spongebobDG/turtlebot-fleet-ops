"""ROS 2 node that aggregates robot and host state for fleet consumers."""

import math
import socket
import time
from typing import Optional, Tuple

from builtin_interfaces.msg import Time as TimeMessage
from fleet_interfaces.msg import RobotStatus
from nav_msgs.msg import Odometry
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import BatteryState, LaserScan

from robot_agent.model import (
    CLEARANCE_BLOCKED,
    CLEARANCE_CLEARED,
    HealthInput,
    HealthThresholds,
    UNKNOWN_VALUE,
    all_finite,
    clearance_transition,
    evaluate_health,
    finite_or_unknown,
    normalize_battery_percent,
    quaternion_to_yaw,
    scan_statistics,
    source_freshness,
)
from robot_agent.system_metrics import sample_system_metrics


class RobotAgent(Node):
    """Publish a structured, freshness-aware status for one robot."""

    def __init__(self, **node_kwargs) -> None:
        super().__init__("robot_agent", **node_kwargs)

        self._declare_parameters()
        self._load_parameters()

        self._last_battery_at: Optional[float] = None
        self._battery_last_received = TimeMessage()
        self._battery_percent = UNKNOWN_VALUE
        self._battery_voltage = UNKNOWN_VALUE
        self._battery_present = False
        self._battery_valid = False

        self._last_odom_at: Optional[float] = None
        self._odom_last_received = TimeMessage()
        self._odom_values = (
            UNKNOWN_VALUE,
            UNKNOWN_VALUE,
            UNKNOWN_VALUE,
            UNKNOWN_VALUE,
            UNKNOWN_VALUE,
        )
        self._odom_valid = False

        self._last_scan_at: Optional[float] = None
        self._scan_last_received = TimeMessage()
        self._scan_valid_points = 0
        self._scan_min_range = UNKNOWN_VALUE
        self._scan_valid = False
        self._clearance_warning_active = False
        self._clearance_recovery_count = 0

        self._last_health: Optional[Tuple[int, Tuple[str, ...]]] = None

        self._publisher = self.create_publisher(
            RobotStatus,
            self._status_topic,
            10,
        )
        self._battery_subscription = self.create_subscription(
            BatteryState,
            self._battery_topic,
            self._on_battery,
            10,
        )
        self._odom_subscription = self.create_subscription(
            Odometry,
            self._odom_topic,
            self._on_odom,
            10,
        )
        self._scan_subscription = self.create_subscription(
            LaserScan,
            self._scan_topic,
            self._on_scan,
            qos_profile_sensor_data,
        )
        self._timer = self.create_timer(
            1.0 / self._publish_rate_hz,
            self._publish_status,
        )

        self.get_logger().info(
            "Robot Agent ready: "
            f"robot_id={self._robot_id}, output={self._status_topic}, "
            f"rate={self._publish_rate_hz:.2f}Hz"
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter("robot_id", "tb1")
        self.declare_parameter("status_topic", "/fleet/robot_status")
        self.declare_parameter("battery_topic", "/battery_state")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("publish_rate_hz", 1.0)
        self.declare_parameter("battery_timeout_sec", 5.0)
        self.declare_parameter("odom_timeout_sec", 1.0)
        self.declare_parameter("scan_timeout_sec", 2.0)
        self.declare_parameter("navigation_min_clearance_m", 0.19)
        self.declare_parameter("clearance_log_hysteresis_m", 0.02)
        self.declare_parameter("clearance_recovery_samples", 3)
        self.declare_parameter("low_battery_percent", 20.0)
        self.declare_parameter("high_cpu_percent", 90.0)
        self.declare_parameter("high_memory_percent", 90.0)
        self.declare_parameter("high_disk_percent", 90.0)

    def _load_parameters(self) -> None:
        self._robot_id = self._string_parameter("robot_id")
        self._status_topic = self._string_parameter("status_topic")
        self._battery_topic = self._string_parameter("battery_topic")
        self._odom_topic = self._string_parameter("odom_topic")
        self._scan_topic = self._string_parameter("scan_topic")
        self._publish_rate_hz = self._positive_float_parameter(
            "publish_rate_hz"
        )
        self._battery_timeout_sec = self._positive_float_parameter(
            "battery_timeout_sec"
        )
        self._odom_timeout_sec = self._positive_float_parameter(
            "odom_timeout_sec"
        )
        self._scan_timeout_sec = self._positive_float_parameter(
            "scan_timeout_sec"
        )
        self._navigation_min_clearance_m = self._positive_float_parameter(
            "navigation_min_clearance_m"
        )
        self._clearance_log_hysteresis_m = self._nonnegative_float_parameter(
            "clearance_log_hysteresis_m"
        )
        self._clearance_recovery_samples = self._positive_int_parameter(
            "clearance_recovery_samples"
        )
        self._thresholds = HealthThresholds(
            low_battery_percent=float(
                self.get_parameter("low_battery_percent").value
            ),
            high_cpu_percent=float(
                self.get_parameter("high_cpu_percent").value
            ),
            high_memory_percent=float(
                self.get_parameter("high_memory_percent").value
            ),
            high_disk_percent=float(
                self.get_parameter("high_disk_percent").value
            ),
        )

    def _string_parameter(self, name: str) -> str:
        value = self.get_parameter(name).value
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        return value.strip()

    def _positive_float_parameter(self, name: str) -> float:
        value = float(self.get_parameter(name).value)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be a positive finite value")
        return value

    def _nonnegative_float_parameter(self, name: str) -> float:
        value = float(self.get_parameter(name).value)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{name} must be a non-negative finite value")
        return value

    def _positive_int_parameter(self, name: str) -> int:
        value = self.get_parameter(name).value
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
        return value

    def _on_battery(self, message: BatteryState) -> None:
        self._last_battery_at = time.monotonic()
        self._battery_last_received = self.get_clock().now().to_msg()
        self._battery_percent = normalize_battery_percent(
            float(message.percentage)
        )
        voltage = finite_or_unknown(float(message.voltage))
        self._battery_voltage = voltage if voltage >= 0.0 else UNKNOWN_VALUE
        self._battery_present = bool(message.present)
        self._battery_valid = self._battery_present and (
            self._battery_percent >= 0.0 or self._battery_voltage >= 0.0
        )

    def _on_odom(self, message: Odometry) -> None:
        self._last_odom_at = time.monotonic()
        self._odom_last_received = self.get_clock().now().to_msg()
        pose = message.pose.pose
        twist = message.twist.twist
        yaw, quaternion_valid = quaternion_to_yaw(
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        )
        raw_values = (
            float(pose.position.x),
            float(pose.position.y),
            float(twist.linear.x),
            float(twist.angular.z),
        )
        self._odom_valid = quaternion_valid and all_finite(raw_values)
        if self._odom_valid:
            self._odom_values = (
                raw_values[0],
                raw_values[1],
                yaw,
                raw_values[2],
                raw_values[3],
            )
        else:
            self._odom_values = (
                UNKNOWN_VALUE,
                UNKNOWN_VALUE,
                UNKNOWN_VALUE,
                UNKNOWN_VALUE,
                UNKNOWN_VALUE,
            )

    def _on_scan(self, message: LaserScan) -> None:
        self._last_scan_at = time.monotonic()
        self._scan_last_received = self.get_clock().now().to_msg()
        count, nearest = scan_statistics(
            message.ranges,
            float(message.range_min),
            float(message.range_max),
        )
        self._scan_valid_points = count
        self._scan_min_range = nearest
        self._scan_valid = count > 0
        self._log_clearance_transition()

    def _log_clearance_transition(self) -> None:
        active, recovery_count, transition = clearance_transition(
            self._clearance_warning_active,
            self._scan_valid,
            float(self._scan_min_range),
            self._navigation_min_clearance_m,
            self._clearance_log_hysteresis_m,
            self._clearance_recovery_count,
            self._clearance_recovery_samples,
        )
        self._clearance_warning_active = active
        self._clearance_recovery_count = recovery_count
        if transition == CLEARANCE_BLOCKED:
            self.get_logger().warning(
                "OBSTACLE_CLEARANCE state=BLOCKED "
                f"nearest={self._scan_min_range:.3f}m "
                f"limit={self._navigation_min_clearance_m:.3f}m"
            )
        elif transition == CLEARANCE_CLEARED:
            self.get_logger().info(
                "OBSTACLE_CLEARANCE state=CLEARED "
                f"nearest={self._scan_min_range:.3f}m "
                f"recovery_limit="
                f"{self._navigation_min_clearance_m + self._clearance_log_hysteresis_m:.3f}m"
            )

    def _publish_status(self) -> None:
        now = time.monotonic()
        battery = source_freshness(
            self._last_battery_at,
            now,
            self._battery_timeout_sec,
        )
        odom = source_freshness(
            self._last_odom_at,
            now,
            self._odom_timeout_sec,
        )
        scan = source_freshness(
            self._last_scan_at,
            now,
            self._scan_timeout_sec,
        )
        system = sample_system_metrics()
        health = evaluate_health(
            HealthInput(
                battery=battery,
                battery_valid=self._battery_valid,
                battery_percent=self._battery_percent,
                odom=odom,
                odom_valid=self._odom_valid,
                scan=scan,
                scan_valid=self._scan_valid,
                cpu_percent=system.cpu_percent,
                memory_percent=system.memory_percent,
                disk_percent=system.disk_percent,
            ),
            self._thresholds,
        )

        message = RobotStatus()
        message.header.stamp = self.get_clock().now().to_msg()
        message.robot_id = self._robot_id
        message.hostname = socket.gethostname()
        message.level = health.level

        message.battery_received = battery.received
        message.battery_fresh = battery.fresh
        message.battery_valid = self._battery_valid
        message.battery_last_received = self._battery_last_received
        message.battery_age_sec = battery.age_sec
        message.battery_percent = self._battery_percent
        message.battery_voltage = self._battery_voltage
        message.battery_present = self._battery_present

        message.odom_received = odom.received
        message.odom_fresh = odom.fresh
        message.odom_valid = self._odom_valid
        message.odom_last_received = self._odom_last_received
        message.odom_age_sec = odom.age_sec
        (
            message.position_x,
            message.position_y,
            message.yaw,
            message.linear_velocity,
            message.angular_velocity,
        ) = self._odom_values

        message.scan_received = scan.received
        message.scan_fresh = scan.fresh
        message.scan_valid = self._scan_valid
        message.scan_last_received = self._scan_last_received
        message.scan_age_sec = scan.age_sec
        message.scan_valid_points = self._scan_valid_points
        message.scan_min_range = self._scan_min_range

        message.cpu_percent = system.cpu_percent
        message.memory_percent = system.memory_percent
        message.disk_percent = system.disk_percent
        message.load_average_1m = system.load_average_1m
        message.uptime_sec = system.uptime_sec
        message.wifi_valid = system.wifi_valid
        message.wifi_interface = system.wifi_interface
        message.wifi_signal_dbm = system.wifi_signal_dbm
        message.wifi_quality_percent = system.wifi_quality_percent
        message.fault_codes = list(health.fault_codes)

        self._publisher.publish(message)
        self._log_health_transition(health.level, health.fault_codes)

    def _log_health_transition(
        self,
        level: int,
        fault_codes: Tuple[str, ...],
    ) -> None:
        current = (level, fault_codes)
        if current == self._last_health:
            return
        self._last_health = current
        if not fault_codes:
            self.get_logger().info("Robot health OK")
            return
        message = f"Robot health level={level}: {', '.join(fault_codes)}"
        if level == RobotStatus.LEVEL_ERROR:
            self.get_logger().error(message)
        else:
            self.get_logger().warning(message)


def main(args=None) -> None:
    """Run the Robot Agent until shutdown."""
    rclpy.init(args=args)
    node: Optional[RobotAgent] = None
    try:
        node = RobotAgent()
        rclpy.spin(node)
    except (ExternalShutdownException, KeyboardInterrupt):
        pass
    finally:
        try:
            if node is not None:
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except (ExternalShutdownException, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    main()
