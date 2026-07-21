"""Test deterministic helpers used by the robot-free TB1 simulator."""

import math

import pytest

from fleet_gateway.mock_robot import (
    interpolate_pose,
    navigation_duration,
    square_room_scan_ranges,
)


def test_navigation_duration_reserves_long_goal_for_cancel() -> None:
    assert navigation_duration(0.5) == 2.0
    assert navigation_duration(1.5) == 30.0


def test_interpolate_pose_clamps_progress() -> None:
    start = (0.0, 0.0, 0.0)
    target = (1.0, -1.0, 2.0)

    assert interpolate_pose(start, target, -1.0) == start
    assert interpolate_pose(start, target, 2.0) == target
    assert interpolate_pose(start, target, 0.5) == pytest.approx(
        (0.5, -0.5, 1.0)
    )


def test_square_room_scan_matches_map_boundary() -> None:
    ranges = square_room_scan_ranges((0.0, 0.0, 0.0))

    assert len(ranges) == 360
    assert min(ranges) == pytest.approx(1.975, abs=0.001)
    assert max(ranges) < 2.8
    assert ranges[0] == pytest.approx(1.975)
    assert ranges[-1] == pytest.approx(1.975)


def test_square_room_scan_tracks_pose_and_yaw() -> None:
    ranges = square_room_scan_ranges((0.5, 0.0, math.pi))

    assert min(ranges) == pytest.approx(1.475, abs=0.001)
    assert all(0.12 <= distance <= 3.5 for distance in ranges)


def test_square_room_raw_scan_uses_tb1_rear_facing_angle_zero() -> None:
    ranges = square_room_scan_ranges((0.5, 0.0, 0.0))

    # Raw -pi points along physical base_link +X and is normalized to bin 0.
    assert ranges[0] == pytest.approx(1.475, abs=0.001)
    # Raw angle 0 points along physical -X before the pi-radian correction.
    assert ranges[180] == pytest.approx(2.475, abs=0.02)
