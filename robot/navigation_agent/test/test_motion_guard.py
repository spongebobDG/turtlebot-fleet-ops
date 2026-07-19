"""Verify fail-closed supervised-motion progress calculations."""

import math

import pytest

from navigation_agent.motion_guard import is_neutral
from navigation_agent.motion_guard import RotationProgress
from navigation_agent.motion_guard import sector_minimum
from navigation_agent.motion_guard import TranslationProgress
from navigation_agent.motion_guard import validate_motion_request
from navigation_agent.motion_guard import wrap_angle


@pytest.mark.parametrize(
    ("angle", "expected"),
    [
        (0.0, 0.0),
        (2.0 * math.pi, 0.0),
        (3.0 * math.pi / 2.0, -math.pi / 2.0),
        (-3.0 * math.pi / 2.0, math.pi / 2.0),
    ],
)
def test_wrap_angle(angle: float, expected: float) -> None:
    assert wrap_angle(angle) == pytest.approx(expected)


def test_translation_uses_signed_heading_projection() -> None:
    tracker = TranslationProgress(1.0, -2.0, 0.0, 1)

    assert tracker.update(1.10, -1.95) == pytest.approx(0.10)
    assert tracker.lateral_distance(1.10, -1.95) == pytest.approx(0.05)


def test_translation_rejects_opposite_direction_as_progress() -> None:
    tracker = TranslationProgress(0.0, 0.0, 0.0, 1)

    assert tracker.update(-0.03, 0.0) == 0.0
    assert tracker.reverse_distance(-0.03, 0.0) == pytest.approx(0.03)


def test_reverse_translation_uses_command_direction() -> None:
    tracker = TranslationProgress(0.0, 0.0, math.pi / 2.0, -1)

    assert tracker.update(0.0, -0.10) == pytest.approx(0.10)


def test_rotation_crosses_positive_pi_boundary() -> None:
    tracker = RotationProgress(math.radians(179.0), 1)

    progress = tracker.update(math.radians(-179.0))

    assert math.degrees(progress) == pytest.approx(2.0)


def test_rotation_crosses_negative_pi_boundary() -> None:
    tracker = RotationProgress(math.radians(-179.0), -1)

    progress = tracker.update(math.radians(179.0))

    assert math.degrees(progress) == pytest.approx(2.0)


def test_rotation_noise_cancels_instead_of_accumulating() -> None:
    tracker = RotationProgress(0.0, 1)

    for yaw in [0.01, 0.0] * 100:
        progress = tracker.update(yaw)

    assert progress == pytest.approx(0.0, abs=1.0e-9)


def test_rotation_reports_only_commanded_direction() -> None:
    tracker = RotationProgress(0.0, 1)

    progress = tracker.update(-0.2)

    assert progress == 0.0
    assert tracker.reverse_rotation == pytest.approx(0.2)


def test_front_sector_wraps_across_zero_degrees() -> None:
    ranges = [math.inf] * 360
    ranges[359] = 0.8
    ranges[0] = 0.9
    ranges[1] = 1.0

    clearance = sector_minimum(
        ranges,
        0.0,
        math.tau / 360.0,
        0.05,
        12.0,
        0.0,
        math.radians(2.0),
    )

    assert clearance == pytest.approx(0.8)


def test_sector_ignores_invalid_ranges() -> None:
    clearance = sector_minimum(
        [0.0, math.nan, math.inf, 13.0],
        0.0,
        0.01,
        0.05,
        12.0,
        0.0,
        0.1,
    )

    assert clearance is None


@pytest.mark.parametrize(
    ("mode", "target", "speed", "timeout", "message"),
    [
        ("unknown", 0.1, 0.03, 5.0, "unsupported mode"),
        ("translate", 0.0, 0.03, 5.0, "target"),
        ("translate", 0.1, 0.0, 5.0, "speed"),
        ("translate", 0.1, 0.06, 5.0, "exceeds"),
        ("rotate", 1.0, 0.31, 5.0, "exceeds"),
        ("rotate", 1.0, 0.2, 0.0, "timeout"),
    ],
)
def test_invalid_motion_request_is_rejected(
    mode: str,
    target: float,
    speed: float,
    timeout: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_motion_request(
            mode,
            target,
            speed,
            timeout,
            0.05,
            0.30,
        )


@pytest.mark.parametrize(
    ("mode", "speed"),
    [("translate", 0.03), ("translate", -0.03), ("rotate", 0.2)],
)
def test_valid_motion_request_is_accepted(mode: str, speed: float) -> None:
    validate_motion_request(mode, 0.1, speed, 5.0, 0.05, 0.30)


@pytest.mark.parametrize(
    ("linear", "angular", "expected"),
    [
        (0.0, 0.0, True),
        (0.001, -0.001, True),
        (0.0011, 0.0, False),
        (0.0, -0.0011, False),
    ],
)
def test_neutral_deadband(
    linear: float,
    angular: float,
    expected: bool,
) -> None:
    assert is_neutral(linear, angular) is expected
