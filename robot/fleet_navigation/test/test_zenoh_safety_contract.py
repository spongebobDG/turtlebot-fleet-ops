"""Verify Zenoh routes preserve the final velocity safety boundary."""

import json
from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ZENOH_ROOT = REPOSITORY_ROOT / "infra" / "zenoh"


def _allow(filename: str):
    with (ZENOH_ROOT / filename).open(encoding="utf-8") as stream:
        config = json.load(stream)
    return config["plugins"]["ros2dds"]["allow"]


def _matches(patterns, interface_name: str) -> bool:
    return any(re.fullmatch(pattern, interface_name) for pattern in patterns)


def test_final_cmd_vel_is_never_bridged() -> None:
    for filename in ("robot-bridge.json5", "control-bridge.json5"):
        allow = _allow(filename)
        for patterns in allow.values():
            assert not _matches(patterns, "/cmd_vel")


def test_teleoperation_uses_watchdog_input_end_to_end() -> None:
    robot = _allow("robot-bridge.json5")
    control = _allow("control-bridge.json5")

    assert _matches(control["publishers"], "/safety/cmd_vel_in")
    assert _matches(robot["subscribers"], "/safety/cmd_vel_in")


def test_robot_status_and_estop_have_both_route_halves() -> None:
    robot = _allow("robot-bridge.json5")
    control = _allow("control-bridge.json5")

    assert _matches(robot["publishers"], "/fleet/robot_status")
    assert _matches(control["subscribers"], "/fleet/robot_status")
    assert _matches(robot["publishers"], "/safety/estop_active")
    assert _matches(control["subscribers"], "/safety/estop_active")
    assert _matches(
        robot["service_servers"],
        "/safety_watchdog/set_estop",
    )
    assert _matches(
        control["service_clients"],
        "/safety_watchdog/set_estop",
    )


def test_navigation_action_and_visualization_are_allowed() -> None:
    robot = _allow("robot-bridge.json5")
    control = _allow("control-bridge.json5")

    assert _matches(robot["action_servers"], "/navigate_to_pose")
    assert _matches(control["action_clients"], "/navigate_to_pose")
    assert _matches(robot["publishers"], "/scan_normalized")
    assert _matches(control["subscribers"], "/scan_normalized")
    assert _matches(robot["publishers"], "/map")
    assert _matches(control["subscribers"], "/map")
