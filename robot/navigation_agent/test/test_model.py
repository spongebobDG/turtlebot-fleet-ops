import math

import pytest

from navigation_agent.model import (
    GridMap,
    MODE_IDLE,
    MODE_MANUAL,
    MODE_NAVIGATION,
    ZERO_COMMAND,
    cell_value,
    choose_command,
    pose_is_on_free_cell,
    world_to_cell,
)


def make_grid(origin_yaw=0.0):
    return GridMap(
        width=3,
        height=2,
        resolution=1.0,
        origin_x=10.0,
        origin_y=20.0,
        origin_yaw=origin_yaw,
        data=(0, 100, -1, 0, 0, 0),
    )


def test_world_to_cell_and_occupancy_policy():
    grid = make_grid()

    assert world_to_cell(grid, 10.1, 20.1) == (0, 0)
    assert cell_value(grid, 11.1, 20.1) == 100
    assert pose_is_on_free_cell(grid, 10.1, 20.1)
    assert not pose_is_on_free_cell(grid, 11.1, 20.1)
    assert not pose_is_on_free_cell(grid, 12.1, 20.1)
    assert world_to_cell(grid, 9.9, 20.0) is None


def test_world_to_cell_accounts_for_rotated_origin():
    grid = make_grid(origin_yaw=math.pi / 2.0)

    assert world_to_cell(grid, 9.9, 20.1) == (0, 0)
    assert world_to_cell(grid, 9.9, 21.1) == (1, 0)


def test_grid_rejects_inconsistent_data():
    with pytest.raises(ValueError):
        GridMap(2, 2, 0.05, 0.0, 0.0, 0.0, (0,))

    with pytest.raises(ValueError, match="-1..100"):
        GridMap(1, 1, 0.05, 0.0, 0.0, 0.0, (101,))

    with pytest.raises(ValueError, match="origin"):
        GridMap(1, 1, 0.05, math.nan, 0.0, 0.0, (0,))


def test_arbiter_fails_closed_and_requires_fresh_authorization():
    common = {
        "now": 10.0,
        "input_timeout_sec": 0.5,
        "authorization_timeout_sec": 0.5,
        "manual_command": (0.03, 0.1),
        "manual_received_at": 9.8,
        "navigation_command": (0.05, -0.2),
        "navigation_received_at": 9.8,
        "authorization_received_at": 9.8,
    }

    assert choose_command(mode=MODE_IDLE, **common) == ZERO_COMMAND
    assert choose_command(mode=MODE_MANUAL, **common) == (0.03, 0.1)
    assert choose_command(mode=MODE_NAVIGATION, **common) == (0.05, -0.2)
    assert choose_command(
        mode=MODE_NAVIGATION,
        **{**common, "authorization_received_at": 9.0},
    ) == ZERO_COMMAND
    assert choose_command(
        mode=MODE_NAVIGATION,
        **{**common, "navigation_received_at": 9.0},
    ) == ZERO_COMMAND
