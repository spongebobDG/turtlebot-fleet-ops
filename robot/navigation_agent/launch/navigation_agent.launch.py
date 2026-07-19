"""Launch the TB1 motion arbiter and robot-local navigation agent."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Return the TB1 navigation supervision nodes."""
    share_dir = Path(get_package_share_directory("navigation_agent"))
    config = share_dir / "config" / "tb1.yaml"
    return LaunchDescription(
        [
            Node(
                package="navigation_agent",
                executable="motion_arbiter_node",
                name="motion_arbiter",
                output="screen",
                parameters=[str(config)],
                respawn=True,
                respawn_delay=3.0,
            ),
            Node(
                package="navigation_agent",
                executable="navigation_agent_node",
                name="navigation_agent",
                output="screen",
                parameters=[str(config)],
                respawn=True,
                respawn_delay=3.0,
            ),
        ]
    )
