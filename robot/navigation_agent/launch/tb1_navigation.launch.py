"""Launch static-map Nav2 and fleet navigation supervision on TB1."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node, SetRemap
from nav2_common.launch import RewrittenYaml
import yaml


def generate_launch_description() -> LaunchDescription:
    """Use the Humble Burger baseline with watchdog-aligned velocity limits."""
    share_dir = Path(get_package_share_directory("navigation_agent"))
    nav2_share = Path(get_package_share_directory("nav2_bringup"))
    tb3_share = Path(get_package_share_directory("turtlebot3_navigation2"))
    official_params = tb3_share / "param" / "humble" / "burger.yaml"
    agent_config = share_dir / "config" / "tb1.yaml"
    rewrites_file = share_dir / "config" / "tb1_nav2_rewrites.yaml"
    with rewrites_file.open(encoding="utf-8") as stream:
        rewrite_values = yaml.safe_load(stream)
    if not isinstance(rewrite_values, dict) or not rewrite_values:
        raise ValueError("TB1 Nav2 parameter rewrites must be a non-empty map")
    map_file = LaunchConfiguration("map")
    use_sim_time = LaunchConfiguration("use_sim_time")
    configured_params = RewrittenYaml(
        source_file=str(official_params),
        root_key=None,
        param_rewrites={
            str(name): str(value)
            for name, value in rewrite_values.items()
        },
        convert_types=True,
    )
    default_map = [
        EnvironmentVariable("HOME"),
        "/.local/share/turtlebot-fleet-ops/maps/tb1/map.yaml",
    ]
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "map",
                default_value=default_map,
                description="Absolute path to the saved TB1 map YAML",
            ),
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use a simulator clock instead of system time",
            ),
            GroupAction(
                [
                    SetRemap(
                        src="/cmd_vel",
                        dst="/motion/navigation/cmd_vel",
                    ),
                    IncludeLaunchDescription(
                        PythonLaunchDescriptionSource(
                            str(nav2_share / "launch" / "bringup_launch.py")
                        ),
                        launch_arguments={
                            "map": map_file,
                            "params_file": configured_params,
                            "use_sim_time": use_sim_time,
                            "autostart": "true",
                            "use_composition": "False",
                            "use_respawn": "True",
                        }.items(),
                    ),
                ]
            ),
            Node(
                package="navigation_agent",
                executable="motion_arbiter_node",
                name="motion_arbiter",
                output="screen",
                parameters=[
                    str(agent_config),
                    {"default_mode": 0, "use_sim_time": use_sim_time},
                ],
                respawn=True,
                respawn_delay=3.0,
            ),
            Node(
                package="navigation_agent",
                executable="navigation_agent_node",
                name="navigation_agent",
                output="screen",
                parameters=[
                    str(agent_config),
                    {"use_sim_time": use_sim_time},
                ],
                respawn=True,
                respawn_delay=3.0,
            ),
        ]
    )
