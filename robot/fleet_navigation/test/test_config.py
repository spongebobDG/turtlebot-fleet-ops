"""Verify navigation limits and frames agree with the deployed TB1 stack."""

from pathlib import Path

from fleet_navigation.safety_contract import MAX_ANGULAR_Z
from fleet_navigation.safety_contract import MAX_LINEAR_X
from fleet_navigation.safety_contract import SAFE_COMMAND_INPUT_TOPIC
import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ROBOT_ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path: Path):
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_nav2_limits_do_not_exceed_watchdog_limits() -> None:
    config = _load_yaml(PACKAGE_ROOT / "config" / "tb1_nav2.yaml")
    controller = config["controller_server"]["ros__parameters"]["FollowPath"]
    smoother = config["velocity_smoother"]["ros__parameters"]
    behavior = config["behavior_server"]["ros__parameters"]

    assert controller["max_vel_x"] == MAX_LINEAR_X
    assert controller["max_vel_theta"] == MAX_ANGULAR_Z
    assert smoother["max_velocity"] == [MAX_LINEAR_X, 0.0, MAX_ANGULAR_Z]
    assert behavior["max_rotational_vel"] == MAX_ANGULAR_Z


def test_navigation_frames_and_scan_match_tb1_bringup() -> None:
    config = _load_yaml(PACKAGE_ROOT / "config" / "tb1_nav2.yaml")
    amcl = config["amcl"]["ros__parameters"]
    local = config["local_costmap"]["local_costmap"]["ros__parameters"]
    global_costmap = config["global_costmap"]["global_costmap"][
        "ros__parameters"
    ]

    assert amcl["odom_frame_id"] == "odom"
    assert amcl["base_frame_id"] == "base_footprint"
    assert amcl["scan_topic"] == "/scan_normalized"
    assert local["obstacle_layer"]["scan"]["topic"] == (
        "/scan_normalized"
    )
    assert global_costmap["obstacle_layer"]["scan"]["topic"] == (
        "/scan_normalized"
    )


def test_slam_keeps_enough_scans_for_short_supervised_steps() -> None:
    config = _load_yaml(PACKAGE_ROOT / "config" / "tb1_slam.yaml")
    slam = config["slam_toolbox"]["ros__parameters"]

    assert slam["scan_queue_size"] >= 10
    assert slam["minimum_travel_distance"] <= slam["resolution"]


def test_watchdog_uses_navigation_safe_input() -> None:
    config = _load_yaml(
        ROBOT_ROOT / "safety_watchdog" / "config" / "tb1.yaml"
    )
    parameters = config["safety_watchdog"]["ros__parameters"]

    assert parameters["input_topic"] == SAFE_COMMAND_INPUT_TOPIC
    assert parameters["max_linear_x"] == MAX_LINEAR_X
    assert parameters["max_angular_z"] == MAX_ANGULAR_Z
