"""Tests for saved Nav2 map artifact validation."""

from pathlib import Path

from navigation_agent.map_validator import inspect_map
from navigation_agent.map_validator import load_map_metadata
from navigation_agent.map_validator import MapValidationError
from navigation_agent.map_validator import read_pgm
import pytest


def _write_map(
    directory: Path,
    *,
    image: str = "test.pgm",
    pixels: bytes = bytes([0, 254, 127, 0]),
    width: int = 2,
    height: int = 2,
    extra_yaml: str = "",
) -> Path:
    (directory / "test.pgm").write_bytes(
        f"P5\n# map fixture\n{width} {height}\n255\n".encode() + pixels
    )
    yaml_path = directory / "test.yaml"
    yaml_path.write_text(
        "\n".join(
            [
                f"image: {image}",
                "mode: trinary",
                "resolution: 0.05",
                "origin: [-1.0, -2.0, 0.0]",
                "negate: 0",
                "occupied_thresh: 0.65",
                "free_thresh: 0.25",
                extra_yaml,
            ]
        ),
        encoding="utf-8",
    )
    return yaml_path


def test_inspect_binary_map_reports_occupancy(tmp_path: Path) -> None:
    report = inspect_map(_write_map(tmp_path))

    assert report.width == 2
    assert report.height == 2
    assert report.occupied_cells == 2
    assert report.free_cells == 1
    assert report.unknown_cells == 1
    assert report.known_ratio == pytest.approx(0.75)


def test_read_ascii_pgm_with_comments(tmp_path: Path) -> None:
    path = tmp_path / "ascii.pgm"
    path.write_text("P2\n# fixture\n3 1\n255\n0 127 254\n", encoding="ascii")

    assert read_pgm(path) == (3, 1, 255, [0, 127, 254])


def test_read_sixteen_bit_binary_pgm(tmp_path: Path) -> None:
    path = tmp_path / "wide.pgm"
    path.write_bytes(b"P5\n2 1\n1023\n" + b"\x00\x00\x03\xff")

    assert read_pgm(path) == (2, 1, 1023, [0, 1023])


def test_negated_map_reverses_occupied_and_free(tmp_path: Path) -> None:
    yaml_path = _write_map(tmp_path)
    text = yaml_path.read_text(encoding="utf-8").replace("negate: 0", "negate: 1")
    yaml_path.write_text(text, encoding="utf-8")

    report = inspect_map(yaml_path)

    assert report.occupied_cells == 1
    assert report.free_cells == 2


def test_nav2_unknown_marker_must_survive_round_trip(tmp_path: Path) -> None:
    yaml_path = _write_map(
        tmp_path,
        pixels=bytes([0, 254, 205, 0]),
    )

    with pytest.raises(MapValidationError, match="would load as free"):
        inspect_map(yaml_path)


def test_nav2_unknown_marker_is_preserved_at_safe_threshold(
    tmp_path: Path,
) -> None:
    yaml_path = _write_map(
        tmp_path,
        pixels=bytes([0, 254, 205, 0]),
    )
    text = yaml_path.read_text(encoding="utf-8").replace(
        "free_thresh: 0.25", "free_thresh: 0.196"
    )
    yaml_path.write_text(text, encoding="utf-8")

    report = inspect_map(yaml_path)

    assert report.known_cells == 3
    assert report.unknown_cells == 1
    assert report.trinary_unknown_marker_cells == 1


def test_absolute_image_is_rejected_by_default(tmp_path: Path) -> None:
    image_path = tmp_path / "test.pgm"
    yaml_path = _write_map(tmp_path, image=str(image_path))

    with pytest.raises(MapValidationError, match="repository-relative"):
        load_map_metadata(yaml_path)


def test_relative_image_cannot_escape_map_directory(tmp_path: Path) -> None:
    map_directory = tmp_path / "maps"
    map_directory.mkdir()
    (tmp_path / "outside.pgm").write_bytes(b"P5\n1 1\n255\n\x00")
    yaml_path = _write_map(map_directory, image="../outside.pgm")

    with pytest.raises(MapValidationError, match="inside the map directory"):
        load_map_metadata(yaml_path)


def test_missing_image_is_rejected(tmp_path: Path) -> None:
    yaml_path = _write_map(tmp_path, image="missing.pgm")

    with pytest.raises(MapValidationError, match="does not exist"):
        inspect_map(yaml_path)


def test_invalid_threshold_order_is_rejected(tmp_path: Path) -> None:
    yaml_path = _write_map(tmp_path)
    text = yaml_path.read_text(encoding="utf-8").replace(
        "free_thresh: 0.25", "free_thresh: 0.75"
    )
    yaml_path.write_text(text, encoding="utf-8")

    with pytest.raises(MapValidationError, match="free < occupied"):
        inspect_map(yaml_path)


def test_unsupported_map_mode_is_rejected(tmp_path: Path) -> None:
    yaml_path = _write_map(tmp_path)
    text = yaml_path.read_text(encoding="utf-8").replace(
        "mode: trinary", "mode: scale"
    )
    yaml_path.write_text(text, encoding="utf-8")

    with pytest.raises(MapValidationError, match="mode must be trinary"):
        inspect_map(yaml_path)


def test_truncated_raster_is_rejected(tmp_path: Path) -> None:
    yaml_path = _write_map(tmp_path, pixels=bytes([0, 254]))

    with pytest.raises(MapValidationError, match="expected 4"):
        inspect_map(yaml_path)


def test_minimum_known_cells_and_ratio_are_enforced(tmp_path: Path) -> None:
    yaml_path = _write_map(tmp_path)

    with pytest.raises(MapValidationError, match="known cells"):
        inspect_map(yaml_path, min_known_cells=4)
    with pytest.raises(MapValidationError, match="known ratio"):
        inspect_map(yaml_path, min_known_ratio=0.8)


def test_pose_graph_pair_can_be_required(tmp_path: Path) -> None:
    yaml_path = _write_map(tmp_path)

    with pytest.raises(MapValidationError, match="pose graph artifacts"):
        inspect_map(yaml_path, require_pose_graph=True)

    (tmp_path / "test.posegraph").write_bytes(b"posegraph")
    (tmp_path / "test.data").write_bytes(b"data")
    report = inspect_map(yaml_path, require_pose_graph=True)
    assert report.known_cells == 3
