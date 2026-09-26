"""Static integration contracts for the ROS motor command path."""

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRINGUP = ROOT / "src" / "devices" / "pinky_pro" / "bringup"


def test_launch_exposes_all_motor_limits_to_the_node():
    launch = (BRINGUP / "launch" / "bringup_robot.launch.py").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(launch.split())

    for name, default in (
        ("max_linear_mps", "0.20"),
        ("max_angular_rps", "0.80"),
        ("max_wheel_rpm", "100.0"),
        ("motor_profile_acceleration", "200"),
    ):
        assert f"DeclareLaunchArgument('{name}', default_value='{default}')" in normalized
        assert re.search(
            rf"'{name}'\s*:\s*LaunchConfiguration\(\s*'{name}'\s*\)",
            launch,
        )


def test_launch_loads_the_pinky_profile_before_runtime_overrides():
    launch = (BRINGUP / "launch" / "bringup_robot.launch.py").read_text(
        encoding="utf-8"
    )
    assert "pinky_pro_adapter.yaml" in launch
    assert "rosy_params.yaml" in launch
    assert launch.index("pinky_pro_adapter.yaml") < launch.index("rosy_params.yaml")


def test_bringup_validates_ros_values_through_the_board_adapter_before_sdk():
    source = (BRINGUP / "bringup" / "bringup.py").read_text(encoding="utf-8")
    assert "from .pinky_pro_adapter import PinkyProAdapter" in source
    assert "self.pinky_pro_adapter = PinkyProAdapter.from_mapping" in source
    assert source.index("PinkyProAdapter.from_mapping") < source.index("DynamixelDriver(")


def test_node_uses_structured_controller_instead_of_inline_kinematics():
    source = (BRINGUP / "bringup" / "bringup.py").read_text(encoding="utf-8")

    assert "MotorController(" in source
    assert "DriveGeometry(" in source
    assert "DriveLimits(" in source
    assert "self.motor_controller.command_twist(" in source
    assert "profile_accel=self.motor_profile_acceleration" in source
    assert "outcome.status is CommandStatus.LIMITED" in source
    assert "v_l = linear_x" not in source
    assert "MAX_RPM =" not in source


def test_node_stops_immediately_on_rejection_and_confirms_deadman_stop():
    source = (BRINGUP / "bringup" / "bringup.py").read_text(encoding="utf-8")

    assert "stop_outcome = self.motor_controller.stop()" in source
    assert "if stop_outcome.accepted:" in source
    assert "self.command_deadman.mark_stopped()" in source
    assert "self.command_deadman.mark_stop_required()" in source
    assert "lambda: self.motor_controller.stop().accepted" in source


def test_node_uses_rollover_safe_encoder_delta():
    source = (BRINGUP / "bringup" / "bringup.py").read_text(encoding="utf-8")

    assert "wrapped_encoder_delta(encoder_l, self.last_encoder_l)" in source
    assert "wrapped_encoder_delta(encoder_r, self.last_encoder_r)" in source


def test_node_preserves_parameter_types_for_strict_driver_validation():
    source = (BRINGUP / "bringup" / "bringup.py").read_text(encoding="utf-8")

    assert "raw_motor_ids = list(self.get_parameter('motor_ids').value)" in source
    assert "self.motor_ids = list(validate_motor_ids(raw_motor_ids))" in source
    assert "self.motor_ids = [int(" not in source
    assert re.search(
        r"raw_profile_acceleration\s*=\s*self\.get_parameter\(\s*"
        r"'motor_profile_acceleration'\s*\)\.value",
        source,
    )
    assert re.search(
        r"self\.motor_profile_acceleration\s*=\s*validate_profile_acceleration\(\s*"
        r"raw_profile_acceleration\s*\)",
        source,
    )


def test_node_constructor_failure_always_terminates_motor_driver():
    source = (BRINGUP / "bringup" / "bringup.py").read_text(encoding="utf-8")
    normalized = " ".join(source.split())

    assert "try: self.get_logger().info('1. Opening serial port...')" in normalized
    assert "except Exception: self.driver.terminate() raise" in normalized


def test_bringup_publishes_a_latched_motor_readiness_lease():
    source = (BRINGUP / "bringup" / "bringup.py").read_text(encoding="utf-8")

    assert "MOTOR_READY_TOPIC = \"motor/ready\"" in source
    assert "TRANSIENT_LOCAL" in source
    assert "self.motor_ready_pub.publish(Bool(data=False))" in source
    assert "self.motor_ready_pub.publish(Bool(data=True))" in source


