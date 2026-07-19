"""Thread-safe occupancy maps and map-coordinate validation."""

from copy import deepcopy
import math
import threading
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


class MapRegistry:
    """Store one latest occupancy grid per robot."""

    def __init__(self, free_value_max: int = 0) -> None:
        if not 0 <= free_value_max <= 100:
            raise ValueError("free_value_max must be within 0..100")
        self._free_value_max = free_value_max
        self._maps: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def update(self, robot_id: str, snapshot: Mapping[str, Any]) -> None:
        """Validate and store a JSON-safe occupancy-grid snapshot."""
        identifier = robot_id.strip()
        if not identifier:
            raise ValueError("robot_id must be non-empty")
        if str(snapshot.get("frame_id", "")).strip() != "map":
            raise ValueError("occupancy map frame must be map")
        try:
            data = [int(value) for value in snapshot.get("data", [])]
        except (TypeError, ValueError) as error:
            raise ValueError("map data must contain integer values") from error
        width = int(snapshot.get("width", 0))
        height = int(snapshot.get("height", 0))
        resolution = float(snapshot.get("resolution", 0.0))
        if width <= 0 or height <= 0 or len(data) != width * height:
            raise ValueError("map dimensions do not match map data")
        if not math.isfinite(resolution) or resolution <= 0.0:
            raise ValueError("map resolution must be positive and finite")
        if any(value < -1 or value > 100 for value in data):
            raise ValueError("map data values must be within -1..100")
        origin = snapshot.get("origin", {})
        origin_values = (
            float(origin.get("x", 0.0)),
            float(origin.get("y", 0.0)),
            float(origin.get("yaw", 0.0)),
        )
        if not all(math.isfinite(value) for value in origin_values):
            raise ValueError("map origin must contain finite values")
        record = deepcopy(dict(snapshot))
        record["robot_id"] = identifier
        record["frame_id"] = "map"
        record["data"] = data
        with self._lock:
            self._maps[identifier] = record

    def get(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Return one complete map snapshot."""
        with self._lock:
            snapshot = self._maps.get(robot_id)
            return deepcopy(snapshot) if snapshot is not None else None

    def validate_pose(
        self,
        robot_id: str,
        x: float,
        y: float,
    ) -> Tuple[bool, str]:
        """Validate finite coordinates and require a known free map cell."""
        if not math.isfinite(x) or not math.isfinite(y):
            return False, "Pose coordinates must be finite"
        snapshot = self.get(robot_id)
        if snapshot is None:
            return False, "Map is unavailable"
        cell = world_to_cell(snapshot, x, y)
        if cell is None:
            return False, "Pose is outside the map"
        cell_x, cell_y = cell
        value = int(
            snapshot["data"][cell_y * int(snapshot["width"]) + cell_x]
        )
        if value < 0:
            return False, "Pose is on an unknown map cell"
        if value > self._free_value_max:
            return False, "Pose is not on a free map cell"
        return True, "Pose is on a free map cell"


def world_to_cell(
    snapshot: Mapping[str, Any],
    x: float,
    y: float,
) -> Optional[Tuple[int, int]]:
    """Transform world coordinates into a row-major occupancy-grid cell."""
    origin = snapshot.get("origin", {})
    resolution = float(snapshot["resolution"])
    delta_x = x - float(origin.get("x", 0.0))
    delta_y = y - float(origin.get("y", 0.0))
    yaw = float(origin.get("yaw", 0.0))
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    local_x = cosine * delta_x + sine * delta_y
    local_y = -sine * delta_x + cosine * delta_y
    cell_x = math.floor(local_x / resolution)
    cell_y = math.floor(local_y / resolution)
    width = int(snapshot["width"])
    height = int(snapshot["height"])
    if not 0 <= cell_x < width or not 0 <= cell_y < height:
        return None
    return int(cell_x), int(cell_y)


def cell_center_to_world(
    snapshot: Mapping[str, Any],
    cell_x: int,
    cell_y: int,
) -> Tuple[float, float]:
    """Return the map-frame center of one occupancy-grid cell."""
    width = int(snapshot["width"])
    height = int(snapshot["height"])
    if not 0 <= cell_x < width or not 0 <= cell_y < height:
        raise ValueError("cell is outside the map")
    resolution = float(snapshot["resolution"])
    origin = snapshot.get("origin", {})
    yaw = float(origin.get("yaw", 0.0))
    local_x = (cell_x + 0.5) * resolution
    local_y = (cell_y + 0.5) * resolution
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    return (
        float(origin.get("x", 0.0)) + cosine * local_x - sine * local_y,
        float(origin.get("y", 0.0)) + sine * local_x + cosine * local_y,
    )


def map_message_to_dict(message: Any) -> Dict[str, Any]:
    """Convert a nav_msgs/OccupancyGrid-like object to the web contract."""
    orientation = message.info.origin.orientation
    yaw = _quaternion_to_yaw(orientation.z, orientation.w)
    return {
        "frame_id": message.header.frame_id,
        "stamp": {
            "sec": int(message.header.stamp.sec),
            "nanosec": int(message.header.stamp.nanosec),
        },
        "width": int(message.info.width),
        "height": int(message.info.height),
        "resolution": float(message.info.resolution),
        "origin": {
            "x": float(message.info.origin.position.x),
            "y": float(message.info.origin.position.y),
            "yaw": yaw,
        },
        "data": [int(value) for value in message.data],
    }


def _quaternion_to_yaw(z: float, w: float) -> float:
    values: Sequence[float] = (float(z), float(w))
    if not all(math.isfinite(value) for value in values):
        return 0.0
    norm = math.hypot(*values)
    if norm <= 1.0e-12:
        return 0.0
    z_value, w_value = (value / norm for value in values)
    return math.atan2(2.0 * w_value * z_value, 1.0 - 2.0 * z_value**2)
