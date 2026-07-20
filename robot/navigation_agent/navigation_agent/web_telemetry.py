"""Publish compact, reliable web LiDAR and map-pose telemetry."""

import json
import math
import time
from typing import Any, Dict, Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener


def compact_scan_snapshot(
    message: Any,
    sensor_x: float,
    sensor_y: float,
    sensor_yaw: float,
    max_points: int,
) -> Dict[str, Any]:
    """Convert a scan to a bounded JSON-safe set of base-frame points."""
    if max_points < 1:
        raise ValueError("max_points must be positive")
    geometry = (
        float(message.angle_min),
        float(message.angle_max),
        float(message.angle_increment),
        float(message.range_min),
        float(message.range_max),
        float(sensor_x),
        float(sensor_y),
        float(sensor_yaw),
    )
    if not all(math.isfinite(value) for value in geometry):
        raise ValueError("scan geometry and sensor pose must be finite")
    angle_min, angle_max, increment, range_min, range_max = geometry[:5]
    if increment <= 0.0 or range_min < 0.0 or range_max <= range_min:
        raise ValueError("scan geometry is invalid")

    cosine = math.cos(sensor_yaw)
    sine = math.sin(sensor_yaw)
    points = []
    nearest: Optional[float] = None
    for index, raw_range in enumerate(message.ranges):
        distance = float(raw_range)
        if (
            not math.isfinite(distance)
            or distance < range_min
            or distance > range_max
        ):
            continue
        angle = angle_min + index * increment
        local_x = distance * math.cos(angle)
        local_y = distance * math.sin(angle)
        points.append(
            [
                round(sensor_x + cosine * local_x - sine * local_y, 4),
                round(sensor_y + sine * local_x + cosine * local_y, 4),
            ]
        )
        nearest = distance if nearest is None else min(nearest, distance)

    if len(points) > max_points:
        point_count = len(points)
        points = [
            points[min(point_count - 1, index * point_count // max_points)]
            for index in range(max_points)
        ]
    span = max(0.0, min(math.tau, angle_max - angle_min))
    return {
        "frame_id": str(message.header.frame_id),
        "stamp": {
            "sec": int(message.header.stamp.sec),
            "nanosec": int(message.header.stamp.nanosec),
        },
        "sensor_pose": {
            "x": float(sensor_x),
            "y": float(sensor_y),
            "yaw": float(sensor_yaw),
        },
        "angle_span_deg": math.degrees(span),
        "coverage_ratio": span / math.tau,
        "sample_count": len(message.ranges),
        "valid_points": len(points),
        "nearest_range": nearest,
        "points": points,
    }


def transform_snapshot(robot_id: str, message: Any) -> Dict[str, Any]:
    """Convert a map-to-base transform into the web pose contract."""
    rotation = message.transform.rotation
    yaw = 2.0 * math.atan2(float(rotation.z), float(rotation.w))
    translation = message.transform.translation
    return {
        "robot_id": robot_id,
        "frame_id": str(message.header.frame_id),
        "stamp": {
            "sec": int(message.header.stamp.sec),
            "nanosec": int(message.header.stamp.nanosec),
        },
        "x": float(translation.x),
        "y": float(translation.y),
        "yaw": yaw,
    }


def transform_is_fresh(
    message: Any,
    now_sec: float,
    timeout_sec: float,
) -> bool:
    """Reject a cached map transform after its localization source stops."""
    stamp = (
        float(message.header.stamp.sec)
        + float(message.header.stamp.nanosec) / 1_000_000_000.0
    )
    values = (stamp, float(now_sec), float(timeout_sec))
    if not all(math.isfinite(value) for value in values):
        return False
    return timeout_sec > 0.0 and stamp > 0.0 and now_sec - stamp <= timeout_sec


class WebTelemetryNode(Node):
    """Relay web-specific telemetry over a reliable low-bandwidth topic."""

    def __init__(self) -> None:
        super().__init__("web_telemetry")
        self.declare_parameter("robot_id", "tb1")
        self.declare_parameter("scan_topic", "/scan_normalized")
        self.declare_parameter("output_topic", "/fleet/web_telemetry")
        self.declare_parameter("publish_rate_hz", 5.0)
        self.declare_parameter("scan_timeout_sec", 1.0)
        self.declare_parameter("sensor_x_m", -0.032)
        self.declare_parameter("sensor_y_m", 0.0)
        self.declare_parameter("sensor_yaw_rad", 0.0)
        self.declare_parameter("max_points", 120)
        self.declare_parameter("target_frame", "map")
        self.declare_parameter("source_frame", "base_footprint")
        self.declare_parameter("pose_timeout_sec", 1.0)

        self._robot_id = str(self.get_parameter("robot_id").value)
        self._scan_timeout = float(
            self.get_parameter("scan_timeout_sec").value
        )
        self._sensor_x = float(self.get_parameter("sensor_x_m").value)
        self._sensor_y = float(self.get_parameter("sensor_y_m").value)
        self._sensor_yaw = float(
            self.get_parameter("sensor_yaw_rad").value
        )
        self._max_points = int(self.get_parameter("max_points").value)
        self._target_frame = str(self.get_parameter("target_frame").value)
        self._source_frame = str(self.get_parameter("source_frame").value)
        self._pose_timeout = float(
            self.get_parameter("pose_timeout_sec").value
        )
        publish_rate = float(self.get_parameter("publish_rate_hz").value)
        if (
            publish_rate <= 0.0
            or self._scan_timeout <= 0.0
            or self._pose_timeout <= 0.0
        ):
            raise ValueError("telemetry rates and timeouts must be positive")

        reliable_qos = QoSProfile(
            depth=5,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._publisher = self.create_publisher(
            String,
            str(self.get_parameter("output_topic").value),
            reliable_qos,
        )
        self._subscription = self.create_subscription(
            LaserScan,
            str(self.get_parameter("scan_topic").value),
            self._on_scan,
            qos_profile_sensor_data,
        )
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(
            self._tf_buffer,
            self,
            spin_thread=False,
        )
        self._latest_scan: Optional[LaserScan] = None
        self._scan_received_at = 0.0
        self._timer = self.create_timer(1.0 / publish_rate, self._publish)

    def _on_scan(self, message: LaserScan) -> None:
        self._latest_scan = message
        self._scan_received_at = time.monotonic()

    def _publish(self) -> None:
        scan = self._latest_scan
        if (
            scan is None
            or time.monotonic() - self._scan_received_at > self._scan_timeout
        ):
            return
        try:
            scan_snapshot = compact_scan_snapshot(
                scan,
                self._sensor_x,
                self._sensor_y,
                self._sensor_yaw,
                self._max_points,
            )
        except ValueError as error:
            self.get_logger().error(f"Rejected web scan: {error}")
            return
        pose = None
        try:
            transform = self._tf_buffer.lookup_transform(
                self._target_frame,
                self._source_frame,
                Time(),
            )
            now_sec = self.get_clock().now().nanoseconds / 1e9
            if transform_is_fresh(
                transform,
                now_sec,
                self._pose_timeout,
            ):
                pose = transform_snapshot(self._robot_id, transform)
        except TransformException:
            pass
        output = String()
        output.data = json.dumps(
            {
                "version": 1,
                "robot_id": self._robot_id,
                "scan": scan_snapshot,
                "map_pose": pose,
            },
            allow_nan=False,
            separators=(",", ":"),
        )
        self._publisher.publish(output)


def main(args=None) -> None:
    """Run compact web telemetry until shutdown."""
    rclpy.init(args=args)
    node = WebTelemetryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
