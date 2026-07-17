"""Run the ROS 2 Python style checker."""

from pathlib import Path

from ament_flake8.main import main_with_errors
import pytest


CONFIG = Path(__file__).resolve().parents[3] / ".flake8"


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8() -> None:
    """Require all Python source files to satisfy flake8."""
    return_code, errors = main_with_errors(
        argv=["--config", str(CONFIG)]
    )
    assert return_code == 0, "\n".join(errors)
