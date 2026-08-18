from nav_msgs.msg import OccupancyGrid

from navigation_agent.map_annotation_filter import (
    _snapshot_id,
    rasterize_annotations,
)


def make_map():
    message = OccupancyGrid()
    message.info.width = 20
    message.info.height = 20
    message.info.resolution = 0.1
    message.info.origin.orientation.w = 1.0
    return message


def test_rasterizes_virtual_walls_but_not_charging_positions():
    annotations = [
        {
            "type": "virtual_wall",
            "enabled": True,
            "points": [{"x": 1.0, "y": 0.2}, {"x": 1.0, "y": 1.8}],
            "width_m": 0.08,
            "safety_margin_m": 0.16,
        },
        {
            "type": "charging",
            "enabled": True,
            "pose": {"x": 0.25, "y": 0.25, "yaw": 0.0},
        },
    ]

    mask = rasterize_annotations(make_map(), annotations)

    assert mask[10 * 20 + 10] == 100
    assert mask[2 * 20 + 2] == 0


def test_snapshot_id_is_stable_across_mapping_key_order():
    first = [{"type": "keepout", "points": [{"x": 1.0, "y": 2.0}]}]
    second = [{"points": [{"y": 2.0, "x": 1.0}], "type": "keepout"}]

    assert _snapshot_id("tb1", first) == _snapshot_id("tb1", second)
    assert _snapshot_id("tb1", first) != _snapshot_id("tb2", first)
