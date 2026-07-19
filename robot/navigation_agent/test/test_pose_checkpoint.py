"""Verify persistent odometry continuity checkpoints."""

import json
import math

import pytest

from navigation_agent.pose_checkpoint import default_pose_checkpoint_path
from navigation_agent.pose_checkpoint import load_pose_checkpoint
from navigation_agent.pose_checkpoint import mark_pose_checkpoint_in_progress
from navigation_agent.pose_checkpoint import PoseCheckpoint
from navigation_agent.pose_checkpoint import PoseCheckpointError
from navigation_agent.pose_checkpoint import pose_deviation
from navigation_agent.pose_checkpoint import require_pose_continuity
from navigation_agent.pose_checkpoint import save_pose_checkpoint


def _pose(x=1.0, y=2.0, yaw=0.3) -> PoseCheckpoint:
    return PoseCheckpoint(x, y, yaw, "odom", "base_footprint")


def test_default_path_is_per_robot() -> None:
    path = default_pose_checkpoint_path(
        {"HOME": "/home/operator"},
        "tb1",
    )

    assert path.as_posix() == (
        "/home/operator/.local/state/turtlebot-fleet-ops/"
        "tb1-supervised-motion-pose.json"
    )


def test_checkpoint_round_trip(tmp_path) -> None:
    path = tmp_path / "pose.json"
    expected = _pose()

    save_pose_checkpoint(path, expected)

    assert load_pose_checkpoint(path) == expected


def test_missing_checkpoint_returns_none(tmp_path) -> None:
    assert load_pose_checkpoint(tmp_path / "missing.json") is None


def test_in_progress_checkpoint_is_rejected(tmp_path) -> None:
    path = tmp_path / "pose.json"
    save_pose_checkpoint(path, _pose())

    mark_pose_checkpoint_in_progress(path)

    with pytest.raises(PoseCheckpointError, match="did not commit"):
        load_pose_checkpoint(path)


def test_corrupt_checkpoint_is_rejected(tmp_path) -> None:
    path = tmp_path / "pose.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(PoseCheckpointError, match="cannot read"):
        load_pose_checkpoint(path)


def test_unknown_schema_is_rejected(tmp_path) -> None:
    path = tmp_path / "pose.json"
    path.write_text(
        json.dumps({"schema_version": 99}),
        encoding="utf-8",
    )

    with pytest.raises(PoseCheckpointError, match="schema"):
        load_pose_checkpoint(path)


def test_wrapped_yaw_deviation_stays_small() -> None:
    expected = _pose(yaw=math.radians(179.0))
    actual = _pose(yaw=math.radians(-179.0))

    deviation = pose_deviation(expected, actual)

    assert math.degrees(deviation.yaw_rad) == pytest.approx(2.0)


def test_frame_change_is_rejected() -> None:
    actual = PoseCheckpoint(1.0, 2.0, 0.3, "map", "base_footprint")

    with pytest.raises(PoseCheckpointError, match="odom frame changed"):
        pose_deviation(_pose(), actual)


def test_uncommanded_translation_is_rejected() -> None:
    with pytest.raises(PoseCheckpointError, match="uncommanded"):
        require_pose_continuity(
            _pose(),
            _pose(x=1.04),
            max_translation_m=0.03,
            max_yaw_rad=math.radians(5.0),
        )


def test_uncommanded_rotation_is_rejected() -> None:
    with pytest.raises(PoseCheckpointError, match="uncommanded"):
        require_pose_continuity(
            _pose(),
            _pose(yaw=math.radians(10.0)),
            max_translation_m=0.03,
            max_yaw_rad=math.radians(5.0),
        )
