import math

import pytest

from fleet_gateway.map_registry import cell_center_to_world
from fleet_gateway.pose_alignment import (
    align_pose,
    alignment_is_acceptable,
    score_pose_alignment,
)


def make_alignment_fixture():
    width = 30
    height = 24
    resolution = 0.1
    data = [0] * (width * height)
    occupied = set()
    for cell_x in range(width):
        occupied.add((cell_x, 0))
        occupied.add((cell_x, height - 1))
    for cell_y in range(height):
        occupied.add((0, cell_y))
        occupied.add((width - 1, cell_y))
    occupied.update((19, cell_y) for cell_y in range(3, 15))
    occupied.update((cell_x, 17) for cell_x in range(7, 16))
    for cell_x, cell_y in occupied:
        data[cell_y * width + cell_x] = 100
    occupancy_map = {
        "frame_id": "map",
        "width": width,
        "height": height,
        "resolution": resolution,
        "origin": {"x": -1.0, "y": -0.7, "yaw": 0.17},
        "data": data,
    }
    true_pose = (0.45, 0.55, 0.42)
    cosine = math.cos(true_pose[2])
    sine = math.sin(true_pose[2])
    points = []
    for cell_x, cell_y in occupied:
        world_x, world_y = cell_center_to_world(
            occupancy_map,
            cell_x,
            cell_y,
        )
        delta_x = world_x - true_pose[0]
        delta_y = world_y - true_pose[1]
        distance = math.hypot(delta_x, delta_y)
        if 0.2 <= distance <= 2.5:
            points.append(
                [
                    cosine * delta_x + sine * delta_y,
                    -sine * delta_x + cosine * delta_y,
                ]
            )
    return occupancy_map, {"fresh": True, "points": points}, true_pose


def angle_error(left, right):
    return abs(math.atan2(math.sin(left - right), math.cos(left - right)))


def test_global_alignment_recovers_asymmetric_map_pose():
    occupancy_map, scan, true_pose = make_alignment_fixture()

    result = align_pose(occupancy_map, scan, -0.4, 0.0, -2.4)

    assert result["acceptable"] is True
    assert result["matched_ratio"] >= 0.75
    assert result["inside_ratio"] >= 0.9
    assert result["pose"]["x"] == pytest.approx(true_pose[0], abs=0.12)
    assert result["pose"]["y"] == pytest.approx(true_pose[1], abs=0.12)
    assert angle_error(result["pose"]["yaw"], true_pose[2]) <= 0.12
    assert result["seed"]["matched_ratio"] < result["matched_ratio"]


def test_pose_score_rejects_visually_wrong_candidate():
    occupancy_map, scan, true_pose = make_alignment_fixture()

    aligned = score_pose_alignment(occupancy_map, scan, *true_pose)
    wrong = score_pose_alignment(occupancy_map, scan, 0.0, 0.0, -2.7)

    assert alignment_is_acceptable(aligned) is True
    assert alignment_is_acceptable(wrong) is False
    assert aligned["matched_ratio"] > wrong["matched_ratio"]


def test_alignment_requires_representative_scan():
    occupancy_map, _, _ = make_alignment_fixture()

    with pytest.raises(ValueError, match="At least 40"):
        align_pose(
            occupancy_map,
            {"fresh": True, "points": [[0.5, 0.0]]},
            0.0,
            0.0,
            0.0,
        )
