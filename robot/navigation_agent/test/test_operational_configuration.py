"""Regression checks for the safety-critical TB1 operating profiles."""

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_navigation_timeouts_topics_and_velocity_limits_are_pinned() -> None:
    agent_config = (PACKAGE_ROOT / "config" / "tb1.yaml").read_text()
    nav2_rewrites = (
        PACKAGE_ROOT / "config" / "tb1_nav2_rewrites.yaml"
    ).read_text()
    launch = (PACKAGE_ROOT / "launch" / "tb1_navigation.launch.py").read_text()
    nav2_launch = (
        PACKAGE_ROOT / "launch" / "tb1_nav2_navigation.launch.py"
    ).read_text()
    scan_normalizer = (
        PACKAGE_ROOT / "config" / "tb1_scan_normalizer.yaml"
    ).read_text()

    assert "lease_timeout_sec: 2.0" in agent_config
    assert "nav2_unavailable_timeout_sec: 1.0" in agent_config
    assert "goal_progress_timeout_sec: 20.0" in agent_config
    assert "goal_feedback_timeout_sec: 3.0" in agent_config
    assert "goal_max_duration_sec: 180.0" in agent_config
    assert "goal_distance_progress_m: 0.05" in agent_config
    assert "goal_yaw_progress_rad: 0.1" in agent_config
    assert "navigation_min_clearance_m: 0.19" in agent_config
    assert "nav2_lifecycle_service: /bt_navigator/get_state" in agent_config
    assert "authorization_timeout_sec: 0.5" in agent_config
    assert "navigation_input_topic: /motion/navigation/cmd_vel" in agent_config
    assert "output_topic: /safety/cmd_vel_in" in agent_config
    assert "mode_service: /tb1/navigation/set_motion_mode" in agent_config
    assert "max_vel_x: 0.05" in nav2_rewrites
    assert "max_speed_xy: 0.05" in nav2_rewrites
    assert "max_vel_theta: 0.22" in nav2_rewrites
    assert "max_rotational_vel: 0.22" in nav2_rewrites
    assert "min_rotational_vel: 0.05" in nav2_rewrites
    assert "min_speed_xy: 0.02" in nav2_rewrites
    assert "min_speed_theta: 0.05" in nav2_rewrites
    assert "base_frame_id: base_footprint" in nav2_rewrites
    assert "robot_base_frame: base_link" in nav2_rewrites
    assert "scan_topic: /scan_normalized" in nav2_rewrites
    assert "odom_topic: /odom" in nav2_rewrites
    assert "bt_loop_duration: 100" in nav2_rewrites
    assert "default_server_timeout: 2000" in nav2_rewrites
    assert "controller_frequency: 5.0" in nav2_rewrites
    assert "debug_trajectory_details: false" in nav2_rewrites
    assert "vx_samples: 10" in nav2_rewrites
    assert "vtheta_samples: 20" in nav2_rewrites
    assert "sim_time: 1.0" in nav2_rewrites
    assert "acc_lim_x: 0.08" in nav2_rewrites
    assert "acc_lim_theta: 0.6" in nav2_rewrites
    assert "decel_lim_x: -0.12" in nav2_rewrites
    assert "decel_lim_theta: -0.8" in nav2_rewrites
    assert "update_min_d: 0.05" in nav2_rewrites
    assert "update_min_a: 0.05" in nav2_rewrites
    assert "robot_radius: 0.14" in nav2_rewrites
    assert "inflation_radius: 0.19" in nav2_rewrites
    assert "cost_scaling_factor: 3.0" in nav2_rewrites
    assert "xy_goal_tolerance: 0.10" in nav2_rewrites
    assert "yaw_goal_tolerance: 0.15" in nav2_rewrites
    assert '"smoothing_frequency": 20.0' in nav2_launch
    assert '"max_velocity": [0.05, 0.0, 0.22]' in nav2_launch
    assert '"max_accel": [0.08, 0.0, 0.6]' in nav2_launch
    assert '"max_decel": [-0.12, 0.0, -0.8]' in nav2_launch
    assert '"max_rotational_vel": 0.22' in nav2_launch
    assert '"min_rotational_vel": 0.05' in nav2_launch
    assert '"rotational_acc_lim": 0.6' in nav2_launch
    assert '"nav2_controller::PoseProgressChecker"' in nav2_launch
    assert '"progress_checker.required_movement_angle": 0.1' in nav2_launch
    assert (
        '"nav2_rotation_shim_controller::"' in nav2_launch
        and '"RotationShimController"' in nav2_launch
    )
    assert '"FollowPath.primary_controller": (' in nav2_launch
    assert '"dwb_core::DWBLocalPlanner"' in nav2_launch
    assert '"FollowPath.angular_dist_threshold": 0.6' in nav2_launch
    assert '"FollowPath.angular_disengage_threshold": 0.35' in nav2_launch
    assert '"FollowPath.forward_sampling_distance": 0.15' in nav2_launch
    assert '"FollowPath.rotate_to_heading_angular_vel": 0.18' in nav2_launch
    assert '"FollowPath.max_angular_accel": 0.6' in nav2_launch
    assert '"FollowPath.rotate_to_goal_heading": True' in nav2_launch
    assert '"FollowPath.critics": [' in nav2_launch
    assert '"RotateToGoal"' not in nav2_launch
    assert '"GoalAlign"' not in nav2_launch
    assert '"tb1_nav2_rewrites.yaml"' in launch
    assert '"localization_launch.py"' in launch
    assert '"tb1_nav2_navigation.launch.py"' in launch
    assert "SetRemap" not in launch
    assert '"bringup_launch.py"' not in launch
    assert nav2_launch.count('("cmd_vel", "cmd_vel_nav")') == 3
    assert '("cmd_vel", NAVIGATION_CMD_TOPIC)' not in nav2_launch
    assert '("cmd_vel_smoothed", NAVIGATION_CMD_TOPIC)' in nav2_launch
    assert '("/scan", "/scan_normalized")' in nav2_launch
    assert 'NAVIGATION_CMD_TOPIC = "/motion/navigation/cmd_vel"' in (
        nav2_launch
    )
    assert 'LaunchConfiguration("use_sim_time")' in launch
    assert 'default_value="false"' in launch
    assert '"use_composition": "False"' in launch
    assert '"use_respawn": "True"' in launch
    assert '"tb1_scan_normalizer.yaml"' in launch
    assert "angle_offset_rad: 3.141592653589793" in scan_normalizer


