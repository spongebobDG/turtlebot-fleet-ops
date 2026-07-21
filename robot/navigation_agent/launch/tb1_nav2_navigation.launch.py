"""Launch Humble Nav2 with TB1-specific velocity ownership."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml


NAVIGATION_CMD_TOPIC = "/motion/navigation/cmd_vel"


def generate_launch_description() -> LaunchDescription:
    """Keep controller smoothing intact and isolate every base command."""
    params_file = LaunchConfiguration("params_file")
    use_sim_time = LaunchConfiguration("use_sim_time")
    autostart = LaunchConfiguration("autostart")
    use_respawn = LaunchConfiguration("use_respawn")
    log_level = LaunchConfiguration("log_level")
    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            root_key=None,
            param_rewrites={
                "use_sim_time": use_sim_time,
                "autostart": autostart,
            },
            convert_types=True,
        ),
        allow_substs=True,
    )
    common = {
        "output": "screen",
        "respawn": use_respawn,
        "respawn_delay": 2.0,
        "parameters": [configured_params],
        "arguments": ["--ros-args", "--log-level", log_level],
    }
    common_remaps = [
        ("/tf", "tf"),
        ("/tf_static", "tf_static"),
        ("/scan", "/scan_normalized"),
    ]
    lifecycle_nodes = [
        "controller_server",
        "smoother_server",
        "planner_server",
        "behavior_server",
        "bt_navigator",
        "waypoint_follower",
        "velocity_smoother",
    ]

    return LaunchDescription(
        [
            SetEnvironmentVariable(
                "RCUTILS_LOGGING_BUFFERED_STREAM",
                "1",
            ),
            DeclareLaunchArgument("params_file"),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("autostart", default_value="true"),
            DeclareLaunchArgument("use_respawn", default_value="true"),
            DeclareLaunchArgument("log_level", default_value="info"),
            Node(
                package="nav2_controller",
                executable="controller_server",
                remappings=common_remaps + [("cmd_vel", "cmd_vel_nav")],
                output=common["output"],
                respawn=common["respawn"],
                respawn_delay=common["respawn_delay"],
                arguments=common["arguments"],
                parameters=[
                    configured_params,
                    {
                        # Slow in-place alignment is valid progress even
                        # before the robot can translate along the path.
                        "progress_checker.plugin": (
                            "nav2_controller::PoseProgressChecker"
                        ),
                        "progress_checker.required_movement_radius": 0.1,
                        "progress_checker.required_movement_angle": 0.1,
                        "progress_checker.movement_time_allowance": 20.0,
                        # DWB can alternate between equally scored clockwise
                        # and counter-clockwise trajectories when a new path
                        # begins almost exactly behind the robot.  Humble's
                        # rotation shim gives that large initial alignment a
                        # deterministic controller phase, then hands the path
                        # back to the repository-tuned DWB controller.
                        "FollowPath.plugin": (
                            "nav2_rotation_shim_controller::"
                            "RotationShimController"
                        ),
                        "FollowPath.primary_controller": (
                            "dwb_core::DWBLocalPlanner"
                        ),
                        "FollowPath.angular_dist_threshold": 0.6,
                        "FollowPath.angular_disengage_threshold": 0.35,
                        "FollowPath.forward_sampling_distance": 0.15,
                        "FollowPath.rotate_to_heading_angular_vel": 0.18,
                        "FollowPath.max_angular_accel": 0.6,
                        "FollowPath.simulate_ahead_time": 1.0,
                        # RotationShimController owns final-yaw control below.
                        # Keeping DWB's RotateToGoal or GoalAlign critics made
                        # DWB slow down or turn toward the final orientation
                        # before entering the 0.10 m XY tolerance, so the shim
                        # never received control on opposite-heading patrol
                        # waypoints.
                        "FollowPath.critics": [
                            "Oscillation",
                            "BaseObstacle",
                            "PathAlign",
                            "PathDist",
                            "GoalDist",
                        ],
                        # Once inside XY tolerance, take control back from DWB
                        # and finish the requested final yaw explicitly.  This
                        # avoids a low-speed DWB stall between patrol points.
                        "FollowPath.rotate_to_goal_heading": True,
                        "FollowPath.closed_loop": True,
                    },
                ],
            ),
            Node(
                package="nav2_smoother",
                executable="smoother_server",
                name="smoother_server",
                remappings=common_remaps,
                **common,
            ),
            Node(
                package="nav2_planner",
                executable="planner_server",
                name="planner_server",
                remappings=common_remaps,
                **common,
            ),
            Node(
                package="nav2_behaviors",
                executable="behavior_server",
                name="behavior_server",
                remappings=common_remaps
                + [("cmd_vel", "cmd_vel_nav")],
                output=common["output"],
                respawn=common["respawn"],
                respawn_delay=common["respawn_delay"],
                arguments=common["arguments"],
                parameters=[
                    configured_params,
                    {
                        # TurtleBot3 Humble stores these under the legacy
                        # recoveries_server key, so the behavior_server node
                        # otherwise falls back to 1.0 rad/s and 3.2 rad/s^2.
                        "max_rotational_vel": 0.22,
                        "min_rotational_vel": 0.05,
                        "rotational_acc_lim": 0.6,
                    },
                ],
            ),
            Node(
                package="nav2_bt_navigator",
                executable="bt_navigator",
                name="bt_navigator",
                remappings=common_remaps,
                **common,
            ),
            Node(
                package="nav2_waypoint_follower",
                executable="waypoint_follower",
                name="waypoint_follower",
                remappings=common_remaps,
                **common,
            ),
            Node(
                package="nav2_velocity_smoother",
                executable="velocity_smoother",
                name="velocity_smoother",
                remappings=common_remaps
                + [
                    ("cmd_vel", "cmd_vel_nav"),
                    ("cmd_vel_smoothed", NAVIGATION_CMD_TOPIC),
                ],
                output=common["output"],
                respawn=common["respawn"],
                respawn_delay=common["respawn_delay"],
                arguments=common["arguments"],
                parameters=[
                    configured_params,
                    {
                        "smoothing_frequency": 20.0,
                        "scale_velocities": True,
                        "feedback": "OPEN_LOOP",
                        "max_velocity": [0.05, 0.0, 0.22],
                        "min_velocity": [-0.05, 0.0, -0.27],
                        "max_accel": [0.08, 0.0, 0.6],
                        "max_decel": [-0.12, 0.0, -0.8],
                        "odom_topic": "/odom",
                        "odom_duration": 0.1,
                        "deadband_velocity": [0.0, 0.0, 0.0],
                        "velocity_timeout": 0.5,
                    },
                ],
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
    )
