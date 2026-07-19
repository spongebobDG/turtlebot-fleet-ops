"""Correlative LiDAR-to-OccupancyGrid alignment for initial poses."""

import heapq
import math
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from fleet_gateway.map_registry import cell_center_to_world, world_to_cell


_NEIGHBORS = (
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, math.sqrt(2.0)),
    (1, -1, math.sqrt(2.0)),
    (-1, 1, math.sqrt(2.0)),
    (-1, -1, math.sqrt(2.0)),
)


def score_pose_alignment(
    occupancy_map: Mapping[str, Any],
    scan: Mapping[str, Any],
    x: float,
    y: float,
    yaw: float,
) -> Dict[str, Any]:
    """Score one map-frame pose using current LiDAR endpoints."""
    points = _sample_points(scan, 160)
    distance_field = _build_distance_field(occupancy_map)
    metrics = _score_pose(
        occupancy_map,
        distance_field,
        points,
        (float(x), float(y), float(yaw)),
    )
    return _public_metrics(metrics, len(points))


def align_pose(
    occupancy_map: Mapping[str, Any],
    scan: Mapping[str, Any],
    seed_x: float,
    seed_y: float,
    seed_yaw: float,
) -> Dict[str, Any]:
    """Find a globally aligned pose, then refine it at sub-cell resolution."""
    points = _sample_points(scan, 160)
    coarse_points = _sample_sequence(points, 64)
    distance_field = _build_distance_field(occupancy_map)
    seed = (float(seed_x), float(seed_y), _normalize_angle(seed_yaw))
    seed_metrics = _score_pose(
        occupancy_map,
        distance_field,
        points,
        seed,
    )

    resolution = float(occupancy_map["resolution"])
    stride = max(1, int(round(0.10 / resolution)))
    coarse_best = None
    for cell_y in range(0, int(occupancy_map["height"]), stride):
        for cell_x in range(0, int(occupancy_map["width"]), stride):
            if not _is_free_cell(occupancy_map, cell_x, cell_y):
                continue
            x_value, y_value = cell_center_to_world(
                occupancy_map,
                cell_x,
                cell_y,
            )
            for degrees in range(-180, 180, 10):
                pose = (x_value, y_value, math.radians(degrees))
                metrics = _score_pose(
                    occupancy_map,
                    distance_field,
                    coarse_points,
                    pose,
                )
                coarse_best = _better(coarse_best, pose, metrics)
    if coarse_best is None:
        raise ValueError("Map has no free cell for LiDAR alignment")

    best = _refine(
        occupancy_map,
        distance_field,
        points,
        coarse_best,
        translation_radius=max(0.15, resolution * 2.0),
        translation_step=max(0.02, resolution / 2.0),
        yaw_radius=math.radians(10.0),
        yaw_step=math.radians(2.0),
    )
    best = _refine(
        occupancy_map,
        distance_field,
        points,
        best,
        translation_radius=max(0.03, resolution * 0.6),
        translation_step=max(0.01, resolution / 5.0),
        yaw_radius=math.radians(2.0),
        yaw_step=math.radians(0.5),
    )
    pose, metrics = best
    result = _public_metrics(metrics, len(points))
    result.update(
        {
            "pose": {"x": pose[0], "y": pose[1], "yaw": pose[2]},
            "seed": {
                "pose": {"x": seed[0], "y": seed[1], "yaw": seed[2]},
                **_public_metrics(seed_metrics, len(points)),
            },
        }
    )
    return result


def alignment_is_acceptable(metrics: Mapping[str, Any]) -> bool:
    """Return whether endpoint agreement is safe enough to seed AMCL."""
    return bool(
        int(metrics.get("point_count", 0)) >= 40
        and float(metrics.get("matched_ratio", 0.0)) >= 0.35
        and float(metrics.get("inside_ratio", 0.0)) >= 0.70
        and float(metrics.get("score", -1.0)) >= 0.20
    )


def _sample_points(
    scan: Mapping[str, Any],
    maximum: int,
) -> List[Tuple[float, float]]:
    if not bool(scan.get("fresh", True)):
        raise ValueError("LiDAR scan is stale")
    normalized = []
    for point in scan.get("points", []):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            continue
        values = (float(point[0]), float(point[1]))
        if all(math.isfinite(value) for value in values):
            normalized.append(values)
    if len(normalized) < 40:
        raise ValueError("At least 40 valid LiDAR points are required")
    return _sample_sequence(normalized, maximum)


