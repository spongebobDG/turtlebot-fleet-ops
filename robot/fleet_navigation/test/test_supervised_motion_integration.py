"""Exercise supervised motion against an in-process ROS safety graph."""

import math
import threading
import time

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_srvs.srv import SetBool

from fleet_navigation.supervised_motion import SupervisedMotion


class FakeWatchdog(Node):
    """Publish final velocity while implementing the e-stop service."""

    def __init__(self) -> None:
        super().__init__("safety_watchdog")
        self.estop_active = True
        self._linear = 0.0
        self._angular = 0.0
        self._publisher = self.create_publisher(Twist, "/cmd_vel", 10)
        self._subscription = self.create_subscription(
            Twist,
            "/safety/cmd_vel_in",
            self._on_input,
            10,
        )
        self._service = self.create_service(
            SetBool,
            "/safety_watchdog/set_estop",
            self._on_estop,
        )
        self._timer = self.create_timer(0.02, self._publish)

    def _on_input(self, message: Twist) -> None:
        self._linear = message.linear.x
        self._angular = message.angular.z

    def _on_estop(self, request, response):
        self.estop_active = request.data
        response.success = True
        response.message = "fake e-stop updated"
        return response

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
        scan.ranges = [1.0] * 360
        self._scan_publisher.publish(scan)


def _motion_parameters() -> list:
    return [
        Parameter("mode", value="translate"),
        Parameter("target_distance_m", value=0.02),
        Parameter("speed", value=0.03),
        Parameter("timeout_sec", value=3.0),
        Parameter("preflight_sec", value=1.0),
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
