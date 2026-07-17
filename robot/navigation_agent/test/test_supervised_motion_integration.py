"""Exercise supervised motion against an in-process ROS safety graph."""

import math
import threading
import time

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import pytest
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool
from std_srvs.srv import SetBool

from navigation_agent.pose_checkpoint import load_pose_checkpoint
from navigation_agent.pose_checkpoint import PoseCheckpoint
from navigation_agent.pose_checkpoint import save_pose_checkpoint
from navigation_agent.supervised_motion import SupervisedMotion


class FakeWatchdog(Node):
    """Publish final velocity while implementing the e-stop service."""

    def __init__(self) -> None:
        super().__init__("safety_watchdog")
        self.estop_active = True
        self.release_count = 0
        self._linear = 0.0
        self._angular = 0.0
        self._publisher = self.create_publisher(Twist, "/cmd_vel", 10)
        status_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self._status_publisher = self.create_publisher(
            Bool,
            "/safety/estop_active",
            status_qos,
        )
        self._subscription = self.create_subscription(
            Twist,
            "/safety/cmd_vel_in",
            self._on_input,
            10,
        )
        self._service = self.create_service(
            SetBool,
            "/test/navigation_agent/set_estop",
            self._on_estop,
        )
        self._timer = self.create_timer(0.02, self._publish)
        self._publish_status()

    def _on_input(self, message: Twist) -> None:
        self._linear = message.linear.x
        self._angular = message.angular.z

    def _on_estop(self, request, response):
        self.estop_active = request.data
        if not request.data:
            self.release_count += 1
        self._publish_status()
        response.success = True
        response.message = "fake e-stop updated"
        return response

    def _publish_status(self) -> None:
        status = Bool()
        status.data = self.estop_active
        self._status_publisher.publish(status)

    def _publish(self) -> None:
        output = Twist()
        if not self.estop_active:
            output.linear.x = self._linear
            output.angular.z = self._angular
        self._publisher.publish(output)


