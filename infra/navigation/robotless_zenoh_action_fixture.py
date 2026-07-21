"""Exercise fleet navigation actions across two Zenoh-bridged ROS domains."""

import argparse
import time
from typing import Callable, Dict, List

from action_msgs.msg import GoalStatus
from fleet_interfaces.action import NavigateRobot
from fleet_interfaces.msg import (
    MappingStatus,
    NavigationLease,
    NavigationStatus,
)
from fleet_interfaces.srv import ManualCommand, SaveMap, SetOperatingProfile
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


ROBOT_ID = "tb1"
ACTION_NAME = "/tb1/navigation/navigate"
LEASE_TOPIC = "/fleet/navigation_lease"
STATUS_TOPIC = "/fleet/navigation_status"
MAPPING_STATUS_TOPIC = "/fleet/mapping_status"
MANUAL_SERVICE = "/tb1/navigation/manual_command"
PROFILE_SERVICE = "/tb1/navigation/set_operating_profile"
SAVE_MAP_SERVICE = "/tb1/navigation/save_map"


class RobotSideFixture(Node):
    """Provide a leased NavigateRobot server in the robot ROS domain."""

    def __init__(self) -> None:
        super().__init__("robotless_zenoh_action_server")
        callback_group = ReentrantCallbackGroup()
        self._leases: Dict[str, float] = {}
        self._state = NavigationStatus.STATE_READY
        self._active_command = ""
        self._profile = MappingStatus.PROFILE_NAVIGATION
        self._status_publisher = self.create_publisher(
            NavigationStatus,
            STATUS_TOPIC,
            10,
        )
        self.create_subscription(
            NavigationLease,
            LEASE_TOPIC,
            self._lease_callback,
            10,
            callback_group=callback_group,
        )
        self.create_timer(
            0.2,
            self._publish_status,
            callback_group=callback_group,
        )
        self._mapping_publisher = self.create_publisher(
            MappingStatus,
            MAPPING_STATUS_TOPIC,
            10,
        )
        self.create_service(
            ManualCommand,
            MANUAL_SERVICE,
            self._manual_command,
            callback_group=callback_group,
        )
        self.create_service(
            SetOperatingProfile,
            PROFILE_SERVICE,
            self._set_profile,
            callback_group=callback_group,
        )
        self.create_service(
            SaveMap,
            SAVE_MAP_SERVICE,
            self._save_map,
            callback_group=callback_group,
        )
        self._action_server = ActionServer(
            self,
            NavigateRobot,
            ACTION_NAME,
            execute_callback=self._execute,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            callback_group=callback_group,
        )

    @staticmethod
    def _goal_callback(_request: NavigateRobot.Goal) -> GoalResponse:
        return GoalResponse.ACCEPT

    @staticmethod
    def _cancel_callback(_goal_handle) -> CancelResponse:
        return CancelResponse.ACCEPT

    def _lease_callback(self, message: NavigationLease) -> None:
        if message.robot_id == ROBOT_ID and message.command_id:
            self._leases[message.command_id] = time.monotonic()

    def _publish_status(self) -> None:
        message = NavigationStatus()
        message.header.stamp = self.get_clock().now().to_msg()
        message.robot_id = ROBOT_ID
        message.state = self._state
        message.nav2_ready = True
        message.localization_ready = True
        message.safety_ready = True
        message.active_command_id = self._active_command
        message.message = "Zenoh robot-side fixture"
        self._status_publisher.publish(message)
        mapping = MappingStatus()
        mapping.header.stamp = message.header.stamp
        mapping.robot_id = ROBOT_ID
        mapping.profile = self._profile
        mapping.map_available = True
        mapping.message = "Zenoh robot-side profile fixture"
        self._mapping_publisher.publish(mapping)

    @staticmethod
    def _manual_command(request, response):
        response.success = bool(request.session_id.strip())
        response.message = "Manual command crossed Zenoh"
        return response

    def _set_profile(self, request, response):
        self._profile = int(request.profile)
        response.success = self._profile in {
            MappingStatus.PROFILE_IDLE,
            MappingStatus.PROFILE_MAPPING,
            MappingStatus.PROFILE_NAVIGATION,
        }
        response.active_profile = self._profile
        response.message = "Profile command crossed Zenoh"
        self._publish_status()
        return response

    def _save_map(self, _request, response):
        response.success = self._profile == MappingStatus.PROFILE_MAPPING
        response.message = "Map save crossed Zenoh"
        return response

    def _finish(
        self,
        goal_handle,
        state: int,
        outcome: int,
        message: str,
    ) -> NavigateRobot.Result:
        result = NavigateRobot.Result()
        result.outcome = outcome
        result.message = message
        if state == NavigationStatus.STATE_SUCCEEDED:
            goal_handle.succeed()
        elif state == NavigationStatus.STATE_CANCELED:
            goal_handle.canceled()
        else:
            goal_handle.abort()
        self._state = state
        self._active_command = ""
        self._publish_status()
        return result

    def _execute(self, goal_handle) -> NavigateRobot.Result:
        command_id = goal_handle.request.command_id
        self._active_command = command_id
        self._state = NavigationStatus.STATE_ACTIVE
        self._publish_status()
        started_at = time.monotonic()
        feedback_count = 0

        while time.monotonic() - started_at < 15.0:
            if goal_handle.is_cancel_requested:
                return self._finish(
                    goal_handle,
                    NavigationStatus.STATE_CANCELED,
                    NavigateRobot.Result.OUTCOME_CANCELED,
                    "Canceled across Zenoh",
                )

            lease_received_at = self._leases.get(command_id)
            if lease_received_at is None:
                time.sleep(0.05)
                continue
            if time.monotonic() - lease_received_at > 2.0:
                return self._finish(
                    goal_handle,
                    NavigationStatus.STATE_LEASE_EXPIRED,
                    NavigateRobot.Result.OUTCOME_LEASE_EXPIRED,
                    "Lease expired across Zenoh",
                )

            feedback = NavigateRobot.Feedback()
            feedback.current_pose.header.frame_id = "map"
            feedback.distance_remaining = max(
                0.0,
                1.0 - (0.25 * feedback_count),
            )
            feedback.lease_age_sec = float(
                time.monotonic() - lease_received_at
            )
            goal_handle.publish_feedback(feedback)
            feedback_count += 1
            if command_id == "zenoh-success" and feedback_count >= 3:
                return self._finish(
                    goal_handle,
                    NavigationStatus.STATE_SUCCEEDED,
                    NavigateRobot.Result.OUTCOME_SUCCEEDED,
                    "Succeeded across Zenoh",
                )
            time.sleep(0.1)

        return self._finish(
            goal_handle,
            NavigationStatus.STATE_FAILED,
            NavigateRobot.Result.OUTCOME_ABORTED,
            "Zenoh fixture timed out",
        )