def test_mapping_supports_simulation_without_changing_real_default() -> None:
    launch = (PACKAGE_ROOT / "launch" / "tb1_mapping.launch.py").read_text()

    assert 'LaunchConfiguration("use_sim_time")' in launch
    assert 'default_value="false"' in launch
    assert '"use_sim_time": use_sim_time' in launch
    assert '"tb1_scan_normalizer.yaml"' in launch
    slam_config = (PACKAGE_ROOT / "config" / "tb1_slam.yaml").read_text()
    assert "scan_topic: /scan_normalized" in slam_config
    assert "scan_queue_size: 10" in slam_config
    assert "minimum_travel_distance: 0.05" in slam_config
    setup = (PACKAGE_ROOT / "setup.py").read_text()
    supervised = (
        PACKAGE_ROOT
        / "navigation_agent"
        / "supervised_motion.py"
    ).read_text()
    assert "supervised_motion = navigation_agent.supervised_motion:main" in (
        setup
    )
    assert 'declare_parameter("input_topic", "/motion/manual/cmd_vel")' in (
        supervised
    )


def test_robotless_fixture_emulates_tb1_raw_scan_axis() -> None:
    fixture = (
        REPOSITORY_ROOT / "infra" / "navigation" / "robotless_fixture.py"
    ).read_text()

    assert "TB1_RAW_SCAN_YAW_OFFSET_RAD = math.pi" in fixture
    assert "sensor_yaw_rad: float = TB1_RAW_SCAN_YAW_OFFSET_RAD" in fixture
    assert "index * increment + sensor_yaw_rad" in fixture


def test_mapping_and_navigation_systemd_profiles_are_mutually_exclusive(
) -> None:
    units = REPOSITORY_ROOT / "infra" / "systemd" / "user"
    mapping = (units / "tb1-mapping.service").read_text()
    navigation = (units / "tb1-navigation.service").read_text()

    assert "Conflicts=tb1-navigation.service" in mapping
    assert "Conflicts=tb1-mapping.service" in navigation
    assert "ExecStartPre=/usr/bin/test -r %h/.local/share/" in navigation


