import json

import pytest

from fleet_gateway.map_annotations import (
    MapAnnotationStore,
    annotation_blocks_point,
    compile_keepout_mask,
)


def occupancy_map():
    return {
        "frame_id": "map",
        "width": 20,
        "height": 20,
        "resolution": 0.1,
        "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "data": [0] * 400,
    }


def test_store_persists_hard_policies_and_charging_destinations(tmp_path):
    path = tmp_path / "annotations.json"
    store = MapAnnotationStore(path)
    wall = store.create(
        "tb1",
        {
            "type": "virtual_wall",
            "name": "복도 벽",
            "points": [{"x": 1.0, "y": 0.2}, {"x": 1.0, "y": 1.8}],
            "width_m": 0.08,
            "safety_margin_m": 0.16,
        },
        occupancy_map(),
    )
    charging = store.create(
        "tb1",
        {
            "type": "charging",
            "name": "충전기",
            "pose": {"x": 0.3, "y": 0.3, "yaw": 1.57},
        },
        occupancy_map(),
    )

    reloaded = MapAnnotationStore(path).list("tb1")

    assert [item["annotation_id"] for item in reloaded] == [
        wall["annotation_id"],
        charging["annotation_id"],
    ]
    assert annotation_blocks_point(wall, 1.19, 1.0)
    assert not annotation_blocks_point(charging, 0.3, 0.3)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_polygon_blocks_interior_margin_and_mask_cells():
    store = MapAnnotationStore()
    privacy = store.create(
        "tb1",
        {
            "type": "privacy",
            "name": "상담 구역",
            "points": [
                {"x": 0.5, "y": 0.5},
                {"x": 1.5, "y": 0.5},
                {"x": 1.5, "y": 1.5},
                {"x": 0.5, "y": 1.5},
            ],
            "safety_margin_m": 0.1,
        },
        occupancy_map(),
    )

    mask = compile_keepout_mask(occupancy_map(), [privacy])

    assert store.blocked_reason("tb1", 1.0, 1.0)
    assert store.blocked_reason("tb1", 1.55, 1.0)
    assert not store.blocked_reason("tb1", 1.8, 1.0)
    assert mask["data"][10 * 20 + 10] == 100
    assert mask["data"][1 * 20 + 1] == 0


def test_rejects_geometry_outside_map_and_policy_that_traps_robot():
    store = MapAnnotationStore()
    with pytest.raises(ValueError, match="inside the map"):
        store.create(
            "tb1",
            {
                "type": "virtual_wall",
                "points": [{"x": -0.1, "y": 0.2}, {"x": 1.0, "y": 0.2}],
            },
            occupancy_map(),
        )

    with pytest.raises(ValueError, match="trap the robot"):
        store.create(
            "tb1",
            {
                "type": "keepout",
                "points": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 0.8, "y": 0.0},
                    {"x": 0.8, "y": 0.8},
                    {"x": 0.0, "y": 0.8},
                ],
            },
            occupancy_map(),
            protected_pose={"x": 0.4, "y": 0.4, "yaw": 0.0},
        )
