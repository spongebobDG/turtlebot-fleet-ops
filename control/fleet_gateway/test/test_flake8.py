from pathlib import Path

from ament_flake8.main import main_with_errors
import pytest


CONFIG = Path(__file__).resolve().parents[3] / ".flake8"


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8():
    rc, errors = main_with_errors(argv=["--config", str(CONFIG)])
    assert rc == 0, "Found %d code style errors:\n" % len(errors) + "\n".join(
        errors
    )
