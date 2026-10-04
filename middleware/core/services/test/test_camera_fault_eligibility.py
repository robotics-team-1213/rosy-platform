from core_features.recovery.camera_fault import CameraFaultEvidence, evaluate_camera_fault


def test_camera_fault_never_switches_to_ir_without_all_local_evidence():
    evidence = CameraFaultEvidence(
        active_task="line_follow", selected_action="IR_LINE", mode="motor",
        ir_calibrated=True, ir_calibration_revision="ir-r1",
        expected_ir_calibration_revision="ir-r1", ir_age_s=0.05,
        ir_line_valid=True, ir_line_age_s=0.05, lidar_age_s=0.05,
        localization_valid=False, stopped_readback=True, g4_passed=True, g5_passed=True,
    )

    result = evaluate_camera_fault(evidence, now=10.0)

    assert result.allowed_actions == ()
    assert "MOTOR_MODE" in result.reasons
    assert result.selected_action is None


def test_camera_free_ir_demo_requires_calibration_and_fresh_sensors_and_stop():
    evidence = CameraFaultEvidence(
        active_task=None, selected_action="IR_LINE", mode="navigation",
        ir_calibrated=True, ir_calibration_revision="ir-r1",
        expected_ir_calibration_revision="ir-r1", ir_age_s=0.05,
        ir_line_valid=True, ir_line_age_s=0.05, lidar_age_s=0.05,
        localization_valid=True, stopped_readback=False, g4_passed=True, g5_passed=True,
    )

    result = evaluate_camera_fault(evidence, now=10.0)

    assert result.allowed_actions == ()
    assert "STOP_NOT_READ_BACK" in result.reasons


def test_only_explicitly_selected_eligible_camera_free_action_is_returned():
    evidence = CameraFaultEvidence(
        active_task=None, selected_action="IR_LINE", mode="navigation",
        ir_calibrated=True, ir_calibration_revision="ir-r1",
        expected_ir_calibration_revision="ir-r1", ir_age_s=0.05,
        ir_line_valid=True, ir_line_age_s=0.05, lidar_age_s=0.05,
        localization_valid=True, stopped_readback=True, g4_passed=True, g5_passed=True,
    )

    result = evaluate_camera_fault(evidence, now=10.0)

    assert result.allowed_actions == ("IR_LINE",)
    assert result.selected_action == "IR_LINE"
    assert result.expires_at == 10.25


def test_running_camera_dependent_task_must_be_cleared_before_alternate_work():
    evidence = CameraFaultEvidence(
        active_task="line_follow", selected_action="IR_LINE", mode="navigation",
        ir_calibrated=True, ir_calibration_revision="ir-r1",
        expected_ir_calibration_revision="ir-r1", ir_age_s=0.05,
        ir_line_valid=True, ir_line_age_s=0.05, lidar_age_s=0.05,
        localization_valid=True, stopped_readback=True, g4_passed=True, g5_passed=True,
    )

    result = evaluate_camera_fault(evidence, now=10.0)

    assert result.allowed_actions == ()
    assert "ACTIVE_TASK_NOT_CLEARED" in result.reasons
    assert result.selected_action is None


def test_missing_ir_calibration_and_stale_ir_fail_closed():
    evidence = CameraFaultEvidence(
        active_task="line_follow", selected_action="IR_LINE", mode="navigation",
        ir_calibrated=False, ir_calibration_revision=None,
        expected_ir_calibration_revision="ir-r1", ir_age_s=1.0,
        ir_line_valid=False, ir_line_age_s=1.0, lidar_age_s=0.05,
        localization_valid=True, stopped_readback=True, g4_passed=True, g5_passed=True,
    )

    result = evaluate_camera_fault(evidence, now=10.0)

    assert result.allowed_actions == ()
    assert {"IR_NOT_CALIBRATED", "IR_STALE", "IR_LINE_NOT_VALID",
            "IR_LINE_STALE"}.issubset(result.reasons)
