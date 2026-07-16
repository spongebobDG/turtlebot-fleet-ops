"""Run the web gateway and mock TB1 in one robot-free process."""

from pathlib import Path
import threading
from typing import List, Optional

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.executors import MultiThreadedExecutor
import uvicorn

from fleet_gateway.api import create_app
from fleet_gateway.mock_robot import MockRobotNode
from fleet_gateway.ros_node import FleetGatewayNode


def main(args: Optional[List[str]] = None) -> None:
    """Start a mock TB1, ROS gateway and dashboard until shutdown."""
    rclpy.init(args=args)
    mock = MockRobotNode()
    gateway = FleetGatewayNode()
    executor = MultiThreadedExecutor(num_threads=6)
    executor.add_node(mock)
    executor.add_node(gateway)
    ros_thread = threading.Thread(
        target=executor.spin,
        name="fleet-gateway-weekend-ros",
        daemon=True,
    )
    ros_thread.start()

    share_dir = Path(get_package_share_directory("fleet_gateway"))
    app = create_app(
        registry=gateway.registry,
        estop_controller=gateway,
        navigation_controller=gateway,
        static_dir=share_dir / "web",
    )
    try:
        uvicorn.run(
            app,
            host=gateway.web_host,
            port=gateway.web_port,
        )
    finally:
        executor.shutdown()
        gateway.destroy_node()
        mock.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        ros_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()
