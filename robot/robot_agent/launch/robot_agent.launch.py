"""Launch the Robot Agent with the checked-in TB1 policy."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Create the TB1 Robot Agent launch description."""
    package_share = Path(get_package_share_directory("robot_agent"))
    config_path = package_share / "config" / "tb1.yaml"
    use_sim_time = LaunchConfiguration("use_sim_time")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use a simulator clock instead of system time",
            ),
            Node(
                package="robot_agent",
                executable="robot_agent",
                name="robot_agent",
                output="screen",
                parameters=[str(config_path), {"use_sim_time": use_sim_time}],
            )
        ]
    )
