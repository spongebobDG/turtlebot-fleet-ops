"""Launch the safety watchdog with the TB1 configuration."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    package_share = Path(get_package_share_directory("safety_watchdog"))
    parameters = package_share / "config" / "tb1.yaml"

    return LaunchDescription(
        [
            Node(
                package="safety_watchdog",
                executable="safety_watchdog_node",
                name="safety_watchdog",
                output="screen",
                parameters=[str(parameters)],
            )
        ]
    )
