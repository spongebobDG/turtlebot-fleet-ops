"""Unit tests for the Nav2-to-watchdog topic contract."""

from fleet_navigation.safety_contract import behavior_remappings
from fleet_navigation.safety_contract import controller_remappings
from fleet_navigation.safety_contract import NAV2_COMMAND_TOPIC
from fleet_navigation.safety_contract import NAV2_SMOOTHED_TOPIC
from fleet_navigation.safety_contract import SAFE_COMMAND_INPUT_TOPIC
from fleet_navigation.safety_contract import velocity_smoother_remappings


def test_controller_output_goes_to_velocity_smoother() -> None:
    assert controller_remappings() == [("cmd_vel", NAV2_COMMAND_TOPIC)]


def test_smoothed_output_goes_to_watchdog() -> None:
    assert velocity_smoother_remappings() == [
        ("cmd_vel", NAV2_COMMAND_TOPIC),
        (NAV2_SMOOTHED_TOPIC, SAFE_COMMAND_INPUT_TOPIC),
    ]


def test_recovery_behavior_output_goes_to_watchdog() -> None:
    assert behavior_remappings() == [
        ("cmd_vel", SAFE_COMMAND_INPUT_TOPIC)
    ]
