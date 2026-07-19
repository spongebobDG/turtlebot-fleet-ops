import math

import pytest
from sensor_msgs.msg import LaserScan

from fleet_gateway.scan_registry import ScanRegistry, scan_message_to_dict


def test_scan_conversion_applies_sensor_offset_and_filters_ranges():
    message = LaserScan()
    message.header.frame_id = "base_scan"
    message.angle_min = 0.0
    message.angle_max = math.pi / 2.0
    message.angle_increment = math.pi / 2.0
    message.range_min = 0.1
    message.range_max = 10.0
    message.ranges = [1.0, 2.0, math.inf, 0.05]

    result = scan_message_to_dict(message, sensor_x=-0.032)

    assert result["sample_count"] == 4
    assert result["valid_points"] == 2
    assert result["nearest_range"] == pytest.approx(1.0)
    assert result["points"][0] == pytest.approx([0.968, 0.0])
    assert result["points"][1] == pytest.approx([-0.032, 2.0])
    assert result["coverage_ratio"] == pytest.approx(0.25)


def test_scan_registry_reports_freshness_and_returns_a_copy():
    now = [10.0]
    registry = ScanRegistry(clock=lambda: now[0])
    registry.update(
        "tb1",
        {"frame_id": "base_scan", "points": [[1.0, 2.0]]},
    )

    first = registry.get("tb1")
    first["points"][0][0] = 99.0
    now[0] = 11.1
    second = registry.get("tb1")

    assert second["points"] == [[1.0, 2.0]]
    assert second["fresh"] is False
    assert second["age_sec"] == pytest.approx(1.1)
