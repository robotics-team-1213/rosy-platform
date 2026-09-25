"""Behavior contracts for ROS-independent differential-drive motor control."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "devices" / "pinky_pro" / "bringup"))

from bringup.motor_control import (  # noqa: E402
    CommandStatus,
    DriveGeometry,
    DriveLimits,
    MotorController,
    plan_twist,
)


GEOMETRY = DriveGeometry(wheel_radius_m=0.027, wheel_separation_m=0.0961)
LIMITS = DriveLimits(
    max_linear_mps=0.25,
    max_angular_rps=2.5,
    max_wheel_rpm=100.0,
)


def test_plan_straight_motion_uses_opposed_motor_mounting_signs():
    plan = plan_twist(0.1, 0.0, GEOMETRY, LIMITS)

    assert plan.left_rpm == pytest.approx(35.3678, rel=1e-4)
    assert plan.right_rpm == pytest.approx(-35.3678, rel=1e-4)
    assert plan.applied_linear_mps == pytest.approx(0.1)
    assert plan.applied_angular_rps == pytest.approx(0.0)
    assert plan.limited is False
    assert plan.limit_reasons == ()


def test_plan_positive_rotation_commands_both_motors_negative():
    plan = plan_twist(0.0, 1.0, GEOMETRY, LIMITS)

    assert plan.left_rpm == pytest.approx(-16.9945, rel=1e-4)
    assert plan.right_rpm == pytest.approx(-16.9945, rel=1e-4)
    assert plan.limited is False


def test_plan_combines_translation_and_rotation():
    plan = plan_twist(0.1, 0.5, GEOMETRY, LIMITS)

    assert plan.left_rpm == pytest.approx(26.8706, rel=1e-4)
    assert plan.right_rpm == pytest.approx(-43.8650, rel=1e-4)


def test_plan_limits_axes_then_scales_both_wheels_to_preserve_curvature():
    limits = DriveLimits(
        max_linear_mps=0.2,
        max_angular_rps=1.0,
        max_wheel_rpm=50.0,
    )

    plan = plan_twist(0.4, 2.0, GEOMETRY, limits)

    assert max(abs(plan.left_rpm), abs(plan.right_rpm)) == pytest.approx(50.0)
    assert plan.applied_linear_mps / plan.applied_angular_rps == pytest.approx(0.2)
    assert plan.limited is True
    assert plan.limit_reasons == (
        "linear speed limited",
        "angular speed limited",
        "wheel RPM limited",
    )


@pytest.mark.parametrize(
    ("linear", "angular"),
    [(float("nan"), 0.0), (0.0, float("inf")), ("fast", 0.0)],
)
def test_plan_rejects_non_finite_or_non_numeric_commands(linear, angular):
    with pytest.raises(ValueError, match="finite number"):
        plan_twist(linear, angular, GEOMETRY, LIMITS)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: DriveGeometry(wheel_radius_m=0.0, wheel_separation_m=0.1),
        lambda: DriveGeometry(wheel_radius_m=0.03, wheel_separation_m=float("nan")),
        lambda: DriveLimits(0.0, 1.0, 100.0),
        lambda: DriveLimits(0.2, -1.0, 100.0),
        lambda: DriveLimits(0.2, 1.0, float("inf")),
    ],
)
def test_geometry_and_limits_require_positive_finite_values(factory):
    with pytest.raises(ValueError, match="positive finite number"):
        factory()


class RecordingMotorSink:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    def __call__(self, left_rpm, right_rpm):
        self.calls.append((left_rpm, right_rpm))
        return self.accepted


def test_controller_reports_applied_command_and_wheel_values():
    sink = RecordingMotorSink()
    controller = MotorController(GEOMETRY, LIMITS, sink)

    outcome = controller.command_twist(0.1, 0.0)

    assert outcome.status is CommandStatus.APPLIED
    assert outcome.accepted is True
    assert outcome.reason == "command applied"
    assert sink.calls == [(outcome.plan.left_rpm, outcome.plan.right_rpm)]


def test_controller_reports_limited_when_any_bound_changes_the_command():
    sink = RecordingMotorSink()
    controller = MotorController(GEOMETRY, LIMITS, sink)

    outcome = controller.command_twist(2.0, 0.0)

    assert outcome.status is CommandStatus.LIMITED
    assert outcome.accepted is True
    assert outcome.plan.limited is True
    assert "linear speed limited" in outcome.reason


def test_controller_rejects_invalid_command_without_touching_driver():
    sink = RecordingMotorSink()
    controller = MotorController(GEOMETRY, LIMITS, sink)

    outcome = controller.command_twist(float("nan"), 0.0)

    assert outcome.status is CommandStatus.REJECTED
    assert outcome.accepted is False
    assert outcome.plan is None
    assert "finite number" in outcome.reason
    assert sink.calls == []


def test_controller_reports_driver_error_when_uart_write_is_rejected():
    sink = RecordingMotorSink(accepted=False)
    controller = MotorController(GEOMETRY, LIMITS, sink)

    outcome = controller.command_twist(0.1, 0.0)

    assert outcome.status is CommandStatus.DRIVER_ERROR
    assert outcome.accepted is False
    assert outcome.plan is not None
    assert outcome.reason == "motor driver rejected wheel RPM"


def test_controller_contains_driver_exception_as_structured_error():
    def failing_sink(_left_rpm, _right_rpm):
        raise OSError("UART disconnected")

    controller = MotorController(GEOMETRY, LIMITS, failing_sink)

    outcome = controller.command_twist(0.1, 0.0)

    assert outcome.status is CommandStatus.DRIVER_ERROR
    assert outcome.accepted is False
    assert outcome.reason == "motor driver error: UART disconnected"


def test_stop_is_an_explicit_confirmed_zero_command():
    sink = RecordingMotorSink()
    controller = MotorController(GEOMETRY, LIMITS, sink)

    outcome = controller.stop()

    assert outcome.status is CommandStatus.APPLIED
    assert outcome.accepted is True
    assert outcome.reason == "stop applied"
    assert sink.calls == [(0.0, -0.0)]
    assert outcome.plan.is_stop is True


def test_nonzero_plan_is_not_reported_as_stop():
    assert plan_twist(0.01, 0.0, GEOMETRY, LIMITS).is_stop is False
