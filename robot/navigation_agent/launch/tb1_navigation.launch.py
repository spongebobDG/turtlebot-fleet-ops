"""Launch static-map Nav2 and fleet navigation supervision on TB1."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    RegisterEventHandler,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node
from nav2_common.launch import RewrittenYaml
import yaml


def generate_launch_description() -> LaunchDescription:
    """Use the Humble Burger baseline with watchdog-aligned velocity limits."""
    share_dir = Path(get_package_share_directory("navigation_agent"))
    tb3_share = Path(get_package_share_directory("turtlebot3_navigation2"))
    official_params = tb3_share / "param" / "humble" / "burger.yaml"
    agent_config = share_dir / "config" / "tb1.yaml"
    normalizer_config = share_dir / "config" / "tb1_scan_normalizer.yaml"
    rewrites_file = share_dir / "config" / "tb1_nav2_rewrites.yaml"
    with rewrites_file.open(encoding="utf-8") as stream:
        rewrite_values = yaml.safe_load(stream)
    if not isinstance(rewrite_values, dict) or not rewrite_values:
        raise ValueError("TB1 Nav2 parameter rewrites must be a non-empty map")
    map_file = LaunchConfiguration("map")
    use_sim_time = LaunchConfiguration("use_sim_time")
    lifecycle_bond_timeout = LaunchConfiguration("lifecycle_bond_timeout")
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
    navigation_agent = Node(
        package="navigation_agent",
        executable="navigation_agent_node",
        name="navigation_agent",
        output="screen",
        parameters=[
            str(agent_config),
            {"use_sim_time": use_sim_time},
        ],
        respawn=False,
    )
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
            DeclareLaunchArgument(
                "lifecycle_bond_timeout",
                default_value="15.0",
                description=(
                    "Seconds lifecycle managers wait for bonds on resource-limited TB1"
                ),
            ),
            Node(
                package="nav2_map_server",
                executable="map_server",
                name="map_server",
                output="screen",
                parameters=[
                    configured_params,
                    {"yaml_filename": map_file, "use_sim_time": use_sim_time},
                ],
                remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
                respawn=True,
                respawn_delay=2.0,
            ),
            Node(
                package="nav2_amcl",
                executable="amcl",
                name="amcl",
                output="screen",
                parameters=[configured_params, {"use_sim_time": use_sim_time}],
                remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
                respawn=True,
                respawn_delay=2.0,
            ),
            Node(
                package="nav2_lifecycle_manager",
                executable="lifecycle_manager",
                name="lifecycle_manager_localization",
                output="screen",
                parameters=[
                    {"use_sim_time": use_sim_time},
                    {"autostart": True},
                    {"node_names": ["map_server", "amcl"]},
                    {"bond_timeout": lifecycle_bond_timeout},
                ],
            ),
            Node(
                package="navigation_agent",
                executable="scan_normalizer",
                name="scan_normalizer",
                output="screen",
                parameters=[
                    str(normalizer_config),
                    {"use_sim_time": use_sim_time},
                ],
                respawn=True,
                respawn_delay=3.0,
            ),
            Node(
                package="navigation_agent",
                executable="map_annotation_filter",
                name="map_annotation_filter",
                output="screen",
                parameters=[{"use_sim_time": use_sim_time}],
                respawn=True,
                respawn_delay=3.0,
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    str(share_dir / "launch" / "tb1_nav2_navigation.launch.py")
                ),
                launch_arguments={
                    "params_file": configured_params,
                    "use_sim_time": use_sim_time,
                    "autostart": "true",
                    "use_respawn": "true",
                    "lifecycle_bond_timeout": lifecycle_bond_timeout,
                }.items(),
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
                executable="manual_control_node",
                name="manual_control",
                output="screen",
                parameters=[str(agent_config), {"use_sim_time": use_sim_time}],
                respawn=True,
                respawn_delay=3.0,
            ),
            navigation_agent,
            RegisterEventHandler(
                OnProcessExit(
                    target_action=navigation_agent,
                    on_exit=[
                        EmitEvent(
                            event=Shutdown(
                                reason="navigation agent exited",
                            )
                        )
                    ],
                )
            ),
        ]
    )
