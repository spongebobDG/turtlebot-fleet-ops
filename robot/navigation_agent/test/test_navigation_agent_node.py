"""ROS integration tests using a controllable fake Nav2 action server."""

import threading
import time
from typing import Callable, List

from action_msgs.msg import GoalStatus
from action_msgs.srv import CancelGoal
from fleet_interfaces.action import NavigateRobot
from fleet_interfaces.msg import (
    NavigationLease,
    NavigationStatus,
    RobotStatus,
    SafetyStatus,
)
from fleet_interfaces.srv import SetInitialPose, SetMotionMode
from geometry_msgs.msg import PoseWithCovarianceStamped
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
import rclpy
from rclpy.action import (
    ActionClient,
    ActionServer,
    CancelResponse,
    GoalResponse,
)
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from navigation_agent.agent_node import NavigationAgent
from navigation_agent.model import MODE_IDLE, MODE_NAVIGATION


def _wait_until(
    condition: Callable[[], bool],
    timeout_sec: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def _future_result(future, timeout_sec: float = 3.0):
    _wait_until(future.done, timeout_sec)
    return future.result()


class FakeNav2Server(Node):
    """Return success, failure, or wait for cancellation on demand."""

    def __init__(self) -> None:
        super().__init__("fake_nav2_server")
        self.mode = "succeed"
        self.received_goals = 0
        self.release_ignored_goal = threading.Event()
        self._server = ActionServer(
            self,
            NavigateToPose,
            "/test/nav2/navigate_to_pose",
            execute_callback=self._execute,
            goal_callback=self._on_goal,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=ReentrantCallbackGroup(),
        )

    def _on_goal(self, _) -> GoalResponse:
        return (
            GoalResponse.REJECT
            if self.mode == "reject"
            else GoalResponse.ACCEPT
        )

    def _execute(self, goal_handle) -> NavigateToPose.Result:
        self.received_goals += 1
        feedback = NavigateToPose.Feedback()
        feedback.current_pose.header.frame_id = "map"
        feedback.current_pose.pose.orientation.w = 1.0
        feedback.distance_remaining = 0.5
        feedback.number_of_recoveries = 1
        goal_handle.publish_feedback(feedback)

        if self.mode in {"hold", "stalled"}:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    return NavigateToPose.Result()
                if self.mode == "stalled":
                    goal_handle.publish_feedback(feedback)
                time.sleep(0.01)
            goal_handle.abort()
            return NavigateToPose.Result()
        if self.mode == "ignore_cancel":
            self.release_ignored_goal.wait(timeout=5.0)
            goal_handle.abort()
            return NavigateToPose.Result()
        if self.mode == "fail":
            goal_handle.abort()
            return NavigateToPose.Result()
        goal_handle.succeed()
        return NavigateToPose.Result()


def _goal(command_id: str) -> NavigateRobot.Goal:
    goal = NavigateRobot.Goal()
    goal.command_id = command_id
    goal.target_pose.header.frame_id = "map"
    goal.target_pose.pose.position.x = 0.25
    goal.target_pose.pose.position.y = 0.25
    goal.target_pose.pose.orientation.w = 1.0
    return goal


def test_navigation_agent_success_cancel_failure_and_lease_expiry() -> None:
    rclpy.init()
    fake_nav2 = FakeNav2Server()
    probe = Node("navigation_agent_test_probe")
    modes: List[int] = []
    residual_cancel_requests = []
    nav2_lifecycle = {"active": False}

    def set_mode(request, response):
        modes.append(int(request.mode))
        response.success = True
        response.message = "accepted"
        return response

    def cancel_all(request, response):
        residual_cancel_requests.append(request)
        response.return_code = (
            CancelGoal.Response.ERROR_REJECTED
            if len(residual_cancel_requests) == 1
            else CancelGoal.Response.ERROR_NONE
        )
        return response

    def get_nav2_state(request, response):
        del request
        response.current_state.id = (
            State.PRIMARY_STATE_ACTIVE
            if nav2_lifecycle["active"]
            else State.PRIMARY_STATE_INACTIVE
        )
        return response

    mode_service = probe.create_service(
        SetMotionMode,
        "/test/motion/set_mode",
        set_mode,
    )
    cancel_all_service = probe.create_service(
        CancelGoal,
        "/test/nav2/cancel_all",
        cancel_all,
    )
    lifecycle_service = probe.create_service(
        GetState,
        "/test/nav2/get_state",
        get_nav2_state,
    )
    agent = NavigationAgent(
        parameter_overrides=[
            Parameter("robot_id", value="tb1"),
            Parameter("command_action", value="/test/tb1/navigation/navigate"),
            Parameter("lease_topic", value="/test/fleet/navigation_lease"),
            Parameter("status_topic", value="/test/fleet/navigation_status"),
            Parameter("robot_status_topic", value="/test/fleet/robot_status"),
            Parameter("safety_status_topic", value="/test/fleet/safety_status"),
            Parameter(
                "initial_pose_service",
                value="/test/tb1/navigation/set_initial_pose",
            ),
            Parameter("motion_mode_service", value="/test/motion/set_mode"),
            Parameter("authorization_topic", value="/test/motion/authorized"),
            Parameter("nav2_action", value="/test/nav2/navigate_to_pose"),
            Parameter(
                "nav2_cancel_service",
                value="/test/nav2/cancel_all",
            ),
            Parameter(
                "nav2_lifecycle_service",
                value="/test/nav2/get_state",
            ),
            Parameter("initial_pose_topic", value="/test/initialpose"),
            Parameter("amcl_pose_topic", value="/test/amcl_pose"),
            Parameter("map_topic", value="/test/map"),
            Parameter("lease_timeout_sec", value=0.3),
            Parameter("nav2_unavailable_timeout_sec", value=0.1),
            Parameter("goal_progress_timeout_sec", value=0.6),
            Parameter("goal_feedback_timeout_sec", value=1.0),
            Parameter("goal_max_duration_sec", value=5.0),
            Parameter("goal_distance_progress_m", value=0.05),
            Parameter("goal_yaw_progress_rad", value=0.1),
            Parameter("robot_status_timeout_sec", value=1.0),
            Parameter("safety_status_timeout_sec", value=1.0),
            Parameter("authorization_rate_hz", value=50.0),
            Parameter("status_rate_hz", value=20.0),
        ]
    )
    transient_qos = QoSProfile(
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    map_publisher = probe.create_publisher(
        OccupancyGrid,
        "/test/map",
        transient_qos,
    )
    robot_publisher = probe.create_publisher(
        RobotStatus,
        "/test/fleet/robot_status",
        10,
    )
    safety_publisher = probe.create_publisher(
        SafetyStatus,
        "/test/fleet/safety_status",
        10,
    )
    amcl_publisher = probe.create_publisher(
        PoseWithCovarianceStamped,
        "/test/amcl_pose",
        10,
    )
    lease_publisher = probe.create_publisher(
        NavigationLease,
        "/test/fleet/navigation_lease",
        10,
    )
    initial_pose_client = probe.create_client(
        SetInitialPose,
        "/test/tb1/navigation/set_initial_pose",
    )
    action_client = ActionClient(
        probe,
        NavigateRobot,
        "/test/tb1/navigation/navigate",
    )
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(fake_nav2)
    executor.add_node(probe)
    executor.add_node(agent)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    lease_renew_timer = None

    def publish_readiness() -> None:
        robot = RobotStatus()
        robot.robot_id = "tb1"
        robot.level = RobotStatus.LEVEL_OK
        robot_publisher.publish(robot)
        safety = SafetyStatus()
        safety.robot_id = "tb1"
        safety.motion_armed = True
        safety_publisher.publish(safety)
        amcl = PoseWithCovarianceStamped()
        amcl.header.frame_id = "map"
        amcl.pose.pose.position.x = 0.25
        amcl.pose.pose.position.y = 0.25
        amcl.pose.pose.orientation.w = 1.0
        amcl_publisher.publish(amcl)

    def send_goal(command_id: str, feedback_callback=None):
        return _future_result(
            action_client.send_goal_async(
                _goal(command_id),
                feedback_callback=feedback_callback,
            )
        )

    try:
        _wait_until(lambda: map_publisher.get_subscription_count() > 0)
        occupancy_map = OccupancyGrid()
        occupancy_map.header.frame_id = "map"
        occupancy_map.info.width = 2
        occupancy_map.info.height = 2
        occupancy_map.info.resolution = 1.0
        occupancy_map.info.origin.orientation.w = 1.0
        occupancy_map.data = [0, 0, 0, 0]
        map_publisher.publish(occupancy_map)
        _wait_until(lambda: agent._grid is not None)
        _wait_until(lambda: initial_pose_client.service_is_ready())
        _wait_until(lambda: action_client.server_is_ready())
        _wait_until(lambda: len(residual_cancel_requests) >= 2)

        initial = SetInitialPose.Request()
        initial.pose.header.frame_id = "map"
        initial.pose.pose.pose.position.x = 0.25
        initial.pose.pose.pose.position.y = 0.25
        initial.pose.pose.pose.orientation.w = 1.0
        initial_response = _future_result(
            initial_pose_client.call_async(initial)
        )
        assert initial_response.success
        publish_readiness()
        _wait_until(lambda: not agent._nav2_lifecycle_active)
        assert not agent._ready_for_goal(time.monotonic(), False)
        nav2_lifecycle["active"] = True
        _wait_until(
            lambda: agent._ready_for_goal(time.monotonic(), False)
        )
        with agent._lock:
            now = time.monotonic()
            agent._initial_pose_sent_at = now - 120.0
            agent._amcl_received_at = now - 60.0
        assert agent._localization_ready(time.monotonic())
        assert agent._startup_motion_idle_sent
        assert agent._startup_cancel_sent

        feedback_messages = []
        success_handle = send_goal("success", feedback_messages.append)
        assert success_handle.accepted
        lease = NavigationLease()
        lease.robot_id = "tb1"
        lease.command_id = "success"
        lease_publisher.publish(lease)
        success = _future_result(success_handle.get_result_async())
        assert success.status == GoalStatus.STATUS_SUCCEEDED
        assert success.result.outcome == NavigateRobot.Result.OUTCOME_SUCCEEDED
        _wait_until(lambda: bool(feedback_messages))
        assert feedback_messages[-1].feedback.distance_remaining == 0.5
        assert feedback_messages[-1].feedback.number_of_recoveries == 1
        assert feedback_messages[-1].feedback.lease_age_sec >= 0.0
        assert fake_nav2.received_goals == 1
        assert MODE_NAVIGATION in modes
        _wait_until(lambda: modes[-1] == MODE_IDLE)
        publish_readiness()
        time.sleep(0.1)
        assert agent._state == NavigationStatus.STATE_SUCCEEDED

        fake_nav2.mode = "reject"
        publish_readiness()
        rejected_handle = send_goal("nav2-reject")
        assert rejected_handle.accepted
        rejected = _future_result(rejected_handle.get_result_async())
        assert rejected.status == GoalStatus.STATUS_ABORTED
        assert rejected.result.outcome == NavigateRobot.Result.OUTCOME_ABORTED
        assert "rejected" in rejected.result.message

        fake_nav2.mode = "hold"
        publish_readiness()
        cancel_handle = send_goal("cancel")
        assert cancel_handle.accepted
        lease.command_id = "cancel"
        lease_publisher.publish(lease)
        cancel_response = _future_result(cancel_handle.cancel_goal_async())
        assert cancel_response.goals_canceling
        canceled = _future_result(cancel_handle.get_result_async())
        assert canceled.status == GoalStatus.STATUS_CANCELED
        assert canceled.result.outcome == NavigateRobot.Result.OUTCOME_CANCELED

        publish_readiness()
        estop_handle = send_goal("estop")
        assert estop_handle.accepted
        lease.command_id = "estop"
        lease_publisher.publish(lease)
        estop_status = SafetyStatus()
        estop_status.robot_id = "tb1"
        estop_status.estop_active = True
        estop_status.motion_armed = False
        safety_publisher.publish(estop_status)
        estop_result = _future_result(estop_handle.get_result_async())
        assert estop_result.status == GoalStatus.STATUS_ABORTED
        assert (
            estop_result.result.outcome
            == NavigateRobot.Result.OUTCOME_CANCELED
        )
        goals_after_estop = fake_nav2.received_goals
        time.sleep(0.1)
        assert fake_nav2.received_goals == goals_after_estop

        fake_nav2.mode = "fail"
        publish_readiness()
        _wait_until(
            lambda: agent._ready_for_goal(time.monotonic(), False)
        )
        failed_handle = send_goal("failure")
        assert failed_handle.accepted
        lease.command_id = "failure"
        lease_publisher.publish(lease)
        failed = _future_result(failed_handle.get_result_async())
        assert failed.status == GoalStatus.STATUS_ABORTED
        assert failed.result.outcome == NavigateRobot.Result.OUTCOME_ABORTED

        fake_nav2.mode = "hold"
        publish_readiness()
        expired_handle = send_goal("lease-expiry")
        assert expired_handle.accepted
        duplicate = send_goal("duplicate")
        assert not duplicate.accepted
        expired = _future_result(
            expired_handle.get_result_async(),
            timeout_sec=2.0,
        )
        assert expired.status == GoalStatus.STATUS_ABORTED
        assert (
            expired.result.outcome
            == NavigateRobot.Result.OUTCOME_LEASE_EXPIRED
        )

        fake_nav2.mode = "stalled"
        publish_readiness()
        stalled_handle = send_goal("stalled-progress")
        assert stalled_handle.accepted
        lease.command_id = "stalled-progress"
        lease_renew_timer = probe.create_timer(
            0.05,
            lambda: lease_publisher.publish(lease),
        )
        stalled = _future_result(
            stalled_handle.get_result_async(),
            timeout_sec=2.0,
        )
        probe.destroy_timer(lease_renew_timer)
        lease_renew_timer = None
        assert stalled.status == GoalStatus.STATUS_ABORTED
        assert stalled.result.outcome == NavigateRobot.Result.OUTCOME_ABORTED
        assert "Failed to make progress" in stalled.result.message
        _wait_until(lambda: modes[-1] == MODE_IDLE)
        assert agent._state == NavigationStatus.STATE_FAILED

        fake_nav2.mode = "ignore_cancel"
        publish_readiness()
        nav2_lost_handle = send_goal("nav2-lost")
        assert nav2_lost_handle.accepted
        lease.command_id = "nav2-lost"
        lease_publisher.publish(lease)
        _wait_until(lambda: agent._active_command_id == "nav2-lost")
        original_server_is_ready = agent._nav_client.server_is_ready
        agent._nav_client.server_is_ready = lambda: False
        nav2_lost = _future_result(
            nav2_lost_handle.get_result_async(),
            timeout_sec=2.0,
        )
        assert nav2_lost.status == GoalStatus.STATUS_ABORTED
        assert nav2_lost.result.outcome == NavigateRobot.Result.OUTCOME_ABORTED
        assert "unavailable" in nav2_lost.result.message
        agent._nav_client.server_is_ready = original_server_is_ready
        fake_nav2.release_ignored_goal.set()
    finally:
        if lease_renew_timer is not None:
            probe.destroy_timer(lease_renew_timer)
        fake_nav2.release_ignored_goal.set()
        agent.shutdown()
        executor.shutdown(timeout_sec=2.0)
        spin_thread.join(timeout=2.0)
        executor.remove_node(agent)
        executor.remove_node(probe)
        executor.remove_node(fake_nav2)
        action_client.destroy()
        probe.destroy_service(cancel_all_service)
        probe.destroy_service(lifecycle_service)
        probe.destroy_service(mode_service)
        agent.destroy_node()
        probe.destroy_node()
        fake_nav2.destroy_node()
        rclpy.shutdown()
