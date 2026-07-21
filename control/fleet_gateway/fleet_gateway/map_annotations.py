"""Persistent semantic map annotations and fail-closed geometry checks."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import uuid

from fleet_gateway.map_registry import cell_center_to_world, world_to_cell


ANNOTATION_TYPES = {
    "virtual_wall",
    "keepout",
    "privacy",
    "charging",
}
HARD_BLOCK_TYPES = {"virtual_wall", "keepout", "privacy"}
MAX_POINTS = 64


class MapAnnotationStore:
    """Store versioned map annotations in one atomic local JSON document."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path).expanduser() if path is not None else None
        self._lock = threading.RLock()
        self._document: Dict[str, Any] = {"version": 1, "robots": {}}
        self._load()

    def list(self, robot_id: str) -> List[Dict[str, Any]]:
        """Return annotations for one robot in creation order."""
        with self._lock:
            records = self._document["robots"].get(robot_id, [])
            return deepcopy(records)

    def get(self, robot_id: str, annotation_id: str) -> Optional[Dict[str, Any]]:
        """Return one annotation or None."""
        return next(
            (
                record
                for record in self.list(robot_id)
                if record["annotation_id"] == annotation_id
            ),
            None,
        )

    def create(
        self,
        robot_id: str,
        payload: Mapping[str, Any],
        occupancy_map: Mapping[str, Any],
        protected_pose: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Validate, persist and return one semantic map annotation."""
        record = normalize_annotation(robot_id, payload, occupancy_map)
        if protected_pose is not None and record["type"] in HARD_BLOCK_TYPES:
            reason = annotation_blocks_point(
                record,
                float(protected_pose["x"]),
                float(protected_pose["y"]),
            )
            if reason:
                raise ValueError(
                    "The annotation would trap the robot at its current pose"
                )
        with self._lock:
            records = self._document["robots"].setdefault(robot_id, [])
            records.append(record)
            self._persist_locked()
        return deepcopy(record)

    def delete(self, robot_id: str, annotation_id: str) -> bool:
        """Delete one annotation and report whether it existed."""
        with self._lock:
            records = self._document["robots"].get(robot_id, [])
            remaining = [
                record
                for record in records
                if record["annotation_id"] != annotation_id
            ]
            if len(remaining) == len(records):
                return False
            self._document["robots"][robot_id] = remaining
            self._persist_locked()
            return True

    def blocked_reason(self, robot_id: str, x: float, y: float) -> str:
        """Return the first active hard-policy violation at a map point."""
        for record in self.list(robot_id):
            reason = annotation_blocks_point(record, x, y)
            if reason:
                return reason
        return ""

    def segment_blocked_reason(
        self,
        robot_id: str,
        start: Tuple[float, float],
        end: Tuple[float, float],
        step_m: float = 0.025,
    ) -> str:
        """Sample a short motion segment against active hard policies."""
        distance = math.hypot(end[0] - start[0], end[1] - start[1])
        count = max(1, int(math.ceil(distance / max(0.005, step_m))))
        for index in range(count + 1):
            ratio = index / count
            x = start[0] + (end[0] - start[0]) * ratio
            y = start[1] + (end[1] - start[1]) * ratio
            reason = self.blocked_reason(robot_id, x, y)
            if reason:
                return reason
        return ""

    def has_hard_blocks(self, robot_id: str) -> bool:
        """Return whether one robot has any enabled movement restrictions."""
        return any(
            record.get("enabled", True)
            and record.get("type") in HARD_BLOCK_TYPES
            for record in self.list(robot_id)
        )

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(
                f"Map annotation store is unreadable: {self._path}"
            ) from error
        if (
            not isinstance(document, dict)
            or document.get("version") != 1
            or not isinstance(document.get("robots"), dict)
        ):
            raise ValueError("Map annotation store has an unsupported format")
        self._document = document

    def _persist_locked(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(
            f".{self._path.name}.{uuid.uuid4().hex}.tmp"
        )
        temporary.write_text(
            json.dumps(
                self._document,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
            temporary.replace(self._path)
            os.chmod(self._path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()


def normalize_annotation(
    robot_id: str,
    payload: Mapping[str, Any],
    occupancy_map: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate an API payload and return a canonical stored record."""
    annotation_type = str(payload.get("type", "")).strip().lower()
    if annotation_type not in ANNOTATION_TYPES:
        raise ValueError("Unsupported map annotation type")
    name = str(payload.get("name", "")).strip()
    if not name:
        name = {
            "virtual_wall": "가상 벽",
            "keepout": "금지구역",
            "privacy": "개인정보 보호구역",
            "charging": "충전 위치",
        }[annotation_type]
    if len(name) > 80:
        raise ValueError("Annotation name must be 80 characters or fewer")
    width_m = _finite_range(payload.get("width_m", 0.08), 0.02, 2.0, "width_m")
    margin_m = _finite_range(
        payload.get("safety_margin_m", 0.16),
        0.0,
        1.0,
        "safety_margin_m",
    )
    points: List[Dict[str, float]] = []
    pose: Optional[Dict[str, float]] = None
    if annotation_type == "charging":
        raw_pose = payload.get("pose")
        if not isinstance(raw_pose, Mapping):
            raise ValueError("Charging position requires a map pose")
        pose = {
            "x": _finite(raw_pose.get("x"), "pose.x"),
            "y": _finite(raw_pose.get("y"), "pose.y"),
            "yaw": _finite(raw_pose.get("yaw"), "pose.yaw"),
        }
        _require_inside_map(occupancy_map, pose["x"], pose["y"])
    else:
        raw_points = payload.get("points")
        if not isinstance(raw_points, Sequence) or isinstance(
            raw_points,
            (str, bytes),
        ):
            raise ValueError("Annotation points must be an array")
        minimum = 2 if annotation_type == "virtual_wall" else 3
        if not minimum <= len(raw_points) <= MAX_POINTS:
            raise ValueError(
                f"{annotation_type} requires {minimum}..{MAX_POINTS} points"
            )
        for index, raw_point in enumerate(raw_points):
            if not isinstance(raw_point, Mapping):
                raise ValueError(f"points[{index}] must be an object")
            point = {
                "x": _finite(raw_point.get("x"), f"points[{index}].x"),
                "y": _finite(raw_point.get("y"), f"points[{index}].y"),
            }
            _require_inside_map(occupancy_map, point["x"], point["y"])
            points.append(point)
        if annotation_type == "virtual_wall" and sum(
            math.hypot(
                second["x"] - first["x"],
                second["y"] - first["y"],
            )
            for first, second in zip(points, points[1:])
        ) < 0.05:
            raise ValueError("Virtual wall length must be at least 0.05 m")
        if annotation_type != "virtual_wall" and abs(_polygon_area(points)) < 0.01:
            raise ValueError("Zone polygon area must be at least 0.01 m2")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "annotation_id": f"zone-{uuid.uuid4().hex}",
        "robot_id": robot_id,
        "type": annotation_type,
        "name": name,
        "enabled": bool(payload.get("enabled", True)),
        "points": points,
        "pose": pose,
        "width_m": width_m,
        "safety_margin_m": margin_m,
        "policy": _policy_for(annotation_type),
        "map_geometry": _map_geometry(occupancy_map),
        "created_at": now,
        "updated_at": now,
    }