# --- D-192 no-motion hardware mode -------------------------------------------


def test_no_motion_mode_keeps_torque_off_and_never_listens_to_cmd_vel():
    source = (BRINGUP / "bringup" / "bringup.py").read_text(encoding="utf-8")
    normalized = " ".join(source.split())

    assert "self.declare_parameter('drive_enabled', True, ParameterDescriptor(" in source
    assert "read_only=True," in source
    assert "enable_torque=self.drive_enabled," in source
    # The only cmd_vel subscription is behind the drive flag.
    assert source.count("create_subscription( Twist") + source.count("create_subscription(\n") >= 1
    assert "if self.drive_enabled: self.twist_sub = self.create_subscription( Twist," in normalized
    # No initial goal write when torque is off, no readiness lease offered.
    assert "if self.drive_enabled: self.get_logger().info('3. Setting initial RPM to zero...')" in normalized
    assert "if self.is_initialized and self.drive_enabled:" in source
    assert "self.motor_ready_pub.publish(Bool(data=self.drive_enabled))" in source


def test_launch_passes_drive_enabled_as_a_boolean_defaulting_to_drive():
    launch = (BRINGUP / "launch" / "bringup_robot.launch.py").read_text(encoding="utf-8")
    normalized = " ".join(launch.split())

    assert "DeclareLaunchArgument( 'drive_enabled', default_value='true'," in normalized
    assert ("'drive_enabled': ParameterValue( LaunchConfiguration('drive_enabled'), "
            "value_type=bool )") in normalized


def test_native_io_unit_defaults_to_no_motion_and_navigation_drives():
    native = ROOT / "deploy" / "robot" / "native"
    io = (native / "rosy-io.service").read_text(encoding="utf-8")
    nav = (native / "rosy-navigation.service").read_text(encoding="utf-8")

    # EnvironmentFile= overrides Environment=, so runtime.env can opt in.
    assert io.index("Environment=ROSY_IO_DRIVE_ENABLED=false") < io.index(
        "EnvironmentFile=/etc/rosy/runtime.env")
    assert "drive_enabled:=${ROSY_IO_DRIVE_ENABLED}" in io
    assert "enable_battery:=true" in io
    # Navigation is gated by its approvals and needs the drive.
    assert "drive_enabled" not in nav
    assert "ROSY_IO_DRIVE_ENABLED" not in (native / "rosy-runtime.env").read_text(encoding="utf-8")


def _drive_gate() -> str:
    """rosy-io's ExecStartPre shell body, with systemd's $$ turned into $."""
    unit = (ROOT / "deploy" / "robot" / "native" / "rosy-io.service").read_text(encoding="utf-8")
    line = next(line for line in unit.splitlines() if line.startswith("ExecStartPre="))
    assert line.startswith("ExecStartPre=/usr/bin/bash --noprofile --norc -c '") and line.endswith("'")
    body = line[len("ExecStartPre=/usr/bin/bash --noprofile --norc -c '"):-1]
    # A lone $NAME would be systemd's to expand; the gate must read the environment.
    assert re.search(r"(?<!\$)\$(?!\$)", body) is None
    return body.replace("$$", "$")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash runs the unit's gate")
@pytest.mark.parametrize(
    ("value", "starts"),
    [("true", True), ("false", True), ("yes", False), ("True", False), ("1", False),
     ("", False), ("false ", False), ("on", False), ("true; reboot", False)],
)
def test_io_unit_starts_only_with_exactly_true_or_false(value, starts):
    # D-192 review: launch_ros would read "yes"/"1"/"True" as a boolean and drive.
    env = dict(os.environ, ROSY_IO_DRIVE_ENABLED=value)
    completed = subprocess.run([shutil.which("bash"), "--noprofile", "--norc", "-c", _drive_gate()],
                               env=env, capture_output=True, text=True, check=False)
    assert (completed.returncode == 0) is starts, completed.stderr
    if not starts:
        assert completed.returncode == 78
        assert "ROSY_IO_DRIVE_ENABLED must be true or false" in completed.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash runs the unit's gate")
def test_io_unit_gate_fails_closed_when_the_variable_is_unset():
    env = {key: value for key, value in os.environ.items() if key != "ROSY_IO_DRIVE_ENABLED"}
    completed = subprocess.run([shutil.which("bash"), "--noprofile", "--norc", "-c", _drive_gate()],
                               env=env, capture_output=True, text=True, check=False)
    assert completed.returncode == 78
