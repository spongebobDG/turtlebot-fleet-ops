"""Launch the current TB1 HTTP, WebSocket and custom-action mock stack."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    """Return a robot-free TB1 gateway and action server."""
    share_dir = Path(get_package_share_directory("fleet_gateway"))
    config = share_dir / "config" / "tb1.yaml"
    use_sim_time = LaunchConfiguration("use_sim_time")
    web_port = LaunchConfiguration("web_port")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use a simulator clock instead of system time",
            ),
            DeclareLaunchArgument(
                "web_port",
                default_value="8000",
                description="HTTP port for the robot-free dashboard",
            ),
            Node(
                package="fleet_gateway",
                executable="mock_robot",
                name="mock_tb1",
                output="screen",
                parameters=[{"use_sim_time": use_sim_time}],
            ),
            Node(
                package="fleet_gateway",
                executable="fleet_gateway",
                name="fleet_gateway",
                output="screen",
                parameters=[
                    str(config),
                    {
                        "use_sim_time": use_sim_time,
                        "web_port": ParameterValue(web_port, value_type=int),
                    },
                ],
            ),
        ]
    )