def annotation_blocks_point(
    annotation: Mapping[str, Any],
    x: float,
    y: float,
) -> str:
    """Return a human-readable reason when one annotation blocks a point."""
    if (
        not annotation.get("enabled", True)
        or annotation.get("type") not in HARD_BLOCK_TYPES
    ):
        return ""
    points = annotation.get("points") or []
    margin = max(0.0, float(annotation.get("safety_margin_m", 0.0)))
    annotation_type = str(annotation.get("type"))
    blocked = False
    if annotation_type == "virtual_wall":
        radius = margin + max(0.0, float(annotation.get("width_m", 0.0))) / 2.0
        blocked = any(
            _distance_to_segment(x, y, first, second) <= radius
            for first, second in zip(points, points[1:])
        )
    elif len(points) >= 3:
        blocked = _point_in_polygon(x, y, points) or any(
            _distance_to_segment(x, y, first, second) <= margin
            for first, second in _polygon_edges(points)
        )
    if not blocked:
        return ""
    label = {
        "virtual_wall": "가상 벽",
        "keepout": "금지구역",
        "privacy": "개인정보 보호구역",
    }[annotation_type]
    return f"{label} '{annotation.get('name', label)}'이(가) 이동을 차단합니다"


def compile_keepout_mask(
    occupancy_map: Mapping[str, Any],
    annotations: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Rasterize enabled hard policies to a Nav2 keepout OccupancyGrid."""
    width = int(occupancy_map["width"])
    height = int(occupancy_map["height"])
    hard = [
        annotation
        for annotation in annotations
        if annotation.get("enabled", True)
        and annotation.get("type") in HARD_BLOCK_TYPES
    ]
    data = [0] * (width * height)
    for cell_y in range(height):
        for cell_x in range(width):
            x, y = cell_center_to_world(occupancy_map, cell_x, cell_y)
            if any(annotation_blocks_point(item, x, y) for item in hard):
                data[cell_y * width + cell_x] = 100
    return {
        "frame_id": "map",
        "width": width,
        "height": height,
        "resolution": float(occupancy_map["resolution"]),
        "origin": deepcopy(dict(occupancy_map.get("origin", {}))),
        "data": data,
    }


def _policy_for(annotation_type: str) -> Dict[str, str]:
    if annotation_type == "privacy":
        return {
            "motion": "HARD_BLOCK",
            "data": "NO_CAPTURE_NO_STORAGE",
        }
    if annotation_type in HARD_BLOCK_TYPES:
        return {"motion": "HARD_BLOCK", "data": "UNCHANGED"}
    return {"motion": "CHARGING_DESTINATION", "data": "UNCHANGED"}


def _map_geometry(occupancy_map: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "width": int(occupancy_map["width"]),
        "height": int(occupancy_map["height"]),
        "resolution": float(occupancy_map["resolution"]),
        "origin": deepcopy(dict(occupancy_map.get("origin", {}))),
    }


def _require_inside_map(occupancy_map: Mapping[str, Any], x: float, y: float) -> None:
    if world_to_cell(occupancy_map, x, y) is None:
        raise ValueError("Annotation geometry must stay inside the map")


def _finite(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be finite") from error
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _finite_range(value: Any, minimum: float, maximum: float, field: str) -> float:
    result = _finite(value, field)
    if not minimum <= result <= maximum:
        raise ValueError(f"{field} must be within {minimum}..{maximum}")
    return result


def _distance_to_segment(
    x: float,
    y: float,
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    start_x = float(first["x"])
    start_y = float(first["y"])
    delta_x = float(second["x"]) - start_x
    delta_y = float(second["y"]) - start_y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared <= 1.0e-12:
        return math.hypot(x - start_x, y - start_y)
    ratio = max(
        0.0,
        min(1.0, ((x - start_x) * delta_x + (y - start_y) * delta_y) / length_squared),
    )
    return math.hypot(x - (start_x + ratio * delta_x), y - (start_y + ratio * delta_y))


def _point_in_polygon(
    x: float,
    y: float,
    points: Sequence[Mapping[str, Any]],
) -> bool:
    inside = False
    previous = points[-1]
    for current in points:
        current_x = float(current["x"])
        current_y = float(current["y"])
        previous_x = float(previous["x"])
        previous_y = float(previous["y"])
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            boundary_x = (
                (previous_x - current_x)
                * (y - current_y)
                / (previous_y - current_y)
                + current_x
            )
            if x < boundary_x:
                inside = not inside
        previous = current
    return inside


def _polygon_edges(
    points: Sequence[Mapping[str, Any]],
) -> Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]]:
    return list(zip(points, list(points[1:]) + [points[0]]))


def _polygon_area(points: Sequence[Mapping[str, Any]]) -> float:
    return 0.5 * sum(
        float(first["x"]) * float(second["y"])
        - float(second["x"]) * float(first["y"])
        for first, second in _polygon_edges(points)
    )