class FakeTurtleBot(Node):
    """Integrate final velocity and publish fresh odometry and scans."""

    def __init__(self) -> None:
        super().__init__("turtlebot3_node")
        self.x = 0.0
        self.y = 0.0
        self.yaw = 0.0
        self.scan_range = 1.0
        self._linear = 0.0
        self._angular = 0.0
        self._last_update = time.monotonic()
        self._subscription = self.create_subscription(
            Twist,
            "/cmd_vel",
            self._on_command,
            10,
        )
        self._odom_publisher = self.create_publisher(
            Odometry,
            "/odom",
            10,
        )
        self._scan_publisher = self.create_publisher(
            LaserScan,
            "/scan_normalized",
            qos_profile_sensor_data,
        )
        self._timer = self.create_timer(0.02, self._update)

    def _on_command(self, message: Twist) -> None:
        self._linear = message.linear.x
        self._angular = message.angular.z

    def _update(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_update
        self._last_update = now
        self.x += self._linear * math.cos(self.yaw) * elapsed
        self.y += self._linear * math.sin(self.yaw) * elapsed
        self.yaw += self._angular * elapsed

        odom = Odometry()
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_footprint"
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.orientation.z = math.sin(self.yaw / 2.0)
        odom.pose.pose.orientation.w = math.cos(self.yaw / 2.0)
        odom.twist.twist.linear.x = self._linear
        odom.twist.twist.angular.z = self._angular
        self._odom_publisher.publish(odom)

        scan = LaserScan()
        scan.angle_min = 0.0
        scan.angle_increment = math.tau / 360.0
        scan.angle_max = scan.angle_increment * 359
        scan.range_min = 0.05
        scan.range_max = 12.0
        scan.ranges = [self.scan_range] * 360
        self._scan_publisher.publish(scan)


def _motion_parameters() -> list:
    return [
        Parameter("input_topic", value="/safety/cmd_vel_in"),
        Parameter("mode", value="translate"),
        Parameter("target_distance_m", value=0.02),
        Parameter("speed", value=0.03),
        Parameter("timeout_sec", value=3.0),
        Parameter("preflight_sec", value=1.0),
        Parameter(
            "estop_service",
            value="/test/navigation_agent/set_estop",
        ),
        Parameter("pose_checkpoint_enabled", value=False),
    ]


def _start_fake_graph():
    watchdog = FakeWatchdog()
    robot = FakeTurtleBot()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(watchdog)
    executor.add_node(robot)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    time.sleep(0.5)
    return watchdog, robot, executor, thread


def _stop_fake_graph(watchdog, robot, executor, thread) -> None:
    executor.shutdown()
    thread.join(timeout=2.0)
    watchdog.destroy_node()
    robot.destroy_node()


def test_supervised_translation_stops_with_estop() -> None:
    rclpy.init()
    watchdog, robot, executor, thread = _start_fake_graph()
    motion = SupervisedMotion(parameter_overrides=_motion_parameters())
    try:
        assert motion.run_once() is True
        assert watchdog.estop_active is True
        assert robot.x >= 0.02
        assert robot.x < 0.04
        assert robot.y == 0.0
    finally:
        motion.destroy_node()
        _stop_fake_graph(watchdog, robot, executor, thread)
        rclpy.shutdown()


def test_dry_run_never_releases_estop_or_moves() -> None:
    rclpy.init()
    watchdog, robot, executor, thread = _start_fake_graph()
    parameters = _motion_parameters()
    parameters.append(Parameter("dry_run", value=True))
    motion = SupervisedMotion(parameter_overrides=parameters)
    try:
        assert motion.run_once() is True
        assert watchdog.estop_active is True
        assert watchdog.release_count == 0
        assert robot.x == 0.0
        assert robot.y == 0.0
    finally:
        motion.destroy_node()
        _stop_fake_graph(watchdog, robot, executor, thread)
        rclpy.shutdown()


def test_supervised_motion_rejects_teleop_publisher() -> None:
    rclpy.init()
    watchdog, robot, executor, thread = _start_fake_graph()
    teleop = Node("teleop_keyboard")
    teleop_publisher = teleop.create_publisher(
        Twist,
        "/safety/cmd_vel_in",
        10,
    )
    executor.add_node(teleop)
    motion = SupervisedMotion(parameter_overrides=_motion_parameters())
    try:
        time.sleep(0.5)
        assert motion.run_once() is False
        assert watchdog.estop_active is True
        assert robot.x == 0.0
        assert teleop_publisher is not None
    finally:
        motion.destroy_node()
        executor.remove_node(teleop)
        teleop.destroy_node()
        _stop_fake_graph(watchdog, robot, executor, thread)
        rclpy.shutdown()


def test_supervised_motion_rejects_low_clearance() -> None:
    rclpy.init()
    watchdog, robot, executor, thread = _start_fake_graph()
    robot.scan_range = 0.20
    motion = SupervisedMotion(parameter_overrides=_motion_parameters())
    try:
        assert motion.run_once() is False
        assert watchdog.estop_active is True
        assert robot.x == 0.0
        assert robot.y == 0.0
    finally:
        motion.destroy_node()
        _stop_fake_graph(watchdog, robot, executor, thread)
        rclpy.shutdown()


def _enable_checkpoint(parameters, path, reset=False) -> None:
    for index, parameter in enumerate(parameters):
        if parameter.name == "pose_checkpoint_enabled":
            parameters[index] = Parameter(
                "pose_checkpoint_enabled",
                value=True,
            )
            break
    else:
        raise AssertionError("checkpoint parameter is missing")
    parameters.extend(
        [
            Parameter("pose_checkpoint_path", value=str(path)),
            Parameter("reset_pose_checkpoint", value=reset),
        ]
    )


def test_pose_checkpoint_blocks_uncommanded_rotation(tmp_path) -> None:
    rclpy.init()
    watchdog, robot, executor, thread = _start_fake_graph()
    path = tmp_path / "pose.json"
    save_pose_checkpoint(
        path,
        PoseCheckpoint(0.0, 0.0, 0.0, "odom", "base_footprint"),
    )
    robot.yaw = math.pi / 2.0
    parameters = _motion_parameters()
    _enable_checkpoint(parameters, path)
    motion = SupervisedMotion(parameter_overrides=parameters)
    try:
        assert motion.run_once() is False
        assert watchdog.estop_active is True
        assert watchdog.release_count == 0
        assert robot.x == 0.0
    finally:
        motion.destroy_node()
        _stop_fake_graph(watchdog, robot, executor, thread)
        rclpy.shutdown()


def test_successful_motion_updates_pose_checkpoint(tmp_path) -> None:
    rclpy.init()
    watchdog, robot, executor, thread = _start_fake_graph()
    path = tmp_path / "pose.json"
    save_pose_checkpoint(
        path,
        PoseCheckpoint(0.0, 0.0, 0.0, "odom", "base_footprint"),
    )
    parameters = _motion_parameters()
    _enable_checkpoint(parameters, path)
    motion = SupervisedMotion(parameter_overrides=parameters)
    try:
        assert motion.run_once() is True
        saved = load_pose_checkpoint(path)
        assert saved is not None
        assert saved.x >= 0.02
        assert saved.y == pytest.approx(0.0)
        assert saved.yaw == pytest.approx(0.0)
    finally:
        motion.destroy_node()
        _stop_fake_graph(watchdog, robot, executor, thread)
        rclpy.shutdown()


def test_dry_run_can_reset_pose_checkpoint_without_motion(tmp_path) -> None:
    rclpy.init()
    watchdog, robot, executor, thread = _start_fake_graph()
    path = tmp_path / "pose.json"
    save_pose_checkpoint(
        path,
        PoseCheckpoint(0.0, 0.0, 0.0, "odom", "base_footprint"),
    )
    robot.yaw = math.pi / 2.0
    parameters = _motion_parameters()
    parameters.append(Parameter("dry_run", value=True))
    _enable_checkpoint(parameters, path, reset=True)
    motion = SupervisedMotion(parameter_overrides=parameters)
    try:
        assert motion.run_once() is True
        saved = load_pose_checkpoint(path)
        assert saved is not None
        assert saved.yaw == pytest.approx(math.pi / 2.0)
        assert watchdog.estop_active is True
        assert watchdog.release_count == 0
        assert robot.x == 0.0
    finally:
        motion.destroy_node()
        _stop_fake_graph(watchdog, robot, executor, thread)
        rclpy.shutdown()


def test_failed_motion_leaves_checkpoint_blocked(tmp_path) -> None:
    rclpy.init()
    watchdog, robot, executor, thread = _start_fake_graph()
    robot.scan_range = 0.20
    path = tmp_path / "pose.json"
    save_pose_checkpoint(
        path,
        PoseCheckpoint(0.0, 0.0, 0.0, "odom", "base_footprint"),
    )
    parameters = _motion_parameters()
    _enable_checkpoint(parameters, path)
    motion = SupervisedMotion(parameter_overrides=parameters)
    try:
        assert motion.run_once() is False
        assert watchdog.estop_active is True
        assert watchdog.release_count == 1
        with pytest.raises(RuntimeError, match="did not commit"):
            load_pose_checkpoint(path)
    finally:
        motion.destroy_node()
        _stop_fake_graph(watchdog, robot, executor, thread)
        rclpy.shutdown()
