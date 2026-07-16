"""Topic contract that keeps every Nav2 velocity behind the watchdog."""

from typing import List, Tuple


Remapping = Tuple[str, str]

NAV2_COMMAND_TOPIC = "cmd_vel_nav"
NAV2_SMOOTHED_TOPIC = "cmd_vel_smoothed"
SAFE_COMMAND_INPUT_TOPIC = "/safety/cmd_vel_in"

MAX_LINEAR_X = 0.05
MAX_ANGULAR_Z = 0.3


def controller_remappings() -> List[Remapping]:
    """Route raw controller output through Nav2's velocity smoother."""
    return [("cmd_vel", NAV2_COMMAND_TOPIC)]


def behavior_remappings() -> List[Remapping]:
    """Route recovery behavior output directly to the local watchdog."""
    return [("cmd_vel", SAFE_COMMAND_INPUT_TOPIC)]


def velocity_smoother_remappings() -> List[Remapping]:
    """Route smoothed Nav2 output to the local watchdog input."""
    return [
        ("cmd_vel", NAV2_COMMAND_TOPIC),
        (NAV2_SMOOTHED_TOPIC, SAFE_COMMAND_INPUT_TOPIC),
    ]
