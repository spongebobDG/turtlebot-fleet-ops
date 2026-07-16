import threading
import time

from nav2_msgs.action import NavigateToPose
import rclpy
from rclpy.action import ActionServer, CancelResponse
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool

from fleet_gateway.ros_node import FleetGatewayNode


class FakeNavigateToPoseServer(Node):

    def __init__(self):
        super().__init__("fake_navigate_to_pose_server")
        estop_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.estop_publisher = self.create_publisher(
            Bool,
            "/safety/estop_active",
            estop_qos,
        )
        self.estop_publisher.publish(Bool(data=False))
        self.server = ActionServer(
            self,
            NavigateToPose,
            "/navigate_to_pose",
            execute_callback=self.execute,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
        )

    def execute(self, goal_handle):
        feedback = NavigateToPose.Feedback()
        feedback.current_pose.header.frame_id = "map"
        feedback.current_pose.pose.position.x = 0.25
        feedback.distance_remaining = 0.75
        feedback.estimated_time_remaining.sec = 2
        goal_handle.publish_feedback(feedback)

        if goal_handle.request.pose.pose.position.x < 0.0:
            goal_handle.abort()
            return NavigateToPose.Result()

        should_wait = goal_handle.request.pose.pose.position.x >= 5.0
        if should_wait:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    return NavigateToPose.Result()
                time.sleep(0.01)
            goal_handle.abort()
            return NavigateToPose.Result()

        goal_handle.succeed()
        return NavigateToPose.Result()

    def destroy_node(self):
        self.server.destroy()
        return super().destroy_node()


def wait_for_status(gateway, expected, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        navigation = gateway.get_navigation("tb1")
        if navigation is not None and navigation["status"] == expected:
            return navigation
        time.sleep(0.02)
    raise AssertionError(f"navigation did not reach {expected}")


def send(gateway, x, timeout_sec=3.0):
    return gateway.send_navigation_goal(
        "tb1",
        {"x": x, "y": 0.0, "yaw": 0.0, "frame_id": "map"},
        timeout_sec,
    )


def wait_for_safety_gate(gateway, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if gateway._navigation_safety_failure("tb1") is None:
            return
        time.sleep(0.02)
    raise AssertionError("gateway did not receive released e-stop status")


def test_real_ros_action_success_cancel_and_timeout_flow():
    rclpy.init()
    server = FakeNavigateToPoseServer()
    gateway = FleetGatewayNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(server)
    executor.add_node(gateway)
    unknown = gateway._navigation_safety_failure("tb1")
    assert unknown is not None
    assert unknown["code"] == "estop_state_unknown"
    gateway._estop_states["tb1"] = (False, time.monotonic() - 3.0)
    stale = gateway._navigation_safety_failure("tb1")
    assert stale is not None
    assert stale["code"] == "estop_state_stale"
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()

    try:
        wait_for_safety_gate(gateway)
        success = send(gateway, 1.0)
        assert success["success"] is True
        succeeded = wait_for_status(gateway, "SUCCEEDED")
        assert succeeded["feedback"]["distance_remaining"] == 0.75

        running = send(gateway, 5.0)
        assert running["status"] == "RUNNING"
        canceled = gateway.cancel_navigation("tb1")
        assert canceled["success"] is True
        wait_for_status(gateway, "CANCELED")

        timed = send(gateway, 6.0, timeout_sec=0.4)
        assert timed["success"] is True
        timeout = wait_for_status(gateway, "TIMEOUT")
        assert timeout["timeout_requested"] is True

        gateway._record_estop_state("tb1", True)
        blocked_retry = gateway.retry_navigation("tb1")
        assert blocked_retry["code"] == "estop_active"

        gateway._record_estop_state("tb1", False)
        retried = gateway.retry_navigation("tb1")
        assert retried["success"] is True
        assert retried["retry_count"] == 1
        assert retried["retried_from_goal_id"] == timed["goal_id"]
        gateway.cancel_navigation("tb1")
        wait_for_status(gateway, "CANCELED")
    finally:
        executor.shutdown(timeout_sec=2.0)
        server.destroy_node()
        gateway.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        thread.join(timeout=2.0)
