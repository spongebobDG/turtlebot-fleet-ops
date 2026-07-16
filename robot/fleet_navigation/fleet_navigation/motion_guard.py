"""Pure motion-progress and clearance rules for supervised robot moves."""

from dataclasses import dataclass
import math
from typing import Optional
from typing import Sequence


VALID_MODES = {"translate", "rotate"}


def wrap_angle(angle: float) -> float:
    """Wrap an angle to the closed-open interval [-pi, pi)."""
    return math.atan2(math.sin(angle), math.cos(angle))


def validate_motion_request(
    mode: str,
    target: float,
    speed: float,
    timeout_sec: float,
    max_linear_speed: float,
    max_angular_speed: float,
) -> None:
    """Reject unsafe or internally inconsistent motion parameters."""
    if mode not in VALID_MODES:
        raise ValueError(f"unsupported mode: {mode}")
    if not math.isfinite(target) or target <= 0.0:
        raise ValueError("target must be finite and positive")
    if not math.isfinite(speed) or speed == 0.0:
        raise ValueError("speed must be finite and non-zero")
    if not math.isfinite(timeout_sec) or timeout_sec <= 0.0:
        raise ValueError("timeout_sec must be finite and positive")
    if max_linear_speed <= 0.0 or max_angular_speed <= 0.0:
        raise ValueError("speed limits must be positive")

    speed_limit = (
        max_linear_speed if mode == "translate" else max_angular_speed
    )
    if abs(speed) > speed_limit:
        raise ValueError(
            f"{mode} speed {abs(speed):.3f} exceeds {speed_limit:.3f}"
        )


@dataclass
class TranslationProgress:
    """Measure signed longitudinal motion from a fixed start pose."""

    start_x: float
    start_y: float
    start_yaw: float
    direction: int

    def __post_init__(self) -> None:
        if self.direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")

    def update(self, x: float, y: float) -> float:
        """Return progress projected onto the commanded heading."""
        return max(0.0, self._longitudinal(x, y))

    def reverse_distance(self, x: float, y: float) -> float:
        """Return distance travelled opposite to the command."""
        return max(0.0, -self._longitudinal(x, y))

    def lateral_distance(self, x: float, y: float) -> float:
        """Return absolute displacement perpendicular to the heading."""
        delta_x = x - self.start_x
        delta_y = y - self.start_y
        return abs(
            -delta_x * math.sin(self.start_yaw)
            + delta_y * math.cos(self.start_yaw)
        )

    def _longitudinal(self, x: float, y: float) -> float:
        delta_x = x - self.start_x
        delta_y = y - self.start_y
        projected = (
            delta_x * math.cos(self.start_yaw)
            + delta_y * math.sin(self.start_yaw)
        )
        return self.direction * projected


@dataclass
class RotationProgress:
    """Track signed net rotation while handling the +/-pi boundary."""

    previous_yaw: float
    direction: int
    signed_rotation: float = 0.0

    def __post_init__(self) -> None:
        if self.direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")

    def update(self, yaw: float) -> float:
        """
        Return progress in the commanded direction.

        Signed deltas are accumulated before applying the direction. This
        makes alternating odometry noise cancel instead of looking like
        real rotation.
        """
        delta = wrap_angle(yaw - self.previous_yaw)
        self.signed_rotation += delta
        self.previous_yaw = yaw
        return max(0.0, self.direction * self.signed_rotation)

    @property
    def reverse_rotation(self) -> float:
        """Return net rotation opposite to the commanded direction."""
        return max(0.0, -self.direction * self.signed_rotation)


def sector_minimum(
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    range_min: float,
    range_max: float,
    center_angle: float,
    half_width: float,
) -> Optional[float]:
    """Return the nearest valid range inside a wrapped angular sector."""
    if angle_increment <= 0.0:
        raise ValueError("angle_increment must be positive")
    if half_width <= 0.0 or half_width > math.pi:
        raise ValueError("half_width must be in (0, pi]")

    values = []
    for index, distance in enumerate(ranges):
        if not math.isfinite(distance):
            continue
        if distance < range_min or distance > range_max:
            continue
        angle = angle_min + index * angle_increment
        if abs(wrap_angle(angle - center_angle)) <= half_width:
            values.append(float(distance))
    return min(values) if values else None


def is_neutral(
    linear_x: float,
    angular_z: float,
    epsilon: float = 1.0e-3,
) -> bool:
    """Return whether planar velocity is inside the neutral deadband."""
    if epsilon < 0.0:
        raise ValueError("epsilon must not be negative")
    return abs(linear_x) <= epsilon and abs(angular_z) <= epsilon
