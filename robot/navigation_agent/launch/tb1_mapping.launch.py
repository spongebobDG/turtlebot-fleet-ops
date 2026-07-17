"""Launch TB1 manual mapping through the safety command path."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Run SLAM Toolbox and a manual-mode motion arbiter."""
    share_dir = Path(get_package_share_directory("navigation_agent"))
    slam_share = Path(get_package_share_directory("slam_toolbox"))
    config = share_dir / "config" / "tb1.yaml"
    slam_config = share_dir / "config" / "tb1_slam.yaml"
    use_sim_time = LaunchConfiguration("use_sim_time")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use a simulator clock instead of system time",
            ),
            Node(
                package="navigation_agent",
                executable="motion_arbiter_node",
                name="motion_arbiter",
                output="screen",
                parameters=[
                    str(config),
                    {"default_mode": 1, "use_sim_time": use_sim_time},
                ],
                respawn=True,
                respawn_delay=3.0,
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    str(slam_share / "launch" / "online_async_launch.py")
                ),
                launch_arguments={
                    "use_sim_time": use_sim_time,
                    "slam_params_file": str(slam_config),
                }.items(),
            ),
        ]
    )
