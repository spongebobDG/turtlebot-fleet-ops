"""Keep remote DDS routes outside the robot-local velocity boundary."""

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ZENOH_ROOT = REPOSITORY_ROOT / "infra" / "zenoh"


def _allow(name: str) -> dict:
    document = json.loads((ZENOH_ROOT / name).read_text(encoding="utf-8"))
    return document["plugins"]["ros2dds"]["allow"]


def _ros2dds(name: str) -> dict:
    document = json.loads((ZENOH_ROOT / name).read_text(encoding="utf-8"))
    return document["plugins"]["ros2dds"]


def test_bridge_halves_cover_navigation_contract() -> None:
    robot = _allow("robot-bridge.json5")
    control = _allow("control-bridge.json5")

    assert "^/fleet/navigation_lease$" in control["publishers"]
    assert "^/fleet/navigation_lease$" in robot["subscribers"]
    for topic in (
        "^/fleet/robot_status$",
        "^/fleet/navigation_status$",
        "^/fleet/safety_status$",
        "^/fleet/mapping_status$",
        "^/fleet/web_telemetry$",
    ):
        assert topic in robot["publishers"]
        assert topic in control["subscribers"]
    for service in (
        "^/tb1/navigation/manual_command$",
        "^/tb1/navigation/set_operating_profile$",
        "^/tb1/navigation/save_map$",
    ):
        assert service in robot["service_servers"]
        assert service in control["service_clients"]
    assert "^/tb1/navigation/navigate$" in robot["action_servers"]
    assert "^/tb1/navigation/navigate$" in control["action_clients"]


def test_bridges_never_proxy_velocity_topics() -> None:
    forbidden = (
        "/cmd_vel",
        "/safety/cmd_vel_in",
        "/motion/manual/cmd_vel",
        "/motion/navigation/cmd_vel",
    )
    for name in ("robot-bridge.json5", "control-bridge.json5"):
        text = (ZENOH_ROOT / name).read_text(encoding="utf-8")
        for topic in forbidden:
            assert topic not in text


def test_control_bridge_allows_long_robot_management_services() -> None:
    timeouts = _ros2dds("control-bridge.json5")["queries_timeout"][
        "services"
    ]

    assert ".*set_operating_profile$=50.0" in timeouts
    assert ".*set_initial_pose$=20.0" in timeouts
    assert ".*save_map$=100.0" in timeouts
    assert ".*=5.0" in timeouts


def test_start_scripts_load_repository_allow_lists() -> None:
    robot = (ZENOH_ROOT / "start-robot-bridge.sh").read_text()
    control = (ZENOH_ROOT / "start-control-bridge.sh").read_text()

    assert "robot-bridge.json5" in robot
    assert 'exec "${bridge}" -c "${config}"' in robot
    assert "control-bridge.json5" in control
    assert 'exec "${bridge}" -c "${config}" -e' in control
