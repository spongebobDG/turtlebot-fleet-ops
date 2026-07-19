"""Fail-closed map-frame progress supervision for Nav2 goals."""

from dataclasses import dataclass
import math
from typing import Optional

from navigation_agent.motion_guard import wrap_angle


@dataclass
class NavigationProgressMonitor:
    """Detect missing feedback, stalled map progress, and runaway goals."""

    started_at: float
    progress_timeout_sec: float
    feedback_timeout_sec: float
    max_duration_sec: float
    distance_progress_m: float
    yaw_progress_rad: float
    last_feedback_at: Optional[float] = None
    last_progress_at: Optional[float] = None
    best_distance: Optional[float] = None
    best_yaw_error: Optional[float] = None
    progress_yaw: Optional[float] = None
    recoveries: int = 0

    def __post_init__(self) -> None:
        values = (
            self.started_at,
            self.progress_timeout_sec,
            self.feedback_timeout_sec,
            self.max_duration_sec,
            self.distance_progress_m,
            self.yaw_progress_rad,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("navigation progress values must be finite")
        if self.started_at < 0.0:
            raise ValueError("started_at must not be negative")
        if min(values[1:]) <= 0.0:
            raise ValueError("navigation progress limits must be positive")
        if self.max_duration_sec <= self.progress_timeout_sec:
            raise ValueError(
                "max_duration_sec must exceed progress_timeout_sec"
            )
        self.last_progress_at = self.started_at

    def update(
        self,
        now: float,
        distance_remaining: float,
        current_yaw: float,
        target_yaw: float,
        recoveries: int,
    ) -> bool:
        """Record valid feedback and return whether material progress occurred."""
        values = (now, distance_remaining, current_yaw, target_yaw)
        if not all(math.isfinite(value) for value in values):
            return False
        if now < self.started_at or recoveries < 0:
            return False

        distance = max(0.0, distance_remaining)
        yaw_error = abs(wrap_angle(target_yaw - current_yaw))
        first_feedback = self.last_feedback_at is None
        recovery_started = recoveries > self.recoveries
        self.last_feedback_at = now

        if first_feedback or recovery_started:
            self.best_distance = distance
            self.best_yaw_error = yaw_error
            self.progress_yaw = current_yaw
            self.last_progress_at = now
            self.recoveries = recoveries
            return recovery_started

        distance_progress = bool(
            self.best_distance is not None
            and distance <= self.best_distance - self.distance_progress_m
        )
        yaw_error_progress = bool(
            self.best_yaw_error is not None
            and yaw_error <= self.best_yaw_error - self.yaw_progress_rad
        )
        yaw_motion_progress = bool(
            self.progress_yaw is not None
            and abs(wrap_angle(current_yaw - self.progress_yaw))
            >= self.yaw_progress_rad
        )
        yaw_progress = yaw_error_progress or yaw_motion_progress
        if distance_progress:
            self.best_distance = distance
        if yaw_progress:
            if self.best_yaw_error is None:
                self.best_yaw_error = yaw_error
            else:
                self.best_yaw_error = min(self.best_yaw_error, yaw_error)
            self.progress_yaw = current_yaw
        if distance_progress or yaw_progress:
            self.last_progress_at = now
            return True
        return False

    def failure_reason(self, now: float) -> Optional[str]:
        """Return a stable operator-facing failure reason, if one is due."""
        if not math.isfinite(now) or now < self.started_at:
            return "Navigation supervision received an invalid clock value"
        elapsed = now - self.started_at
        if elapsed >= self.max_duration_sec:
            return (
                "Navigation maximum duration exceeded "
                f"({self.max_duration_sec:.1f}s)"
            )

        feedback_reference = self.last_feedback_at or self.started_at
        if now - feedback_reference >= self.feedback_timeout_sec:
            return (
                "Navigation feedback timeout: no fresh Nav2 feedback for "
                f"{self.feedback_timeout_sec:.1f}s"
            )

        progress_reference = self.last_progress_at or self.started_at
        if now - progress_reference >= self.progress_timeout_sec:
            return (
                "Failed to make progress in map frame for "
                f"{self.progress_timeout_sec:.1f}s"
            )
        return None