def test_tb1_ros_services_wait_for_an_operating_network() -> None:
    units = REPOSITORY_ROOT / "infra" / "systemd" / "user"
    runtime_units = (
        "tb1-bringup.service",
        "tb1-safety-watchdog.service",
        "tb1-robot-agent.service",
        "tb1-zenoh-bridge.service",
        "tb1-mapping.service",
        "tb1-navigation.service",
    )
    network_unit = (units / "tb1-network-ready.service").read_text()
    wait_script = (
        REPOSITORY_ROOT / "scripts" / "tb1" / "wait_network_ready.sh"
    ).read_text()

    assert "Type=oneshot" in network_unit
    assert "TimeoutStartSec=0" in network_unit
    assert "wait_network_ready.sh" in network_unit
    assert "ip -4 route show default" in wait_script
    assert "scope global" in wait_script
    for unit_name in runtime_units:
        unit = (units / unit_name).read_text()
        assert "After=" in unit and "tb1-network-ready.service" in unit
        assert "Wants=" in unit and "tb1-network-ready.service" in unit


def test_tb1_acceptance_tests_are_serialized_and_scoped() -> None:
    deploy = (
        REPOSITORY_ROOT / "scripts" / "tb1" / "deploy_acceptance.sh"
    ).read_text()

    assert "--executor sequential" in deploy
    assert '--test-result-base "build/${package}"' in deploy
    assert "Install all eight TB1 user units" in deploy


def test_process_recovery_preserves_fail_closed_motion_ownership() -> None:
    units = REPOSITORY_ROOT / "infra" / "systemd" / "user"
    navigation_unit = (units / "tb1-navigation.service").read_text()
    navigation_launch = (
        PACKAGE_ROOT / "launch" / "tb1_navigation.launch.py"
    ).read_text()
    watchdog_launch = (
        REPOSITORY_ROOT
        / "robot"
        / "safety_watchdog"
        / "launch"
        / "safety_watchdog.launch.py"
    ).read_text()

    assert "OnProcessExit" in navigation_launch
    assert 'reason="navigation agent exited"' in navigation_launch
    assert "respawn=False" in navigation_launch
    assert "Restart=always" in navigation_unit
    assert "try-restart tb1-zenoh-bridge.service" in navigation_unit
    assert watchdog_launch.count("respawn=True") == 2
    assert watchdog_launch.count("respawn_delay=0.0") == 2
    assert 'package="safety_watchdog_guard"' in watchdog_launch
    assert 'name="safety_watchdog_policy"' in watchdog_launch


def test_map_save_preserves_unknown_cells_and_validates_artifacts() -> None:
    save_script = (
        REPOSITORY_ROOT / "infra" / "navigation" / "save-tb1-map.sh"
    ).read_text()

    assert "--free 0.196" in save_script
    assert "--occ 0.65" in save_script
    assert "navigation_agent validate_map" in save_script
    assert "--require-pose-graph" in save_script


def test_only_watchdog_owns_the_real_velocity_topic() -> None:
    watchdog_config = (
        REPOSITORY_ROOT
        / "robot"
        / "safety_watchdog"
        / "config"
        / "tb1.yaml"
    ).read_text()
    navigation_config = (PACKAGE_ROOT / "config" / "tb1.yaml").read_text()
    navigation_launch = (
        PACKAGE_ROOT / "launch" / "tb1_navigation.launch.py"
    ).read_text()
    nav2_launch = (
        PACKAGE_ROOT / "launch" / "tb1_nav2_navigation.launch.py"
    ).read_text()

    assert "output_topic: /safety/watchdog_cmd_vel" in watchdog_config
    assert watchdog_config.count("output_topic: /cmd_vel") == 1
    assert watchdog_config.count(
        "/safety/watchdog_guard_restarted"
    ) == 2
    assert "output_topic: /safety/cmd_vel_in" in navigation_config
    assert '"tb1_nav2_navigation.launch.py"' in navigation_launch
    assert nav2_launch.count('("cmd_vel", "cmd_vel_nav")') == 3
    assert '("cmd_vel", NAVIGATION_CMD_TOPIC)' not in nav2_launch
    assert '("cmd_vel_smoothed", NAVIGATION_CMD_TOPIC)' in nav2_launch
