from collections import deque
import json
import math

import pytest

from fleet_interfaces.msg import NavigationStatus, RobotStatus, SafetyStatus
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import OccupancyGrid
from std_msgs.msg import String

from fleet_gateway.map_registry import map_message_to_dict
from fleet_gateway.ros_node import (
    _map_save_completed_after_response_loss,
    navigation_status_to_dict,
    safety_status_to_dict,
    status_message_to_dict,
    transform_message_to_pose_dict,
    update_clock_offset_estimate,
    web_telemetry_message_to_dict,
)


def test_map_save_response_loss_requires_a_new_validated_status():
    previous = "Map and pose graph saved and validated; completion_ns=100"
    observed = {
        "mapping": {
            "fresh": True,
            "profile": "MAPPING",
            "message": (
                "Map and pose graph saved and validated; completion_ns=200"
            ),
        }
    }

    assert _map_save_completed_after_response_loss(previous, observed)
    observed["mapping"]["message"] = previous
    assert not _map_save_completed_after_response_loss(previous, observed)
    observed["mapping"]["message"] = "Map save failed: validation failed"
    assert not _map_save_completed_after_response_loss(previous, observed)


def test_clock_offset_estimate_ignores_positive_transport_delay_spike():
    samples = deque()

    estimate, delay, raw = update_clock_offset_estimate(
        samples,
        observed_timestamp=100.03,
        robot_timestamp=100.0,
        observed_monotonic=1.0,
        window_sec=10.0,
    )
    assert estimate == pytest.approx(0.03)
    assert delay == pytest.approx(0.0)
    assert raw == pytest.approx(0.03)

    estimate, delay, raw = update_clock_offset_estimate(
        samples,
        observed_timestamp=102.99,
        robot_timestamp=102.0,
        observed_monotonic=3.0,
        window_sec=10.0,
    )
    assert estimate == pytest.approx(0.03)
    assert delay == pytest.approx(0.96)
    assert raw == pytest.approx(0.99)


def test_status_message_to_dict_builds_json_contract():
    message = RobotStatus()
    message.robot_id = "tb1"
    message.hostname = "tb1"
    message.level = RobotStatus.LEVEL_OK
    message.battery_percent = 86.6
    message.position_x = 1.25
    message.scan_min_range = 0.42
    message.wifi_signal_dbm = -40.0
    message.fault_codes = []

    result = status_message_to_dict(message)

    assert result["robot_id"] == "tb1"
    assert result["battery"]["percent"] == pytest.approx(86.6)
    assert result["odom"]["x"] == pytest.approx(1.25)
    assert result["scan"]["min_range"] == pytest.approx(0.42)
    assert result["wifi"]["signal_dbm"] == pytest.approx(-40.0)


def test_web_telemetry_message_parses_scan_and_optional_map_pose():
    message = String()
    message.data = json.dumps(
        {
            "version": 1,
            "robot_id": "tb1",
            "scan": {
                "frame_id": "base_scan",
                "points": [[1.0, 0.0]],
            },
            "map_pose": {
                "frame_id": "map",
                "x": 1.25,
                "y": -0.5,
                "yaw": 0.2,
            },
        }
    )

    scan, pose = web_telemetry_message_to_dict(message, "tb1")

    assert scan["robot_id"] == "tb1"
    assert scan["points"] == [[1.0, 0.0]]
    assert pose is not None
    assert pose["robot_id"] == "tb1"
    assert pose["x"] == pytest.approx(1.25)


def test_web_telemetry_message_rejects_wrong_robot():
    message = String()
    message.data = json.dumps(
        {
            "version": 1,
            "robot_id": "tb2",
            "scan": {"frame_id": "base_scan", "points": []},
            "map_pose": None,
        }
    )

    with pytest.raises(ValueError, match="robot_id"):
        web_telemetry_message_to_dict(message, "tb1")


def test_navigation_safety_and_map_messages_build_web_contracts():
    navigation = NavigationStatus()
    navigation.robot_id = "tb1"
    navigation.state = NavigationStatus.STATE_ACTIVE
    navigation.active_command_id = "goal-1"
    navigation.target_pose.header.frame_id = "map"
    navigation.target_pose.pose.position.x = 1.25
    navigation.target_pose.pose.orientation.z = 0.5
    navigation.target_pose.pose.orientation.w = 0.5
    navigation.distance_remaining = 0.75
    safety = SafetyStatus()
    safety.robot_id = "tb1"
    safety.mode = SafetyStatus.MODE_WAITING_NEUTRAL
    safety.motion_armed = False
    occupancy_map = OccupancyGrid()
    occupancy_map.header.frame_id = "map"
    occupancy_map.info.width = 2
    occupancy_map.info.height = 1
    occupancy_map.info.resolution = 0.05
    occupancy_map.info.origin.position.x = -1.0
    occupancy_map.info.origin.orientation.w = 1.0
    occupancy_map.data = [0, -1]

    navigation_result = navigation_status_to_dict(navigation)
    safety_result = safety_status_to_dict(safety)
    map_result = map_message_to_dict(occupancy_map)

    assert navigation_result["state"] == "ACTIVE"
    assert navigation_result["target"]["yaw"] == pytest.approx(math.pi / 2.0)
    assert navigation_result["distance_remaining"] == pytest.approx(0.75)
    assert safety_result["mode"] == "WAITING_NEUTRAL"
    assert safety_result["motion_armed"] is False
    assert map_result["origin"]["x"] == -1.0
    assert map_result["data"] == [0, -1]


def test_transform_message_builds_map_pose_contract():
    transform = TransformStamped()
    transform.header.frame_id = "map"
    transform.header.stamp.sec = 12
    transform.child_frame_id = "base_footprint"
    transform.transform.translation.x = 1.25
    transform.transform.translation.y = -0.75
    transform.transform.rotation.z = math.sin(0.3 / 2.0)
    transform.transform.rotation.w = math.cos(0.3 / 2.0)

    result = transform_message_to_pose_dict("tb1", transform)

    assert result["robot_id"] == "tb1"
    assert result["frame_id"] == "map"
    assert result["stamp"]["sec"] == 12
    assert result["x"] == pytest.approx(1.25)
    assert result["y"] == pytest.approx(-0.75)
    assert result["yaw"] == pytest.approx(0.3)
