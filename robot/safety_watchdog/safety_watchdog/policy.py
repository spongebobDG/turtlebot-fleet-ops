"""Pure safety-policy functions that can be tested without a running ROS graph."""

from dataclasses import dataclass
import math
from typing import Optional, Tuple


@dataclass(frozen=True)
class SafetyLimits:
    """Maximum absolute velocities allowed by the safety layer."""

    max_linear_x: float
    max_angular_z: float

    def __post_init__(self) -> None:
        for name, value in (
            ("max_linear_x", self.max_linear_x),
            ("max_angular_z", self.max_angular_z),
        ):
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be a positive finite value")


def clamp_symmetric(value: float, maximum: float) -> float:
    """Clamp a finite value to +/- maximum; reject non-finite input as zero."""
    if not math.isfinite(value):
        return 0.0
    return max(-maximum, min(maximum, value))


def sanitize_planar_command(
    linear_x: float,
    angular_z: float,
    limits: SafetyLimits,
) -> Tuple[float, float]:
    """Return a differential-drive command restricted by configured limits."""
    return (
        clamp_symmetric(linear_x, limits.max_linear_x),
        clamp_symmetric(angular_z, limits.max_angular_z),
    )


def command_is_fresh(
    last_received_at: Optional[float],
    now: float,
    timeout_sec: float,
) -> bool:
    """Return whether a command was received within the watchdog timeout."""
    if not math.isfinite(timeout_sec) or timeout_sec <= 0.0:
        raise ValueError("timeout_sec must be a positive finite value")
    if last_received_at is None:
        return False

    elapsed = now - last_received_at
    return 0.0 <= elapsed <= timeout_sec
