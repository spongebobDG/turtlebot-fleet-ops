"""Launch TB1 AMCL and Nav2 with every velocity behind the watchdog."""

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from fleet_navigation.safety_contract import behavior_remappings
from fleet_navigation.safety_contract import controller_remappings
from fleet_navigation.safety_contract import velocity_smoother_remappings
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import IncludeLaunchDescription
from launch.actions import SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml


def _navigation_node(
    package: str,
    executable: str,
    name: str,
    configured_params: ParameterFile,
    use_respawn: LaunchConfiguration,
    log_level: LaunchConfiguration,
    remappings=None,
) -> Node:
    """Create one non-composed Nav2 lifecycle node."""
    return Node(
        package=package,
        executable=executable,
        name=name,
        output="screen",
        respawn=use_respawn,
        respawn_delay=2.0,
        parameters=[configured_params],
        arguments=["--ros-args", "--log-level", log_level],
        remappings=[("/tf", "tf"), ("/tf_static", "tf_static")]
        + list(remappings or []),
    )


def generate_launch_description() -> LaunchDescription:
    """Build localization and navigation nodes for a saved TB1 map."""
    package_share = Path(get_package_share_directory("fleet_navigation"))
    nav2_share = Path(get_package_share_directory("nav2_bringup"))

    map_yaml = LaunchConfiguration("map")
    params_file = LaunchConfiguration("params_file")
    use_sim_time = LaunchConfiguration("use_sim_time")
    autostart = LaunchConfiguration("autostart")
    use_respawn = LaunchConfiguration("use_respawn")
    log_level = LaunchConfiguration("log_level")

    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            root_key="",
            param_rewrites={
                "use_sim_time": use_sim_time,
                "autostart": autostart,
            },
            convert_types=True,
        ),
        allow_substs=True,
    )

    lifecycle_nodes = [
        "controller_server",
        "smoother_server",
        "planner_server",
        "behavior_server",
        "bt_navigator",
        "waypoint_follower",
        "velocity_smoother",
    ]

    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_share, "launch", "localization_launch.py")
        ),
        launch_arguments={
            "map": map_yaml,
            "params_file": params_file,
            "use_sim_time": use_sim_time,
            "autostart": autostart,
            "use_composition": "False",
            "use_respawn": use_respawn,
            "log_level": log_level,
        }.items(),
    )

    navigation_nodes = [
        _navigation_node(
            "nav2_controller",
            "controller_server",
            "controller_server",
            configured_params,
            use_respawn,
            log_level,
            controller_remappings(),
        ),
        _navigation_node(
            "nav2_smoother",
            "smoother_server",
            "smoother_server",
            configured_params,
            use_respawn,
            log_level,
        ),
        _navigation_node(
            "nav2_planner",
            "planner_server",
            "planner_server",
            configured_params,
            use_respawn,
            log_level,
        ),
        _navigation_node(
            "nav2_behaviors",
            "behavior_server",
            "behavior_server",
            configured_params,
            use_respawn,
            log_level,
            behavior_remappings(),
        ),
        _navigation_node(
            "nav2_bt_navigator",
            "bt_navigator",
            "bt_navigator",
            configured_params,
            use_respawn,
            log_level,
        ),
        _navigation_node(
            "nav2_waypoint_follower",
            "waypoint_follower",
            "waypoint_follower",
            configured_params,
            use_respawn,
            log_level,
        ),
        _navigation_node(
            "nav2_velocity_smoother",
            "velocity_smoother",
            "velocity_smoother",
            configured_params,
            use_respawn,
            log_level,
            velocity_smoother_remappings(),
        ),
        Node(
            package="nav2_lifecycle_manager",
            executable="lifecycle_manager",
            name="lifecycle_manager_navigation",
            output="screen",
            arguments=["--ros-args", "--log-level", log_level],
            parameters=[
                {"use_sim_time": use_sim_time},
                {"autostart": autostart},
                {"node_names": lifecycle_nodes},
            ],
        ),
    ]

    return LaunchDescription(
        [
            SetEnvironmentVariable("RCUTILS_LOGGING_BUFFERED_STREAM", "1"),
            DeclareLaunchArgument(
                "map",
                default_value=str(package_share / "maps" / "tb1_lab.yaml"),
                description="Full path to the saved occupancy-grid YAML",
            ),
            DeclareLaunchArgument(
                "params_file",
                default_value=str(
                    package_share / "config" / "tb1_nav2.yaml"
                ),
                description="Full path to the TB1 Nav2 parameter file",
            ),
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use simulation clock instead of wall clock",
            ),
            DeclareLaunchArgument(
                "autostart",
                default_value="true",
                description="Configure and activate Nav2 lifecycle nodes",
            ),
            DeclareLaunchArgument(
                "use_respawn",
                default_value="false",
                description="Respawn a Nav2 process after an unexpected exit",
            ),
            DeclareLaunchArgument(
                "log_level",
                default_value="info",
                description="ROS logger severity for Nav2 processes",
            ),
            localization,
            *navigation_nodes,
        ]
    )
