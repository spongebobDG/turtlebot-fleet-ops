"""Run the ROS 2 Python style checker."""

from ament_flake8.main import main_with_errors
import pytest


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8() -> None:
    """Require all Python source files to satisfy flake8."""
    return_code, errors = main_with_errors(argv=[])
    assert return_code == 0, "\n".join(errors)
