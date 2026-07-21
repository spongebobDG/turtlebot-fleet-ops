"""Normalize variable-angle LDS-02 scans onto a fixed angular grid."""

import math
from typing import Sequence, Tuple

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import LaserScan


DEFAULT_BIN_COUNT = 360
NORMALIZED_SCAN_TOPIC = "/scan_normalized"


def normalize_samples(
    ranges: Sequence[float],
    intensities: Sequence[float],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    bin_count: int = DEFAULT_BIN_COUNT,
    angle_offset_rad: float = 0.0,
) -> Tuple[list, list]:
    """Project scan samples onto fixed bins in the physical base convention."""
    if bin_count < 1:
        raise ValueError("bin_count must be at least 1")
    if angle_increment <= 0.0:
        raise ValueError("angle_increment must be positive")
    if not math.isfinite(angle_offset_rad):
        raise ValueError("angle_offset_rad must be finite")

    output_ranges = [math.inf] * bin_count
    output_intensities = [0.0] * bin_count
    bin_width = math.tau / bin_count

    for sample_index, sample_range in enumerate(ranges):
        if not math.isfinite(sample_range):
            continue
        if sample_range < range_min or sample_range > range_max:
            continue

        angle = angle_min + sample_index * angle_increment
        normalized_angle = (angle + angle_offset_rad) % math.tau
        bin_index = int(normalized_angle / bin_width + 0.5) % bin_count

        if sample_range < output_ranges[bin_index]:
            output_ranges[bin_index] = float(sample_range)
            if sample_index < len(intensities):
                output_intensities[bin_index] = float(
                    intensities[sample_index]
                )

    return output_ranges, output_intensities


class ScanNormalizer(Node):
    """Publish fixed-length scans while preserving the original raw topic."""

    def __init__(self) -> None:
        super().__init__("scan_normalizer")
        self.declare_parameter("input_topic", "/scan")
        self.declare_parameter("output_topic", NORMALIZED_SCAN_TOPIC)
        self.declare_parameter("bin_count", DEFAULT_BIN_COUNT)
        self.declare_parameter("angle_offset_rad", 0.0)
        self.declare_parameter("publish_intensities", True)

        input_topic = str(self.get_parameter("input_topic").value)
        output_topic = str(self.get_parameter("output_topic").value)
        self._bin_count = int(self.get_parameter("bin_count").value)
        self._angle_offset_rad = float(
            self.get_parameter("angle_offset_rad").value
        )
        self._publish_intensities = bool(
            self.get_parameter("publish_intensities").value
        )
        if self._bin_count < 1:
            raise ValueError("bin_count must be at least 1")
        if not math.isfinite(self._angle_offset_rad):
            raise ValueError("angle_offset_rad must be finite")

        output_qos = QoSProfile(
            depth=5,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._publisher = self.create_publisher(
            LaserScan,
            output_topic,
            output_qos,
        )
        self._subscription = self.create_subscription(
            LaserScan,
            input_topic,
            self._on_scan,
            qos_profile_sensor_data,
        )
        self.get_logger().info(
            f"Normalizing {input_topic} to {output_topic} "
            f"with {self._bin_count} bins and "
            f"{self._angle_offset_rad:.6f} rad angle offset"
        )

    def _on_scan(self, message: LaserScan) -> None:
        output = LaserScan()
        output.header = message.header
        output.angle_min = 0.0
        output.angle_increment = math.tau / self._bin_count
        output.angle_max = output.angle_increment * (self._bin_count - 1)
        output.scan_time = message.scan_time
        output.time_increment = (
            message.scan_time / self._bin_count
            if message.scan_time > 0.0
            else 0.0
        )
        output.range_min = message.range_min
        output.range_max = message.range_max
        output.ranges, normalized_intensities = normalize_samples(
            message.ranges,
            message.intensities,
            message.angle_min,
            message.angle_increment,
            message.range_min,
            message.range_max,
            self._bin_count,
            self._angle_offset_rad,
        )
        if self._publish_intensities:
            output.intensities = normalized_intensities
        self._publisher.publish(output)


def main(args=None) -> None:
    """Run the scan normalizer node."""
    rclpy.init(args=args)
    node = ScanNormalizer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if node.context.ok():
                node.destroy_node()
        except (KeyboardInterrupt, RuntimeError):
            # A launch-wide stop may interrupt entity destruction.
            pass
        if rclpy.ok():
            try:
                rclpy.shutdown()
            except RuntimeError:
                # A launch-wide signal may close the context after the check.
                pass
