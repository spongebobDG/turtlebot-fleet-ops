"""Launch a robot-free TB1 mock with the web fleet gateway."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch.actions import DeclareLaunchArgument
from launch import LaunchDescription
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    """Return the weekend mock and gateway launch description."""
    share_dir = Path(get_package_share_directory("fleet_gateway"))
    config = share_dir / "config" / "tb1.yaml"
    web_port = LaunchConfiguration("web_port")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "web_port",
                default_value="8000",
                description="Local mock dashboard port",
            ),
            Node(
                package="fleet_gateway",
                executable="fleet_gateway_weekend",
                output="screen",
                parameters=[
                    str(config),
                    {
                        "web_port": ParameterValue(
                            web_port,
                            value_type=int,
                        )
                    },
                ],
            ),
        ]
    )
