"""Run flake8 as part of the ROS 2 package test suite."""

from ament_flake8.main import main
import pytest


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8() -> None:
    assert main(argv=["."]) == 0
