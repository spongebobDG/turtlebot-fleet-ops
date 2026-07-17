import math

import pytest

from fleet_interfaces.msg import NavigationStatus, RobotStatus, SafetyStatus
from nav_msgs.msg import OccupancyGrid

from fleet_gateway.map_registry import map_message_to_dict
from fleet_gateway.ros_node import (
    navigation_status_to_dict,
    safety_status_to_dict,
    status_message_to_dict,
)


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
