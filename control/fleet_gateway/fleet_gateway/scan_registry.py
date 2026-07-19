"""Thread-safe, JSON-safe LaserScan snapshots for map alignment."""

from copy import deepcopy
import math
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional


class ScanRegistry:
    """Store the latest local-frame LiDAR points for each robot."""

    def __init__(
        self,
        freshness_timeout_sec: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            not math.isfinite(freshness_timeout_sec)
            or freshness_timeout_sec <= 0.0
        ):
            raise ValueError("scan freshness timeout must be positive")
        self._freshness_timeout_sec = freshness_timeout_sec
        self._clock = clock
        self._scans: Dict[str, Dict[str, Any]] = {}
        self._received_at: Dict[str, float] = {}
        self._lock = threading.RLock()

    def update(self, robot_id: str, snapshot: Mapping[str, Any]) -> None:
        """Validate and store one scan snapshot."""
        identifier = robot_id.strip()
        if not identifier:
            raise ValueError("robot_id must be non-empty")
        frame_id = str(snapshot.get("frame_id", "")).strip()
        if not frame_id:
            raise ValueError("scan frame_id must be non-empty")
        points = snapshot.get("points", [])
        if not isinstance(points, list):
            raise ValueError("scan points must be a list")
        normalized_points = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("scan points must contain x/y pairs")
            x_value, y_value = (float(point[0]), float(point[1]))
            if not math.isfinite(x_value) or not math.isfinite(y_value):
                raise ValueError("scan point coordinates must be finite")
            normalized_points.append([x_value, y_value])
        record = deepcopy(dict(snapshot))
        record["robot_id"] = identifier
        record["frame_id"] = frame_id
        record["points"] = normalized_points
        with self._lock:
            self._scans[identifier] = record
            self._received_at[identifier] = self._clock()

    def get(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Return the latest snapshot with monotonic freshness metadata."""
        with self._lock:
            snapshot = self._scans.get(robot_id)
            received_at = self._received_at.get(robot_id)
            if snapshot is None or received_at is None:
                return None
            result = deepcopy(snapshot)
        age_sec = max(0.0, self._clock() - received_at)
        result["age_sec"] = age_sec
        result["fresh"] = age_sec <= self._freshness_timeout_sec
        return result


def scan_message_to_dict(
    message: Any,
    sensor_x: float = 0.0,
    sensor_y: float = 0.0,
    sensor_yaw: float = 0.0,
) -> Dict[str, Any]:
    """Convert a LaserScan-like message into compact local x/y points."""
    pose_values = (float(sensor_x), float(sensor_y), float(sensor_yaw))
    if not all(math.isfinite(value) for value in pose_values):
        raise ValueError("scan sensor pose must be finite")
    angle_min = float(message.angle_min)
    angle_max = float(message.angle_max)
    angle_increment = float(message.angle_increment)
    range_min = float(message.range_min)
    range_max = float(message.range_max)
    geometry = (
        angle_min,
        angle_max,
        angle_increment,
        range_min,
        range_max,
    )
    if not all(math.isfinite(value) for value in geometry):
        raise ValueError("scan geometry must be finite")
    if angle_increment <= 0.0 or range_min < 0.0 or range_max <= range_min:
        raise ValueError("scan geometry is invalid")
    cosine = math.cos(sensor_yaw)
    sine = math.sin(sensor_yaw)
    points = []
    nearest = None
    for index, raw_range in enumerate(message.ranges):
        distance = float(raw_range)
        if (
            not math.isfinite(distance)
            or distance < range_min
            or distance > range_max
        ):
            continue
        angle = angle_min + index * angle_increment
        local_x = distance * math.cos(angle)
        local_y = distance * math.sin(angle)
        points.append(
            [
                sensor_x + cosine * local_x - sine * local_y,
                sensor_y + sine * local_x + cosine * local_y,
            ]
        )
        nearest = distance if nearest is None else min(nearest, distance)
    span = max(0.0, min(math.tau, angle_max - angle_min))
    return {
        "frame_id": str(message.header.frame_id),
        "stamp": {
            "sec": int(message.header.stamp.sec),
            "nanosec": int(message.header.stamp.nanosec),
        },
        "sensor_pose": {
            "x": sensor_x,
            "y": sensor_y,
            "yaw": sensor_yaw,
        },
        "angle_span_deg": math.degrees(span),
        "coverage_ratio": span / math.tau,
        "sample_count": len(message.ranges),
        "valid_points": len(points),
        "nearest_range": nearest,
        "points": points,
    }
