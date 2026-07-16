"""Process entry point that runs ROS and FastAPI together."""

from pathlib import Path
import threading
from typing import List, Optional

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.executors import MultiThreadedExecutor
import uvicorn

from fleet_gateway.api import create_app
from fleet_gateway.ros_node import FleetGatewayNode


def main(args: Optional[List[str]] = None) -> None:
    """Start the ROS executor and serve the dashboard until shutdown."""
    rclpy.init(args=args)
    node = FleetGatewayNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    ros_thread = threading.Thread(
        target=executor.spin,
        name="fleet-gateway-ros",
        daemon=True,
    )
    ros_thread.start()

    share_dir = Path(get_package_share_directory("fleet_gateway"))
    app = create_app(
        registry=node.registry,
        estop_controller=node,
        static_dir=share_dir / "web",
    )
    try:
        uvicorn.run(app, host=node.web_host, port=node.web_port)
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        ros_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()
