"""Process entry point that runs ROS and FastAPI together."""

from pathlib import Path
import os
import threading
from typing import List, Optional

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.executors import MultiThreadedExecutor
import uvicorn

from fleet_gateway.api import create_app
from fleet_gateway.operations import OperationsStore
from fleet_gateway.ros_node import FleetGatewayNode
from fleet_gateway.task_manager import NavigationTaskManager


def main(args: Optional[List[str]] = None) -> None:
    """Start the ROS executor and serve the dashboard until shutdown."""
    rclpy.init(args=args)
    node = FleetGatewayNode()
    database_path = Path(
        os.environ.get(
            "FLEET_OPERATIONS_DB",
            "~/.local/share/turtlebot-fleet-ops/operations.sqlite3",
        )
    ).expanduser()
    operations_store = OperationsStore(database_path)
    recovered_tasks = operations_store.reconcile_gateway_restart()
    if recovered_tasks:
        node.get_logger().warning(
            f"Failed {recovered_tasks} nonterminal task(s) "
            "after Gateway restart"
        )
    node.registry.add_listener(operations_store.observe)
    task_manager = NavigationTaskManager(operations_store, node)
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
        navigation_controller=node,
        map_registry=node.map_registry,
        operations_store=operations_store,
        task_manager=task_manager,
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
