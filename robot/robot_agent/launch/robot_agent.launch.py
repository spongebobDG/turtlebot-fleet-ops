"""Launch the Robot Agent with the checked-in TB1 policy."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Create the TB1 Robot Agent launch description."""
    package_share = Path(get_package_share_directory("robot_agent"))
    config_path = package_share / "config" / "tb1.yaml"

    return LaunchDescription(
        [
            Node(
                package="robot_agent",
                executable="robot_agent",
                name="robot_agent",
                output="screen",
                parameters=[str(config_path)],
            )
        ]
    )
