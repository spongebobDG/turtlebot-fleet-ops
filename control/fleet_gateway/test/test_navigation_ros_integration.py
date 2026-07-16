import threading
import time

from nav2_msgs.action import NavigateToPose
import rclpy
from rclpy.action import ActionServer, CancelResponse
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from fleet_gateway.ros_node import FleetGatewayNode


class FakeNavigateToPoseServer(Node):

    def __init__(self):
        super().__init__("fake_navigate_to_pose_server")
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


def test_real_ros_action_success_cancel_and_timeout_flow():
    rclpy.init()
    server = FakeNavigateToPoseServer()
    gateway = FleetGatewayNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(server)
    executor.add_node(gateway)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()

    try:
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
    finally:
        executor.shutdown(timeout_sec=2.0)
        server.destroy_node()
        gateway.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        thread.join(timeout=2.0)
