"""Runtime environment contract tests for supervised motion."""

import pytest

from fleet_navigation.supervised_motion import require_cyclonedds_rmw


def test_cyclonedds_rmw_is_required() -> None:
    require_cyclonedds_rmw(
        {"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"}
    )


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"RMW_IMPLEMENTATION": "rmw_fastrtps_cpp"},
    ],
)
def test_incompatible_rmw_is_rejected(environment) -> None:
    with pytest.raises(RuntimeError, match="rmw_cyclonedds_cpp"):
        require_cyclonedds_rmw(environment)
