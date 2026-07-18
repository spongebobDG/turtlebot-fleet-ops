"""Launch the safety watchdog with the TB1 configuration."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    package_share = Path(get_package_share_directory("safety_watchdog"))
    parameters = package_share / "config" / "tb1.yaml"
    use_sim_time = LaunchConfiguration("use_sim_time")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use a simulator clock instead of system time",
            ),
            Node(
                package="safety_watchdog",
                executable="safety_watchdog_node",
                name="safety_watchdog",
                output="screen",
                parameters=[str(parameters), {"use_sim_time": use_sim_time}],
                respawn=True,
                respawn_delay=0.5,
            )
        ]
    )
