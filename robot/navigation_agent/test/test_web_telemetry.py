"""Verify compact web telemetry conversion contracts."""

import math
from types import SimpleNamespace

import pytest

from navigation_agent.web_telemetry import (
    compact_scan_snapshot,
    transform_is_fresh,
    transform_snapshot,
)


def _stamp() -> SimpleNamespace:
    return SimpleNamespace(sec=12, nanosec=34)


def test_compact_scan_is_bounded_and_applies_sensor_pose() -> None:
    message = SimpleNamespace(
        header=SimpleNamespace(frame_id="base_scan", stamp=_stamp()),
        angle_min=0.0,
        angle_max=math.tau - math.tau / 360.0,
        angle_increment=math.tau / 360.0,
        range_min=0.05,
        range_max=12.0,
        ranges=[1.0] * 360,
    )

    snapshot = compact_scan_snapshot(message, -0.032, 0.0, 0.0, 120)

    assert snapshot["frame_id"] == "base_scan"
    assert snapshot["sample_count"] == 360
    assert snapshot["valid_points"] == 120
    assert len(snapshot["points"]) == 120
    assert snapshot["points"][0] == pytest.approx([0.968, 0.0])


def test_transform_snapshot_returns_map_pose() -> None:
    message = SimpleNamespace(
        header=SimpleNamespace(frame_id="map", stamp=_stamp()),
        transform=SimpleNamespace(
            translation=SimpleNamespace(x=1.2, y=-0.5),
            rotation=SimpleNamespace(z=math.sin(0.4), w=math.cos(0.4)),
        ),
    )

    pose = transform_snapshot("tb1", message)

    assert pose["robot_id"] == "tb1"
    assert pose["frame_id"] == "map"
    assert pose["x"] == pytest.approx(1.2)
    assert pose["yaw"] == pytest.approx(0.8)


def test_cached_map_transform_expires_when_profile_stops() -> None:
    message = SimpleNamespace(
        header=SimpleNamespace(frame_id="map", stamp=_stamp()),
    )

    assert transform_is_fresh(message, now_sec=12.5, timeout_sec=1.0)
    assert not transform_is_fresh(message, now_sec=13.1, timeout_sec=1.0)
