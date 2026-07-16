"""Launch the Phase 4 single-robot fleet gateway."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Return a launch description with the TB1 gateway config."""
    share_dir = Path(get_package_share_directory("fleet_gateway"))
    config = share_dir / "config" / "tb1.yaml"
    return LaunchDescription(
        [
            Node(
                package="fleet_gateway",
                executable="fleet_gateway",
                name="fleet_gateway",
                output="screen",
                parameters=[str(config)],
            )
        ]
    )
