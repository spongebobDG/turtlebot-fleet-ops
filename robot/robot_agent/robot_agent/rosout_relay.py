"""Relay the ROS 2 internal log stream onto an explicit fleet topic."""

from typing import List, Optional

import rclpy
from rclpy.executors import ExternalShutdownException
from rcl_interfaces.msg import Log
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy


class RosoutRelay(Node):
    """Republish /rosout with a stable fleet-owned QoS contract."""

    def __init__(self) -> None:
        super().__init__("rosout_relay")
        input_qos = QoSProfile(
            depth=1000,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        output_qos = QoSProfile(
            depth=200,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._publisher = self.create_publisher(
            Log,
            "/fleet/rosout",
            output_qos,
        )
        self.create_subscription(Log, "/rosout", self._on_log, input_qos)

    def _on_log(self, message: Log) -> None:
        self._publisher.publish(message)


def main(args: Optional[List[str]] = None) -> None:
    """Run the fleet rosout relay until shutdown."""
    rclpy.init(args=args)
    node = RosoutRelay()
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, KeyboardInterrupt):
        pass
    finally:
        try:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except (ExternalShutdownException, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    main()