class ControlSideFixture(Node):
    """Drive goal, feedback, result, cancel, lease and status from control."""

    def __init__(self) -> None:
        super().__init__("robotless_zenoh_action_client")
        self._action_client = ActionClient(
            self,
            NavigateRobot,
            ACTION_NAME,
        )
        self._lease_publisher = self.create_publisher(
            NavigationLease,
            LEASE_TOPIC,
            10,
        )
        self._states: List[int] = []
        self._mapping_profiles: List[int] = []
        self._feedback_counts: Dict[str, int] = {}
        self._leased_command = ""
        self.create_subscription(
            NavigationStatus,
            STATUS_TOPIC,
            lambda message: self._states.append(int(message.state)),
            10,
        )
        self.create_subscription(
            MappingStatus,
            MAPPING_STATUS_TOPIC,
            lambda message: self._mapping_profiles.append(
                int(message.profile)
            ),
            10,
        )
        self._manual_client = self.create_client(
            ManualCommand,
            MANUAL_SERVICE,
        )
        self._profile_client = self.create_client(
            SetOperatingProfile,
            PROFILE_SERVICE,
        )
        self._save_map_client = self.create_client(
            SaveMap,
            SAVE_MAP_SERVICE,
        )
        self.create_timer(0.1, self._publish_lease)

    def _publish_lease(self) -> None:
        if not self._leased_command:
            return
        message = NavigationLease()
        message.header.stamp = self.get_clock().now().to_msg()
        message.robot_id = ROBOT_ID
        message.command_id = self._leased_command
        self._lease_publisher.publish(message)

    def _spin_until(
        self,
        condition: Callable[[], bool],
        timeout_sec: float,
    ) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if condition():
                return
        raise AssertionError("condition was not met before timeout")

    def _wait_future(self, future, timeout_sec: float = 10.0):
        self._spin_until(future.done, timeout_sec)
        result = future.result()
        if result is None:
            raise AssertionError("ROS future completed without a result")
        return result

    def _feedback_callback(self, message) -> None:
        command_id = self._leased_command
        self._feedback_counts[command_id] = (
            self._feedback_counts.get(command_id, 0) + 1
        )
        assert message.feedback.current_pose.header.frame_id == "map"
        assert message.feedback.lease_age_sec <= 2.0

    def _send_goal(self, command_id: str):
        self._leased_command = command_id
        self._feedback_counts[command_id] = 0
        goal = NavigateRobot.Goal()
        goal.command_id = command_id
        goal.target_pose.header.stamp = self.get_clock().now().to_msg()
        goal.target_pose.header.frame_id = "map"
        goal.target_pose.pose.orientation.w = 1.0
        handle = self._wait_future(
            self._action_client.send_goal_async(
                goal,
                feedback_callback=self._feedback_callback,
            )
        )
        assert handle.accepted
        return handle

    def run(self) -> None:
        self._spin_until(
            lambda: self._action_client.server_is_ready(),
            30.0,
        )
        self._spin_until(
            lambda: NavigationStatus.STATE_READY in self._states,
            10.0,
        )

        for client in (
            self._manual_client,
            self._profile_client,
            self._save_map_client,
        ):
            self._spin_until(client.service_is_ready, 30.0)

        profile_request = SetOperatingProfile.Request()
        profile_request.profile = (
            SetOperatingProfile.Request.PROFILE_MAPPING
        )
        profile = self._wait_future(
            self._profile_client.call_async(profile_request)
        )
        assert profile.success
        assert profile.active_profile == MappingStatus.PROFILE_MAPPING
        self._spin_until(
            lambda: MappingStatus.PROFILE_MAPPING
            in self._mapping_profiles,
            5.0,
        )

        manual_request = ManualCommand.Request()
        manual_request.session_id = "zenoh-manual"
        manual_request.command.linear.x = 0.05
        manual = self._wait_future(
            self._manual_client.call_async(manual_request)
        )
        assert manual.success
        manual_request.stop = True
        stopped = self._wait_future(
            self._manual_client.call_async(manual_request)
        )
        assert stopped.success

        save_request = SaveMap.Request()
        save_request.overwrite = True
        saved = self._wait_future(
            self._save_map_client.call_async(save_request)
        )
        assert saved.success

        success_handle = self._send_goal("zenoh-success")
        success = self._wait_future(success_handle.get_result_async())
        assert success.status == GoalStatus.STATUS_SUCCEEDED
        assert (
            success.result.outcome
            == NavigateRobot.Result.OUTCOME_SUCCEEDED
        )
        assert self._feedback_counts["zenoh-success"] >= 3
        self._spin_until(
            lambda: NavigationStatus.STATE_SUCCEEDED in self._states,
            5.0,
        )

        cancel_handle = self._send_goal("zenoh-cancel")
        self._spin_until(
            lambda: self._feedback_counts["zenoh-cancel"] >= 1,
            5.0,
        )
        cancel_response = self._wait_future(
            cancel_handle.cancel_goal_async()
        )
        assert cancel_response.goals_canceling
        canceled = self._wait_future(cancel_handle.get_result_async())
        assert canceled.status == GoalStatus.STATUS_CANCELED
        assert (
            canceled.result.outcome
            == NavigateRobot.Result.OUTCOME_CANCELED
        )
        self._leased_command = ""
        self._spin_until(
            lambda: NavigationStatus.STATE_CANCELED in self._states,
            5.0,
        )
        print(
            "PASS: Zenoh NavigateRobot goal, feedback, result, cancel, "
            "lease and status forwarding"
        )
        print(
            "PASS: Zenoh manual, operating-profile, map-save and "
            "MappingStatus forwarding"
        )


def run_server() -> None:
    rclpy.init()
    node = RobotSideFixture()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.remove_node(node)
        node.destroy_node()
        executor.shutdown()
        rclpy.shutdown()


def run_client() -> None:
    rclpy.init()
    node = ControlSideFixture()
    try:
        node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("server", "client"))
    args = parser.parse_args()
    if args.role == "server":
        run_server()
    else:
        run_client()


if __name__ == "__main__":
    main()
