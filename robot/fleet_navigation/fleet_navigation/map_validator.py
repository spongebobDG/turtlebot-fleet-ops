"""Validate saved Nav2 map metadata and occupancy image artifacts."""

from argparse import ArgumentParser
from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Any
from typing import Mapping
from typing import Sequence

import yaml


class MapValidationError(ValueError):
    """Raised when a saved map cannot be trusted as a Nav2 input."""


@dataclass(frozen=True)
class MapMetadata:
    """Validated subset of a Nav2 map-server YAML document."""

    yaml_path: Path
    image_path: Path
    mode: str
    resolution: float
    origin: tuple[float, float, float]
    negate: bool
    occupied_thresh: float
    free_thresh: float


@dataclass(frozen=True)
class MapReport:
    """Occupancy statistics computed from a saved map image."""

    metadata: MapMetadata
    width: int
    height: int
    occupied_cells: int
    free_cells: int
    unknown_cells: int

    @property
    def total_cells(self) -> int:
        """Return the image cell count."""
        return self.width * self.height

    @property
    def known_cells(self) -> int:
        """Return cells classified as occupied or free."""
        return self.occupied_cells + self.free_cells

    @property
    def known_ratio(self) -> float:
        """Return the fraction of cells that contain observed map data."""
        return self.known_cells / self.total_cells


