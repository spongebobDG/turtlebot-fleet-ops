"""ROS log relay contract tests."""

from types import SimpleNamespace

from rcl_interfaces.msg import Log
import rclpy

from robot_agent.rosout_relay import RosoutRelay


def test_rosout_relay_preserves_the_original_log_message() -> None:
    """Relay without changing timestamp, severity, logger, or text."""
    rclpy.init()
    relay = RosoutRelay()
    published = []
    relay._publisher = SimpleNamespace(publish=published.append)
    message = Log()
    message.level = 40
    message.name = "controller_server"
    message.msg = "goal aborted"

    try:
        relay._on_log(message)
    finally:
        relay.destroy_node()
        rclpy.shutdown()

    assert published == [message]
