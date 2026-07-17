import math

import pytest

from fleet_gateway.map_registry import (
    MapRegistry,
    cell_center_to_world,
    world_to_cell,
)


def snapshot(origin_yaw=0.0):
    return {
        "frame_id": "map",
        "width": 3,
        "height": 2,
        "resolution": 1.0,
        "origin": {"x": 10.0, "y": 20.0, "yaw": origin_yaw},
        "data": [0, 100, -1, 0, 0, 0],
    }


def test_map_registry_validates_bounds_unknown_and_occupied_cells():
    registry = MapRegistry()
    registry.update("tb1", snapshot())

    assert registry.validate_pose("tb1", 10.1, 20.1)[0]
    assert registry.validate_pose("tb1", 11.1, 20.1) == (
        False,
        "Pose is not on a free map cell",
    )
    assert registry.validate_pose("tb1", 12.1, 20.1) == (
        False,
        "Pose is on an unknown map cell",
    )
    assert registry.validate_pose("tb1", 9.9, 20.0) == (
        False,
        "Pose is outside the map",
    )


def test_world_to_cell_supports_rotated_map_origins():
    rotated = snapshot(origin_yaw=math.pi / 2.0)

    assert world_to_cell(rotated, 9.9, 20.1) == (0, 0)
    assert world_to_cell(rotated, 9.9, 21.1) == (1, 0)
    world = cell_center_to_world(rotated, 1, 0)
    assert world == pytest.approx((9.5, 21.5))
    assert world_to_cell(rotated, *world) == (1, 0)


def test_map_registry_rejects_out_of_contract_data_and_origin():
    registry = MapRegistry()
    bad_frame = snapshot()
    bad_frame["frame_id"] = "odom"
    with pytest.raises(ValueError, match="frame"):
        registry.update("tb1", bad_frame)

    bad_data = snapshot()
    bad_data["data"][0] = 101
    with pytest.raises(ValueError, match="-1..100"):
        registry.update("tb1", bad_data)

    bad_origin = snapshot()
    bad_origin["origin"]["yaw"] = math.nan
    with pytest.raises(ValueError, match="origin"):
        registry.update("tb1", bad_origin)
