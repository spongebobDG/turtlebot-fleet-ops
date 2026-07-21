"""Compile web-authored semantic map policies into a Nav2 keepout mask."""

import json
import math
from typing import Any, List, Mapping, Sequence, Tuple

from nav2_msgs.msg import CostmapFilterInfo
from nav_msgs.msg import OccupancyGrid
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


HARD_BLOCK_TYPES = {"virtual_wall", "keepout", "privacy"}


def rasterize_annotations(
    occupancy_map: Any,
    annotations: Sequence[Mapping[str, Any]],
) -> List[int]:
    """Rasterize enabled hard-policy geometry into 0/100 mask cells."""
    width = int(occupancy_map.info.width)
    height = int(occupancy_map.info.height)
    resolution = float(occupancy_map.info.resolution)
    origin = occupancy_map.info.origin
    yaw = _quaternion_yaw(origin.orientation.z, origin.orientation.w)
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    hard = [
        item
        for item in annotations
        if item.get("enabled", True)
        and item.get("type") in HARD_BLOCK_TYPES
    ]
    data = [0] * (width * height)
    for cell_y in range(height):
        local_y = (cell_y + 0.5) * resolution
        for cell_x in range(width):
            local_x = (cell_x + 0.5) * resolution
            world_x = origin.position.x + cosine * local_x - sine * local_y
            world_y = origin.position.y + sine * local_x + cosine * local_y
            if any(_blocks_point(item, world_x, world_y) for item in hard):
                data[cell_y * width + cell_x] = 100
    return data


class MapAnnotationFilter(Node):
    """Publish a transient-local filter mask consumed by both Nav2 costmaps."""

    def __init__(self) -> None:
        super().__init__("map_annotation_filter")
        self.declare_parameter("robot_id", "tb1")
        self.declare_parameter("map_topic", "/map")
        self.declare_parameter("annotation_topic", "/tb1/map_annotations")
        self.declare_parameter(
            "mask_topic",
            "/tb1/map_annotations/filter_mask",
        )
        self.declare_parameter(
            "filter_info_topic",
            "/tb1/map_annotations/filter_info",
        )
        self._robot_id = str(self.get_parameter("robot_id").value)
        self._mask_topic = str(self.get_parameter("mask_topic").value)
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._mask_publisher = self.create_publisher(
            OccupancyGrid,
            self._mask_topic,
            qos,
        )
        self._info_publisher = self.create_publisher(
            CostmapFilterInfo,
            str(self.get_parameter("filter_info_topic").value),
            qos,
        )
        self._map_subscription = self.create_subscription(
            OccupancyGrid,
            str(self.get_parameter("map_topic").value),
            self._on_map,
            qos,
        )
        self._annotation_subscription = self.create_subscription(
            String,
            str(self.get_parameter("annotation_topic").value),
            self._on_annotations,
            qos,
        )
        self._map = None
        self._annotations: List[Mapping[str, Any]] = []
        self._publish_info()

    def _on_map(self, message: OccupancyGrid) -> None:
        self._map = message
        self._publish_mask()

    def _on_annotations(self, message: String) -> None:
        try:
            payload = json.loads(message.data)
            if payload.get("version") != 1:
                raise ValueError("unsupported annotation version")
            if payload.get("robot_id") != self._robot_id:
                raise ValueError("annotation robot_id mismatch")
            annotations = payload.get("annotations")
            if not isinstance(annotations, list):
                raise ValueError("annotations must be an array")
        except (AttributeError, TypeError, ValueError) as error:
            self.get_logger().error(f"Rejected map annotations: {error}")
            return
        self._annotations = annotations
        self._publish_mask()

    def _publish_info(self) -> None:
        message = CostmapFilterInfo()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "map"
        message.type = 0
        message.base = 0.0
        message.multiplier = 1.0
        message.filter_mask_topic = self._mask_topic
        self._info_publisher.publish(message)

    def _publish_mask(self) -> None:
        if self._map is None:
            return
        mask = OccupancyGrid()
        mask.header.stamp = self.get_clock().now().to_msg()
        mask.header.frame_id = self._map.header.frame_id or "map"
        mask.info = self._map.info
        mask.data = rasterize_annotations(self._map, self._annotations)
        self._mask_publisher.publish(mask)
        self._publish_info()
        blocked = sum(value == 100 for value in mask.data)
        self.get_logger().info(
            "Published semantic keepout mask "
            f"annotations={len(self._annotations)} blocked_cells={blocked}"
        )


def _blocks_point(annotation: Mapping[str, Any], x: float, y: float) -> bool:
    points = annotation.get("points") or []
    margin = max(0.0, float(annotation.get("safety_margin_m", 0.0)))
    if annotation.get("type") == "virtual_wall":
        radius = margin + max(
            0.0,
            float(annotation.get("width_m", 0.0)),
        ) / 2.0
        return any(
            _distance_to_segment(x, y, first, second) <= radius
            for first, second in zip(points, points[1:])
        )
    if len(points) < 3:
        return False
    return _point_in_polygon(x, y, points) or any(
        _distance_to_segment(x, y, first, second) <= margin
        for first, second in _polygon_edges(points)
    )


def _distance_to_segment(
    x: float,
    y: float,
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    start_x = float(first["x"])
    start_y = float(first["y"])
    delta_x = float(second["x"]) - start_x
    delta_y = float(second["y"]) - start_y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared <= 1.0e-12:
        return math.hypot(x - start_x, y - start_y)
    ratio = max(
        0.0,
        min(
            1.0,
            ((x - start_x) * delta_x + (y - start_y) * delta_y)
            / length_squared,
        ),
    )
    return math.hypot(
        x - (start_x + ratio * delta_x),
        y - (start_y + ratio * delta_y),
    )


def _point_in_polygon(
    x: float,
    y: float,
    points: Sequence[Mapping[str, Any]],
) -> bool:
    inside = False
    previous = points[-1]
    for current in points:
        current_x = float(current["x"])
        current_y = float(current["y"])
        previous_x = float(previous["x"])
        previous_y = float(previous["y"])
        if (current_y > y) != (previous_y > y):
            boundary_x = (
                (previous_x - current_x)
                * (y - current_y)
                / (previous_y - current_y)
                + current_x
            )
            if x < boundary_x:
                inside = not inside
        previous = current
    return inside


def _polygon_edges(
    points: Sequence[Mapping[str, Any]],
) -> Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]]:
    return list(zip(points, list(points[1:]) + [points[0]]))


def _quaternion_yaw(z: float, w: float) -> float:
    norm = math.hypot(float(z), float(w))
    if norm <= 1.0e-12:
        return 0.0
    normalized_z = float(z) / norm
    normalized_w = float(w) / norm
    return math.atan2(
        2.0 * normalized_w * normalized_z,
        1.0 - 2.0 * normalized_z * normalized_z,
    )


def main(args: Any = None) -> None:
    """Run the map annotation filter node."""
    rclpy.init(args=args)
    node = MapAnnotationFilter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
