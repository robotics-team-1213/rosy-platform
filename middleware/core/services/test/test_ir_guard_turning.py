"""D-344 §12 amendment 2026-10-10: below ir_guard_min_linear (a camera turn in place) the side IR
guard does not steer away; above it, and with the setting off, it does."""
from core_features.line_follow.model import LineFollowMode, LineObservation
from test_ir_guard_crosswalk import REV, rig


def turn(r, *, ir_error, confidence):
    clock, manager = r
    clock[0] = 1.0
    manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, 1.0, True, -0.5, confidence),
                    received_at=1.0, source_now=1.0)
    manager.observe(LineObservation(LineFollowMode.IR_LINE, 1.0, True, ir_error, 0.9, ir_calibrated=True,
                                    calibration_revision=REV), received_at=1.0, source_now=1.0)
    return manager.tick(1.0)


def test_turning_in_place_keeps_the_camera_turn():
    decision = turn(rig(ir_guard_min_linear=0.01), ir_error=-0.8, confidence=0.37)
    assert decision.angular > 0.0          # camera turns left; the left-edge guard would turn right


def test_moving_or_setting_off_still_steers_away():
    assert turn(rig(ir_guard_min_linear=0.01), ir_error=-0.8, confidence=0.9).angular < 0.0
    assert turn(rig(), ir_error=-0.8, confidence=0.37).angular < 0.0


def test_turning_in_place_over_a_line_under_the_centre_sensor_does_not_hold():
    decision = turn(rig(ir_guard_min_linear=0.01), ir_error=0.0, confidence=0.37)
    assert decision.angular > 0.0
    assert turn(rig(ir_guard_min_linear=0.01), ir_error=0.0, confidence=0.9).angular == 0.0


def test_backing_needs_a_seen_clear_rear():
    decision = turn(rig(ir_guard_min_linear=0.01, ir_guard_back_speed=0.02), ir_error=0.0, confidence=0.37)
    assert 0.0 <= decision.linear < 0.01 and decision.angular > 0.0  # no scan, no body: no backing
