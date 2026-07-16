"""Run flake8 as part of the ROS 2 package test suite."""

from pathlib import Path

from ament_flake8.main import main
import pytest


CONFIG = Path(__file__).resolve().parents[3] / ".flake8"


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8() -> None:
    assert main(argv=["--config", str(CONFIG), "."]) == 0
