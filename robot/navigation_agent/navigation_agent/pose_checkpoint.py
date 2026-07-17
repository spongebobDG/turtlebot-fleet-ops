"""Persist and compare odometry poses between supervised commands."""

from dataclasses import asdict
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import socket
import tempfile
from typing import Mapping
from typing import Optional

from navigation_agent.motion_guard import wrap_angle


SCHEMA_VERSION = 1


class PoseCheckpointError(RuntimeError):
    """Report an invalid or incompatible pose checkpoint."""


@dataclass(frozen=True)
class PoseCheckpoint:
    """Represent one odometry pose accepted by supervised motion."""

    x: float
    y: float
    yaw: float
    odom_frame: str
    base_frame: str

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.yaw)
        if not all(math.isfinite(value) for value in values):
            raise PoseCheckpointError("pose values must be finite")
        if not self.odom_frame or not self.base_frame:
            raise PoseCheckpointError("pose frames must not be empty")


@dataclass(frozen=True)
class PoseDeviation:
    """Describe translation and yaw changes from a checkpoint."""

    translation_m: float
    yaw_rad: float


def default_pose_checkpoint_path(
    environment: Optional[Mapping[str, str]] = None,
    hostname: Optional[str] = None,
) -> Path:
    """Return a per-robot state path outside the source checkout."""
    source = os.environ if environment is None else environment
    state_home = source.get("XDG_STATE_HOME")
    if state_home:
        root = Path(state_home).expanduser()
    else:
        home = source.get("HOME")
        root = (
            Path(home).expanduser() if home else Path.home()
        ) / ".local" / "state"
    robot_name = hostname or socket.gethostname()
    return (
        root
        / "turtlebot-fleet-ops"
        / f"{robot_name}-supervised-motion-pose.json"
    )


def pose_deviation(
    expected: PoseCheckpoint,
    actual: PoseCheckpoint,
) -> PoseDeviation:
    """Return planar distance and wrapped absolute yaw difference."""
    if expected.odom_frame != actual.odom_frame:
        raise PoseCheckpointError(
            "odom frame changed: "
            f"expected={expected.odom_frame} actual={actual.odom_frame}"
        )
    if expected.base_frame != actual.base_frame:
        raise PoseCheckpointError(
            "base frame changed: "
            f"expected={expected.base_frame} actual={actual.base_frame}"
        )
    return PoseDeviation(
        translation_m=math.hypot(
            actual.x - expected.x,
            actual.y - expected.y,
        ),
        yaw_rad=abs(wrap_angle(actual.yaw - expected.yaw)),
    )


def require_pose_continuity(
    expected: PoseCheckpoint,
    actual: PoseCheckpoint,
    max_translation_m: float,
    max_yaw_rad: float,
) -> PoseDeviation:
    """Reject an uncommanded pose change beyond configured limits."""
    if max_translation_m <= 0.0 or max_yaw_rad <= 0.0:
        raise ValueError("pose continuity limits must be positive")
    deviation = pose_deviation(expected, actual)
    if (
        deviation.translation_m > max_translation_m
        or deviation.yaw_rad > max_yaw_rad
    ):
        raise PoseCheckpointError(
            "uncommanded odom pose change: "
            f"translation={deviation.translation_m:.4f}m "
            f"limit={max_translation_m:.4f}m "
            f"yaw={math.degrees(deviation.yaw_rad):.2f}deg "
            f"limit={math.degrees(max_yaw_rad):.2f}deg"
        )
    return deviation


def load_pose_checkpoint(path: Path) -> Optional[PoseCheckpoint]:
    """Load a checkpoint, returning None only when it does not exist."""
    checkpoint_path = Path(path).expanduser()
    if not checkpoint_path.exists():
        return None
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PoseCheckpointError(
            f"cannot read pose checkpoint {checkpoint_path}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise PoseCheckpointError("pose checkpoint must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise PoseCheckpointError(
            "unsupported pose checkpoint schema: "
            f"{payload.get('schema_version')}"
        )
    if payload.get("motion_in_progress") is not False:
        raise PoseCheckpointError(
            "previous supervised motion did not commit a successful "
            "endpoint; inspect the robot and reset in dry-run"
        )
    try:
        return PoseCheckpoint(
            x=float(payload["x"]),
            y=float(payload["y"]),
            yaw=float(payload["yaw"]),
            odom_frame=str(payload["odom_frame"]),
            base_frame=str(payload["base_frame"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PoseCheckpointError(
            f"invalid pose checkpoint fields: {error}"
        ) from error


def _write_pose_checkpoint(
    path: Path,
    checkpoint: PoseCheckpoint,
    motion_in_progress: bool,
) -> None:
    checkpoint_path = Path(path).expanduser()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "motion_in_progress": motion_in_progress,
        **asdict(checkpoint),
    }
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=checkpoint_path.parent,
            prefix=f".{checkpoint_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, checkpoint_path)
    except OSError as error:
        raise PoseCheckpointError(
            f"cannot save pose checkpoint {checkpoint_path}: {error}"
        ) from error
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def save_pose_checkpoint(path: Path, checkpoint: PoseCheckpoint) -> None:
    """Atomically save a successfully accepted final pose."""
    _write_pose_checkpoint(path, checkpoint, motion_in_progress=False)


def mark_pose_checkpoint_in_progress(path: Path) -> None:
    """Persist that a motion may start before releasing the e-stop."""
    checkpoint = load_pose_checkpoint(path)
    if checkpoint is None:
        raise PoseCheckpointError("cannot arm a missing pose checkpoint")
    _write_pose_checkpoint(path, checkpoint, motion_in_progress=True)
