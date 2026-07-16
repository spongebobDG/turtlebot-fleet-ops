import pytest

from fleet_interfaces.msg import RobotStatus

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
