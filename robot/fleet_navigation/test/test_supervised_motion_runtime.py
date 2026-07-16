"""Runtime environment contract tests for supervised motion."""

import pytest
import rclpy
from rclpy.parameter import Parameter

from fleet_navigation.supervised_motion import require_cyclonedds_rmw
from fleet_navigation.supervised_motion import SupervisedMotion


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


def test_pose_checkpoint_reset_requires_dry_run() -> None:
    rclpy.init()
    try:
        with pytest.raises(ValueError, match="only in dry-run"):
            SupervisedMotion(
                parameter_overrides=[
                    Parameter("reset_pose_checkpoint", value=True),
                ]
            )
    finally:
        rclpy.shutdown()
