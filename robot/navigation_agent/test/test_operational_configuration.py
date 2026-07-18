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

    assert "lease_timeout_sec: 2.0" in agent_config
    assert "nav2_unavailable_timeout_sec: 1.0" in agent_config
    assert "nav2_lifecycle_service: /bt_navigator/get_state" in agent_config
    assert "authorization_timeout_sec: 0.5" in agent_config
    assert "navigation_input_topic: /motion/navigation/cmd_vel" in agent_config
    assert "output_topic: /safety/cmd_vel_in" in agent_config
    assert "mode_service: /tb1/navigation/set_motion_mode" in agent_config
    assert "max_vel_x: 0.05" in nav2_rewrites
    assert "max_speed_xy: 0.05" in nav2_rewrites
    assert "max_vel_theta: 0.3" in nav2_rewrites
    assert "max_rotational_vel: 0.3" in nav2_rewrites
    assert "base_frame_id: base_footprint" in nav2_rewrites
    assert "robot_base_frame: base_link" in nav2_rewrites
    assert "scan_topic: /scan_normalized" in nav2_rewrites
    assert "odom_topic: /odom" in nav2_rewrites
    assert '"tb1_nav2_rewrites.yaml"' in launch
    assert '"localization_launch.py"' in launch
    assert '"tb1_nav2_navigation.launch.py"' in launch
    assert "SetRemap" not in launch
    assert '"bringup_launch.py"' not in launch
    assert '("cmd_vel", "cmd_vel_nav")' in nav2_launch
    assert '("cmd_vel", NAVIGATION_CMD_TOPIC)' in nav2_launch
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


def test_mapping_and_navigation_systemd_profiles_are_mutually_exclusive(
) -> None:
    units = REPOSITORY_ROOT / "infra" / "systemd" / "user"
    mapping = (units / "tb1-mapping.service").read_text()
    navigation = (units / "tb1-navigation.service").read_text()

    assert "Conflicts=tb1-navigation.service" in mapping
    assert "Conflicts=tb1-mapping.service" in navigation
    assert "ExecStartPre=/usr/bin/test -r %h/.local/share/" in navigation


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
    assert "respawn=True" in watchdog_launch
    assert "respawn_delay=0.5" in watchdog_launch


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

    assert "output_topic: /cmd_vel" in watchdog_config
    assert "output_topic: /safety/cmd_vel_in" in navigation_config
    assert '"tb1_nav2_navigation.launch.py"' in navigation_launch
    assert '("cmd_vel", "cmd_vel_nav")' in nav2_launch
    assert '("cmd_vel", NAVIGATION_CMD_TOPIC)' in nav2_launch
    assert '("cmd_vel_smoothed", NAVIGATION_CMD_TOPIC)' in nav2_launch