def _finite_float(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise MapValidationError(f"{field} must be numeric") from error
    if not math.isfinite(result):
        raise MapValidationError(f"{field} must be finite")
    return result


def _required(mapping: Mapping[str, Any], field: str) -> Any:
    if field not in mapping:
        raise MapValidationError(f"missing YAML field: {field}")
    return mapping[field]


def load_map_metadata(
    yaml_path: Path,
    require_relative_image: bool = True,
) -> MapMetadata:
    """Load and validate a map-server YAML file and its image path."""
    yaml_path = yaml_path.expanduser().resolve()
    if not yaml_path.is_file():
        raise MapValidationError(f"map YAML does not exist: {yaml_path}")

    try:
        with yaml_path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise MapValidationError(f"cannot read map YAML: {error}") from error

    if not isinstance(document, Mapping):
        raise MapValidationError("map YAML root must be a mapping")

    image_value = _required(document, "image")
    if not isinstance(image_value, str) or not image_value.strip():
        raise MapValidationError("image must be a non-empty path")
    image_reference = Path(image_value)
    if require_relative_image and image_reference.is_absolute():
        raise MapValidationError("image must use a repository-relative path")
    image_path = (
        image_reference
        if image_reference.is_absolute()
        else yaml_path.parent / image_reference
    ).resolve()
    if require_relative_image:
        try:
            image_path.relative_to(yaml_path.parent)
        except ValueError as error:
            raise MapValidationError(
                "image must stay inside the map directory"
            ) from error
    if not image_path.is_file():
        raise MapValidationError(f"map image does not exist: {image_path}")

    mode = _required(document, "mode")
    if mode != "trinary":
        raise MapValidationError("map mode must be trinary")

    resolution = _finite_float(_required(document, "resolution"), "resolution")
    if resolution <= 0.0:
        raise MapValidationError("resolution must be positive")

    origin_value = _required(document, "origin")
    if not isinstance(origin_value, Sequence) or isinstance(
        origin_value, (str, bytes)
    ):
        raise MapValidationError("origin must be a three-number sequence")
    if len(origin_value) != 3:
        raise MapValidationError("origin must contain x, y and yaw")
    origin = tuple(
        _finite_float(value, f"origin[{index}]")
        for index, value in enumerate(origin_value)
    )

    negate_value = _required(document, "negate")
    if negate_value not in (0, 1, False, True):
        raise MapValidationError("negate must be 0 or 1")

    occupied_thresh = _finite_float(
        _required(document, "occupied_thresh"), "occupied_thresh"
    )
    free_thresh = _finite_float(
        _required(document, "free_thresh"), "free_thresh"
    )
    if not 0.0 <= free_thresh < occupied_thresh <= 1.0:
        raise MapValidationError(
            "thresholds must satisfy 0 <= free < occupied <= 1"
        )

    return MapMetadata(
        yaml_path=yaml_path,
        image_path=image_path,
        mode=mode,
        resolution=resolution,
        origin=origin,
        negate=bool(negate_value),
        occupied_thresh=occupied_thresh,
        free_thresh=free_thresh,
    )


def _read_token(data: bytes, offset: int) -> tuple[bytes, int]:
    length = len(data)
    while offset < length:
        if data[offset] in b" \t\r\n":
            offset += 1
            continue
        if data[offset] == ord("#"):
            newline = data.find(b"\n", offset)
            if newline < 0:
                raise MapValidationError("truncated PGM comment")
            offset = newline + 1
            continue
        break
    start = offset
    while offset < length and data[offset] not in b" \t\r\n#":
        offset += 1
    if start == offset:
        raise MapValidationError("truncated PGM header")
    return data[start:offset], offset


def read_pgm(path: Path) -> tuple[int, int, int, list[int]]:
    """Read P2 or P5 PGM data without an image-library dependency."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise MapValidationError(f"cannot read map image: {error}") from error

    tokens = []
    offset = 0
    for _ in range(4):
        token, offset = _read_token(data, offset)
        tokens.append(token)
    magic = tokens[0]
    if magic not in (b"P2", b"P5"):
        raise MapValidationError("map image must be a P2 or P5 PGM")
    try:
        width, height, max_value = (int(token) for token in tokens[1:])
    except ValueError as error:
        raise MapValidationError("PGM dimensions and maximum must be integers") from error
    if width <= 0 or height <= 0:
        raise MapValidationError("PGM dimensions must be positive")
    if max_value <= 0 or max_value > 65535:
        raise MapValidationError("PGM maximum must be in [1, 65535]")

    expected = width * height
    if magic == b"P2":
        pixels = []
        while len(pixels) < expected:
            token, offset = _read_token(data, offset)
            try:
                pixels.append(int(token))
            except ValueError as error:
                raise MapValidationError("P2 PGM pixels must be integers") from error
        try:
            _read_token(data, offset)
        except MapValidationError:
            pass
        else:
            raise MapValidationError("P2 PGM has extra pixel data")
    else:
        if offset >= len(data) or data[offset] not in b" \t\r\n":
            raise MapValidationError("P5 PGM header lacks raster separator")
        if data[offset:offset + 2] == b"\r\n":
            offset += 2
        else:
            offset += 1
        bytes_per_pixel = 1 if max_value < 256 else 2
        raster = data[offset:]
        expected_bytes = expected * bytes_per_pixel
        if len(raster) != expected_bytes:
            raise MapValidationError(
                f"P5 PGM raster has {len(raster)} bytes; expected {expected_bytes}"
            )
        if bytes_per_pixel == 1:
            pixels = list(raster)
        else:
            pixels = [
                int.from_bytes(raster[index:index + 2], "big")
                for index in range(0, len(raster), 2)
            ]

    if any(pixel < 0 or pixel > max_value for pixel in pixels):
        raise MapValidationError("PGM pixel lies outside the declared range")
    return width, height, max_value, pixels


def inspect_map(
    yaml_path: Path,
    min_known_cells: int = 1,
    min_known_ratio: float = 0.0,
    require_pose_graph: bool = False,
    require_relative_image: bool = True,
) -> MapReport:
    """Validate map artifacts and return occupancy statistics."""
    if min_known_cells < 0:
        raise MapValidationError("min_known_cells must not be negative")
    if not 0.0 <= min_known_ratio <= 1.0:
        raise MapValidationError("min_known_ratio must be in [0, 1]")

    metadata = load_map_metadata(yaml_path, require_relative_image)
    width, height, max_value, pixels = read_pgm(metadata.image_path)

    occupied = 0
    free = 0
    for pixel in pixels:
        normalized = pixel / max_value
        occupancy = normalized if metadata.negate else 1.0 - normalized
        if occupancy > metadata.occupied_thresh:
            occupied += 1
        elif occupancy < metadata.free_thresh:
            free += 1
    report = MapReport(
        metadata=metadata,
        width=width,
        height=height,
        occupied_cells=occupied,
        free_cells=free,
        unknown_cells=len(pixels) - occupied - free,
    )
    if report.known_cells < min_known_cells:
        raise MapValidationError(
            f"known cells {report.known_cells} are below {min_known_cells}"
        )
    if report.known_ratio < min_known_ratio:
        raise MapValidationError(
            f"known ratio {report.known_ratio:.4f} is below "
            f"{min_known_ratio:.4f}"
        )
    if require_pose_graph:
        base = metadata.yaml_path.with_suffix("")
        missing = [
            path.name
            for path in (base.with_suffix(".posegraph"), base.with_suffix(".data"))
            if not path.is_file()
        ]
        if missing:
            raise MapValidationError(
                "missing SLAM pose graph artifacts: " + ", ".join(missing)
            )
    return report


def _parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Validate a saved Nav2 YAML/PGM map before localization",
    )
    parser.add_argument("map_yaml", type=Path)
    parser.add_argument("--min-known-cells", type=int, default=100)
    parser.add_argument("--min-known-ratio", type=float, default=0.01)
    parser.add_argument("--require-pose-graph", action="store_true")
    parser.add_argument("--allow-absolute-image", action="store_true")
    return parser


def main() -> None:
    """Run map validation and expose an automation-friendly exit status."""
    args = _parser().parse_args()
    try:
        report = inspect_map(
            args.map_yaml,
            min_known_cells=args.min_known_cells,
            min_known_ratio=args.min_known_ratio,
            require_pose_graph=args.require_pose_graph,
            require_relative_image=not args.allow_absolute_image,
        )
    except MapValidationError as error:
        print(f"MAP_VALIDATION=FAIL reason={error}", file=sys.stderr)
        raise SystemExit(2) from error

    print("MAP_VALIDATION=PASS")
    print(f"yaml={report.metadata.yaml_path}")
    print(f"image={report.metadata.image_path}")
    print(f"size={report.width}x{report.height}")
    print(f"resolution_m={report.metadata.resolution:.6f}")
    print(f"known_cells={report.known_cells}")
    print(f"known_ratio={report.known_ratio:.4f}")
    print(f"occupied_cells={report.occupied_cells}")
    print(f"free_cells={report.free_cells}")
    print(f"unknown_cells={report.unknown_cells}")


if __name__ == "__main__":
    main()