def _sample_sequence(
    values: Sequence[Tuple[float, float]],
    maximum: int,
) -> List[Tuple[float, float]]:
    if len(values) <= maximum:
        return list(values)
    step = len(values) / maximum
    return [values[min(len(values) - 1, int(index * step))] for index in range(maximum)]


def _build_distance_field(occupancy_map: Mapping[str, Any]) -> List[float]:
    width = int(occupancy_map["width"])
    height = int(occupancy_map["height"])
    data = occupancy_map["data"]
    distances = [math.inf] * (width * height)
    queue: List[Tuple[float, int]] = []
    for index, value in enumerate(data):
        if int(value) >= 50:
            distances[index] = 0.0
            heapq.heappush(queue, (0.0, index))
    if not queue:
        raise ValueError("Map has no occupied cells for LiDAR alignment")
    while queue:
        distance, index = heapq.heappop(queue)
        if distance != distances[index]:
            continue
        cell_x = index % width
        cell_y = index // width
        for delta_x, delta_y, cost in _NEIGHBORS:
            next_x = cell_x + delta_x
            next_y = cell_y + delta_y
            if not 0 <= next_x < width or not 0 <= next_y < height:
                continue
            next_index = next_y * width + next_x
            next_distance = distance + cost
            if next_distance < distances[next_index]:
                distances[next_index] = next_distance
                heapq.heappush(queue, (next_distance, next_index))
    return distances


def _score_pose(
    occupancy_map: Mapping[str, Any],
    distance_field: Sequence[float],
    points: Iterable[Tuple[float, float]],
    pose: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    point_list = list(points)
    resolution = float(occupancy_map["resolution"])
    match_distance = max(0.10, resolution * 1.5)
    sigma = max(0.08, resolution)
    cosine = math.cos(pose[2])
    sine = math.sin(pose[2])
    total_score = 0.0
    matched = 0
    inside = 0
    width = int(occupancy_map["width"])
    for local_x, local_y in point_list:
        world_x = pose[0] + cosine * local_x - sine * local_y
        world_y = pose[1] + sine * local_x + cosine * local_y
        cell = world_to_cell(occupancy_map, world_x, world_y)
        if cell is None:
            total_score -= 0.5
            continue
        inside += 1
        distance = distance_field[cell[1] * width + cell[0]] * resolution
        total_score += math.exp(-0.5 * (distance / sigma) ** 2)
        if distance <= match_distance:
            matched += 1
    count = max(1, len(point_list))
    return total_score / count, matched / count, inside / count


def _refine(
    occupancy_map: Mapping[str, Any],
    distance_field: Sequence[float],
    points: Sequence[Tuple[float, float]],
    current: Tuple[Tuple[float, float, float], Tuple[float, float, float]],
    translation_radius: float,
    translation_step: float,
    yaw_radius: float,
    yaw_step: float,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    center = current[0]
    steps = int(math.ceil(translation_radius / translation_step))
    yaw_steps = int(math.ceil(yaw_radius / yaw_step))
    best = current
    for x_step in range(-steps, steps + 1):
        for y_step in range(-steps, steps + 1):
            x_value = center[0] + x_step * translation_step
            y_value = center[1] + y_step * translation_step
            if not _is_free_pose(occupancy_map, x_value, y_value):
                continue
            for angle_step in range(-yaw_steps, yaw_steps + 1):
                pose = (
                    x_value,
                    y_value,
                    _normalize_angle(center[2] + angle_step * yaw_step),
                )
                metrics = _score_pose(
                    occupancy_map,
                    distance_field,
                    points,
                    pose,
                )
                best = _better(best, pose, metrics)
    return best


def _better(current, pose, metrics):
    if current is None or metrics[0] > current[1][0]:
        return pose, metrics
    return current


def _is_free_pose(
    occupancy_map: Mapping[str, Any],
    x: float,
    y: float,
) -> bool:
    cell = world_to_cell(occupancy_map, x, y)
    return cell is not None and _is_free_cell(occupancy_map, *cell)


def _is_free_cell(
    occupancy_map: Mapping[str, Any],
    cell_x: int,
    cell_y: int,
) -> bool:
    width = int(occupancy_map["width"])
    return int(occupancy_map["data"][cell_y * width + cell_x]) == 0


def _public_metrics(
    metrics: Tuple[float, float, float],
    point_count: int,
) -> Dict[str, Any]:
    result = {
        "score": metrics[0],
        "matched_ratio": metrics[1],
        "inside_ratio": metrics[2],
        "point_count": int(point_count),
    }
    result["acceptable"] = alignment_is_acceptable(result)
    return result


def _normalize_angle(value: float) -> float:
    return math.atan2(math.sin(float(value)), math.cos(float(value)))
