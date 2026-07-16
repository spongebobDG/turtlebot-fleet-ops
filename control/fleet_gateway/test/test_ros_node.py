import math

import pytest

from action_msgs.msg import GoalStatus
from builtin_interfaces.msg import Time
from fleet_interfaces.msg import RobotStatus
from nav2_msgs.action import NavigateToPose

from fleet_gateway.ros_node import navigation_feedback_to_dict
from fleet_gateway.ros_node import navigation_goal_from_target
from fleet_gateway.ros_node import navigation_terminal_status
from fleet_gateway.ros_node import status_message_to_dict


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


def test_navigation_goal_uses_map_pose_and_yaw_quaternion():
    stamp = Time(sec=10, nanosec=20)
    goal = navigation_goal_from_target(
        {
            "x": 1.2,
            "y": -0.5,
            "yaw": math.pi / 2.0,
            "frame_id": "map",
        },
        stamp,
    )

    assert goal.pose.header.frame_id == "map"
    assert goal.pose.header.stamp == stamp
    assert goal.pose.pose.position.x == pytest.approx(1.2)
    assert goal.pose.pose.position.y == pytest.approx(-0.5)
    assert goal.pose.pose.orientation.z == pytest.approx(math.sqrt(0.5))
    assert goal.pose.pose.orientation.w == pytest.approx(math.sqrt(0.5))


def test_navigation_feedback_builds_json_contract():
    feedback = NavigateToPose.Feedback()
    feedback.current_pose.header.frame_id = "map"
    feedback.current_pose.pose.position.x = 0.4
    feedback.current_pose.pose.position.y = -0.1
    feedback.current_pose.pose.orientation.z = math.sin(0.25)
    feedback.current_pose.pose.orientation.w = math.cos(0.25)
    feedback.navigation_time.sec = 2
    feedback.navigation_time.nanosec = 500_000_000
    feedback.estimated_time_remaining.sec = 4
    feedback.number_of_recoveries = 1
    feedback.distance_remaining = 0.8

    result = navigation_feedback_to_dict(feedback)

    assert result["current_pose"]["x"] == pytest.approx(0.4)
    assert result["current_pose"]["yaw"] == pytest.approx(0.5)
    assert result["navigation_time_sec"] == pytest.approx(2.5)
    assert result["estimated_time_remaining_sec"] == pytest.approx(4.0)
    assert result["number_of_recoveries"] == 1
    assert result["distance_remaining"] == pytest.approx(0.8)


@pytest.mark.parametrize(
    "action_status,timed_out,expected",
    [
        (GoalStatus.STATUS_SUCCEEDED, False, "SUCCEEDED"),
        (GoalStatus.STATUS_CANCELED, False, "CANCELED"),
        (GoalStatus.STATUS_CANCELED, True, "TIMEOUT"),
        (GoalStatus.STATUS_ABORTED, False, "ABORTED"),
        (GoalStatus.STATUS_UNKNOWN, False, "ABORTED"),
    ],
)
def test_navigation_terminal_status_mapping(
    action_status,
    timed_out,
    expected,
):
    assert navigation_terminal_status(action_status, timed_out) == expected
