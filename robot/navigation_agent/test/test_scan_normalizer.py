"""Verify fixed-grid normalization of variable LDS-02 scans."""

import math

import pytest

from navigation_agent.scan_normalizer import normalize_samples


def test_normalizer_always_returns_fixed_length() -> None:
    ranges, intensities = normalize_samples(
        [1.0] * 207,
        [10.0] * 207,
        0.2,
        0.0275,
        0.05,
        12.0,
        360,
    )

    assert len(ranges) == 360
    assert len(intensities) == 360
    assert any(math.isinf(value) for value in ranges)


def test_normalizer_places_samples_by_wrapped_angle() -> None:
    ranges, intensities = normalize_samples(
        [1.0, 2.0],
        [3.0, 4.0],
        -math.pi / 180.0,
        2.0 * math.pi / 180.0,
        0.05,
        12.0,
        360,
    )

    assert ranges[359] == pytest.approx(1.0)
    assert intensities[359] == pytest.approx(3.0)
    assert ranges[1] == pytest.approx(2.0)
    assert intensities[1] == pytest.approx(4.0)


def test_normalizer_keeps_nearest_obstacle_in_shared_bin() -> None:
    ranges, intensities = normalize_samples(
        [2.0, 0.7],
        [20.0, 7.0],
        0.0,
        0.001,
        0.05,
        12.0,
        360,
    )

    assert ranges[0] == pytest.approx(0.7)
    assert intensities[0] == pytest.approx(7.0)


def test_normalizer_discards_invalid_ranges() -> None:
    ranges, _ = normalize_samples(
        [0.0, math.nan, math.inf, 13.0],
        [],
        0.0,
        0.1,
        0.05,
        12.0,
        360,
    )

    assert all(math.isinf(value) for value in ranges)


@pytest.mark.parametrize(
    ("angle_increment", "bin_count"),
    [(0.0, 360), (-0.1, 360), (0.1, 0)],
)
def test_normalizer_rejects_invalid_geometry(
    angle_increment: float,
    bin_count: int,
) -> None:
    with pytest.raises(ValueError):
        normalize_samples(
            [1.0],
            [],
            0.0,
            angle_increment,
            0.05,
            12.0,
            bin_count,
        )
