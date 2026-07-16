"""Pure Robot Agent data normalization and health policy functions."""

from dataclasses import dataclass
import math
from typing import Iterable, Optional, Sequence, Tuple


LEVEL_OK = 0
LEVEL_WARN = 1
LEVEL_ERROR = 2
UNKNOWN_VALUE = -1.0


@dataclass(frozen=True)
class Freshness:
    """Age and freshness of one source topic."""

    received: bool
    fresh: bool
    age_sec: float


@dataclass(frozen=True)
class HealthInput:
    """Normalized facts used to determine fleet health and fault codes."""

    battery: Freshness
    battery_valid: bool
    battery_percent: float
    odom: Freshness
    odom_valid: bool
    scan: Freshness
    scan_valid: bool
    cpu_percent: float
    memory_percent: float
    disk_percent: float


@dataclass(frozen=True)
class HealthThresholds:
    """Thresholds that turn normalized facts into health warnings."""

    low_battery_percent: float
    high_cpu_percent: float
    high_memory_percent: float
    high_disk_percent: float

    def __post_init__(self) -> None:
        for name, value in (
            ("low_battery_percent", self.low_battery_percent),
            ("high_cpu_percent", self.high_cpu_percent),
            ("high_memory_percent", self.high_memory_percent),
            ("high_disk_percent", self.high_disk_percent),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} must be within 0..100")


@dataclass(frozen=True)
class HealthResult:
    """Overall health level plus stable machine-readable fault identifiers."""

    level: int
    fault_codes: Tuple[str, ...]


def source_freshness(
    received_at: Optional[float],
    now: float,
    timeout_sec: float,
) -> Freshness:
    """Return source age without treating missing or future data as fresh."""
    if not math.isfinite(timeout_sec) or timeout_sec <= 0.0:
        raise ValueError("timeout_sec must be a positive finite value")
    if received_at is None:
        return Freshness(False, False, UNKNOWN_VALUE)

    age_sec = now - received_at
    if not math.isfinite(age_sec) or age_sec < 0.0:
        return Freshness(True, False, UNKNOWN_VALUE)
    return Freshness(True, age_sec <= timeout_sec, age_sec)


def normalize_battery_percent(value: float) -> float:
    """Normalize standard 0..1 or TurtleBot 0..100 battery percentages."""
    if not math.isfinite(value) or value < 0.0:
        return UNKNOWN_VALUE
    if value <= 1.0:
        return value * 100.0
    if value <= 100.0:
        return value
    return UNKNOWN_VALUE


def finite_or_unknown(value: float) -> float:
    """Return a finite value or the JSON-safe unknown sentinel."""
    if not math.isfinite(value):
        return UNKNOWN_VALUE
    return value


def quaternion_to_yaw(
    x: float,
    y: float,
    z: float,
    w: float,
) -> Tuple[float, bool]:
    """Convert a finite non-zero quaternion into planar yaw."""
    values = (x, y, z, w)
    if not all(math.isfinite(value) for value in values):
        return 0.0, False

    norm_squared = sum(value * value for value in values)
    if norm_squared <= 1.0e-12:
        return 0.0, False

    inverse_norm = 1.0 / math.sqrt(norm_squared)
    x_n, y_n, z_n, w_n = (
        value * inverse_norm for value in values
    )
    sin_yaw = 2.0 * (w_n * z_n + x_n * y_n)
    cos_yaw = 1.0 - 2.0 * (y_n * y_n + z_n * z_n)
    return math.atan2(sin_yaw, cos_yaw), True


def scan_statistics(
    ranges: Iterable[float],
    range_min: float,
    range_max: float,
) -> Tuple[int, float]:
    """Return count and nearest distance for finite in-range LiDAR points."""
    if (
        not math.isfinite(range_min)
        or not math.isfinite(range_max)
        or range_min < 0.0
        or range_max <= range_min
    ):
        return 0, UNKNOWN_VALUE

    valid_ranges = [
        value
        for value in ranges
        if math.isfinite(value) and range_min <= value <= range_max
    ]
    if not valid_ranges:
        return 0, UNKNOWN_VALUE
    return len(valid_ranges), min(valid_ranges)


def all_finite(values: Sequence[float]) -> bool:
    """Return whether every supplied numeric value is finite."""
    return all(math.isfinite(value) for value in values)


def evaluate_health(
    facts: HealthInput,
    thresholds: HealthThresholds,
) -> HealthResult:
    """Create deterministic level and fault codes from a status snapshot."""
    warnings = []
    errors = []

    _append_source_faults(
        warnings,
        "BATTERY",
        facts.battery,
        facts.battery_valid,
    )
    _append_source_faults(
        errors,
        "ODOM",
        facts.odom,
        facts.odom_valid,
    )
    _append_source_faults(
        errors,
        "SCAN",
        facts.scan,
        facts.scan_valid,
    )

    if (
        facts.battery_percent >= 0.0
        and facts.battery_percent <= thresholds.low_battery_percent
    ):
        warnings.append("LOW_BATTERY")

    for code, value, limit in (
        ("HIGH_CPU", facts.cpu_percent, thresholds.high_cpu_percent),
        (
            "HIGH_MEMORY",
            facts.memory_percent,
            thresholds.high_memory_percent,
        ),
        ("HIGH_DISK", facts.disk_percent, thresholds.high_disk_percent),
    ):
        if math.isfinite(value) and value >= limit:
            warnings.append(code)

    if errors:
        level = LEVEL_ERROR
    elif warnings:
        level = LEVEL_WARN
    else:
        level = LEVEL_OK
    return HealthResult(level, tuple(errors + warnings))


def _append_source_faults(
    target: list,
    source_name: str,
    freshness: Freshness,
    valid: bool,
) -> None:
    """Append exactly one availability fault for a source when needed."""
    if not freshness.received:
        target.append(f"{source_name}_NOT_RECEIVED")
    elif not valid:
        target.append(f"{source_name}_INVALID")
    elif not freshness.fresh:
        target.append(f"{source_name}_STALE")
