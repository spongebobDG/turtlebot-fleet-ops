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
    assert "scan_topic: /scan" in nav2_rewrites
    assert "odom_topic: /odom" in nav2_rewrites
    assert '"tb1_nav2_rewrites.yaml"' in launch
    assert 'src="/cmd_vel"' in launch
    assert 'src="cmd_vel_smoothed"' in launch
    assert 'dst="/motion/navigation/cmd_vel"' in launch
    assert 'LaunchConfiguration("use_sim_time")' in launch
    assert 'default_value="false"' in launch
    assert '"use_composition": "False"' in launch
    assert '"use_respawn": "True"' in launch


def test_mapping_supports_simulation_without_changing_real_default() -> None:
    launch = (PACKAGE_ROOT / "launch" / "tb1_mapping.launch.py").read_text()

    assert 'LaunchConfiguration("use_sim_time")' in launch
    assert 'default_value="false"' in launch
    assert '"use_sim_time": use_sim_time' in launch


def test_mapping_and_navigation_systemd_profiles_are_mutually_exclusive(
) -> None:
    units = REPOSITORY_ROOT / "infra" / "systemd" / "user"
    mapping = (units / "tb1-mapping.service").read_text()
    navigation = (units / "tb1-navigation.service").read_text()

    assert "Conflicts=tb1-navigation.service" in mapping
    assert "Conflicts=tb1-mapping.service" in navigation
    assert "ExecStartPre=/usr/bin/test -r %h/.local/share/" in navigation


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

    assert "output_topic: /cmd_vel" in watchdog_config
    assert "output_topic: /safety/cmd_vel_in" in navigation_config
    assert 'src="/cmd_vel"' in navigation_launch
    assert 'src="cmd_vel_smoothed"' in navigation_launch
    assert 'dst="/motion/navigation/cmd_vel"' in navigation_launch
