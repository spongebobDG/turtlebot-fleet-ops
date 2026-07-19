"""Pure navigation and map policy helpers."""

from dataclasses import dataclass
import math
from typing import Optional, Sequence, Tuple


MODE_IDLE = 0
MODE_MANUAL = 1
MODE_NAVIGATION = 2
ZERO_COMMAND = (0.0, 0.0)


@dataclass(frozen=True)
class GridMap:
    """Minimal occupancy-grid data needed for coordinate validation."""

    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    origin_yaw: float
    data: Sequence[int]

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("map dimensions must be positive")
        if not math.isfinite(self.resolution) or self.resolution <= 0.0:
            raise ValueError("map resolution must be positive and finite")
        if not all(
            math.isfinite(value)
            for value in (self.origin_x, self.origin_y, self.origin_yaw)
        ):
            raise ValueError("map origin must be finite")
        if len(self.data) != self.width * self.height:
            raise ValueError("map data length does not match dimensions")
        if any(int(value) < -1 or int(value) > 100 for value in self.data):
            raise ValueError("map data values must be within -1..100")


def quaternion_to_yaw(z: float, w: float) -> float:
    """Return planar yaw from a normalized-or-normalizable z/w quaternion."""
    if not math.isfinite(z) or not math.isfinite(w):
        return 0.0
    norm = math.hypot(z, w)
    if norm <= 1.0e-12:
        return 0.0
    z_value = z / norm
    w_value = w / norm
    return math.atan2(2.0 * w_value * z_value, 1.0 - 2.0 * z_value**2)


def pose_values_are_finite(x: float, y: float, z: float, w: float) -> bool:
    """Return whether a planar pose contains finite values and orientation."""
    if not all(math.isfinite(value) for value in (x, y, z, w)):
        return False
    return math.hypot(z, w) > 1.0e-12


def world_to_cell(grid: GridMap, x: float, y: float) -> Optional[Tuple[int, int]]:
    """Transform map-frame world coordinates into an occupancy-grid cell."""
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    delta_x = x - grid.origin_x
    delta_y = y - grid.origin_y
    cosine = math.cos(grid.origin_yaw)
    sine = math.sin(grid.origin_yaw)
    local_x = cosine * delta_x + sine * delta_y
    local_y = -sine * delta_x + cosine * delta_y
    cell_x = math.floor(local_x / grid.resolution)
    cell_y = math.floor(local_y / grid.resolution)
    if not 0 <= cell_x < grid.width or not 0 <= cell_y < grid.height:
        return None
    return int(cell_x), int(cell_y)


def cell_value(grid: GridMap, x: float, y: float) -> Optional[int]:
    """Return the occupancy value at world coordinates, if inside the map."""
    cell = world_to_cell(grid, x, y)
    if cell is None:
        return None
    cell_x, cell_y = cell
    return int(grid.data[cell_y * grid.width + cell_x])


def pose_is_on_free_cell(
    grid: GridMap,
    x: float,
    y: float,
    free_value_max: int = 0,
) -> bool:
    """Accept only known cells at or below the configured free threshold."""
    value = cell_value(grid, x, y)
    return value is not None and 0 <= value <= free_value_max


def value_is_fresh(
    received_at: Optional[float],
    now: float,
    timeout_sec: float,
) -> bool:
    """Return whether a local monotonic receipt time is still valid."""
    if received_at is None:
        return False
    age = now - received_at
    return 0.0 <= age <= timeout_sec


def choose_command(
    mode: int,
    now: float,
    input_timeout_sec: float,
    authorization_timeout_sec: float,
    manual_command: Tuple[float, float],
    manual_received_at: Optional[float],
    navigation_command: Tuple[float, float],
    navigation_received_at: Optional[float],
    authorization_received_at: Optional[float],
) -> Tuple[float, float]:
    """Choose one command source and fail closed to an explicit zero."""
    if mode == MODE_MANUAL and value_is_fresh(
        manual_received_at,
        now,
        input_timeout_sec,
    ):
        return manual_command
    if (
        mode == MODE_NAVIGATION
        and value_is_fresh(
            navigation_received_at,
            now,
            input_timeout_sec,
        )
        and value_is_fresh(
            authorization_received_at,
            now,
            authorization_timeout_sec,
        )
    ):
        return navigation_command
    return ZERO_COMMAND
