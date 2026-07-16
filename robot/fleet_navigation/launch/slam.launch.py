"""Launch asynchronous SLAM Toolbox for the physical TB1 sensor stack."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Build the TB1 mapping launch description without motion producers."""
    package_share = Path(get_package_share_directory("fleet_navigation"))
    default_parameters = package_share / "config" / "tb1_slam.yaml"
    normalizer_parameters = (
        package_share / "config" / "tb1_scan_normalizer.yaml"
    )

    use_sim_time = LaunchConfiguration("use_sim_time")
    parameters = LaunchConfiguration("slam_params_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use simulation clock instead of wall clock",
            ),
            DeclareLaunchArgument(
                "slam_params_file",
                default_value=str(default_parameters),
                description="Full path to the SLAM Toolbox parameter file",
            ),
            Node(
                package="fleet_navigation",
                executable="scan_normalizer",
                name="scan_normalizer",
                output="screen",
                parameters=[str(normalizer_parameters)],
            ),
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                name="slam_toolbox",
                output="screen",
                parameters=[parameters, {"use_sim_time": use_sim_time}],
                remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
            ),
        ]
    )
