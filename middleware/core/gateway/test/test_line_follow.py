"""NAV-007 / D-143 line-follow policy is ROS-free and fail-closed."""

import math
import threading

import pytest

from core_events.events.bus import EventBus
from core_features.line_follow.manager import (
    LineFollowConfig,
    LineFollowManager,
    LineFollowMode,
    LineObservation,
)


@pytest.fixture
def rig():
    now = [100.0]
    events = EventBus("rosy_01")
    manager = LineFollowManager(
        events,
        config=LineFollowConfig(
            cruise_speed=0.09,
            max_linear=0.10,
            steering_gain=0.8,
            max_angular=0.7,
            min_confidence=0.35,
            stale_after_s=0.3,
            lost_after_s=3.0,
        ),
        clock=lambda: now[0],
    )
    return now, events, manager


def observation(source, *, error=0.0, confidence=0.9, visible=True, stamp=10.0):
    return LineObservation(
        source=LineFollowMode(source),
        stamp=stamp,
        visible=visible,
        error=error if visible else None,
        confidence=confidence if visible else 0.0,
    )


def test_off_is_zero_and_selecting_a_mode_waits_for_fresh_evidence(rig):
    now, _events, manager = rig
    assert manager.tick().linear == 0.0

    manager.set_mode(LineFollowMode.IR_LINE)
    decision = manager.tick()

    assert decision.linear == 0.0
    assert manager.status().state == "WAITING"
    assert manager.status().reason == "no_observation"


def test_only_the_selected_source_can_drive(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.IR_LINE)
    manager.observe(observation("CAMERA_LINE", error=0.5), received_at=now[0])
    assert manager.tick().linear == 0.0

    manager.observe(observation("IR_LINE", error=0.5), received_at=now[0])
    decision = manager.tick()
    assert decision.linear > 0.0
    assert decision.angular < 0.0
    assert manager.status().source == "IR_LINE"


def test_ir_fallback_readiness_uses_fresh_valid_matching_calibration_while_camera_selected(rig):
    now, _events, _manager = rig
    revision = "d" * 64
    manager = LineFollowManager(
        _events,
        config=LineFollowConfig(ir_calibration_revision=revision),
        clock=lambda: now[0],
    )
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    ir = LineObservation(
        source=LineFollowMode.IR_LINE, stamp=100.0, visible=True,
        error=0.1, confidence=0.9, ir_calibrated=True,
        calibration_revision=revision,
    )
    assert manager.observe(ir, received_at=now[0]) is False
    assert manager.ir_fallback_readiness() == (True, ())

    now[0] += 0.31
    ready, reasons = manager.ir_fallback_readiness()
    assert not ready
    assert reasons == ("IR_EVIDENCE_STALE",)


def test_speed_is_capped_and_adapts_to_error_and_confidence(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    manager.observe(observation("CAMERA_LINE", error=0.0, confidence=1.0), now[0])
    straight = manager.tick()

    manager.observe(observation("CAMERA_LINE", error=0.8, confidence=0.55), now[0])
    curve = manager.tick()

    assert straight.linear == pytest.approx(0.09)
    assert straight.linear <= 0.10
    assert 0.0 < curve.linear < straight.linear
    assert abs(curve.angular) <= 0.7


def test_low_confidence_missing_and_stale_observations_stop_immediately(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.IR_LINE)

    manager.observe(observation("IR_LINE", confidence=0.2), now[0])
    assert manager.tick().linear == 0.0
    assert manager.status().reason == "low_confidence"

    manager.observe(observation("IR_LINE", visible=False), now[0])
    assert manager.tick().linear == 0.0
    assert manager.status().reason == "line_not_visible"

    manager.observe(observation("IR_LINE"), now[0])
    now[0] += 0.31
    assert manager.tick().linear == 0.0
    assert manager.status().reason == "observation_stale"


def test_camera_loss_is_reported_as_camera_hold_and_never_reuses_previous_command(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    manager.observe(observation("CAMERA_LINE", error=0.4), now[0])
    assert manager.tick().linear > 0.0

    now[0] += 0.31
    decision = manager.tick()

    assert decision.linear == 0.0
    assert decision.angular == 0.0
    assert manager.status().state == "HOLD"
    assert manager.status().reason == "camera_observation_stale"


def test_three_second_loss_latches_and_emits_one_event_until_reselected(rig):
    now, events, manager = rig
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    manager.observe(observation("CAMERA_LINE"), now[0])
    assert manager.tick().linear > 0.0

    manager.observe(observation("CAMERA_LINE", visible=False), now[0])
    now[0] += 3.01
    assert manager.tick().linear == 0.0
    assert manager.status().state == "LOST"
    manager.tick()
    assert [event.type for event in events.history()].count("nav.lane_lost") == 1

    manager.observe(observation("CAMERA_LINE"), now[0])
    assert manager.tick().linear == 0.0
    assert manager.status().reason == "camera_reselection_required"

    manager.set_mode(LineFollowMode.OFF)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    manager.observe(observation("CAMERA_LINE"), now[0])
    assert manager.tick().linear > 0.0


def test_switching_source_discards_old_observation_and_command(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.IR_LINE)
    manager.observe(observation("IR_LINE", error=-0.5), now[0])
    assert manager.tick().linear > 0.0

    manager.set_mode(LineFollowMode.CAMERA_LINE)
    decision = manager.tick()
    assert decision.linear == 0.0
    assert decision.angular == 0.0
    assert manager.status().reason == "camera_no_observation"


@pytest.mark.parametrize("changes", [
    {"error": math.nan},
    {"error": 1.01},
    {"confidence": math.inf},
    {"confidence": -0.1},
    {"stamp": math.nan},
])
def test_invalid_observation_is_rejected_without_replacing_last_good(rig, changes):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.IR_LINE)
    manager.observe(observation("IR_LINE"), now[0])
    good = manager.tick()

    kwargs = dict(error=0.0, confidence=0.9, stamp=10.0)
    kwargs.update(changes)
    with pytest.raises(ValueError):
        observation("IR_LINE", **kwargs)

    assert manager.tick() == good


def test_invalid_wire_evidence_stops_an_active_command_immediately(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.IR_LINE)
    manager.observe(observation("IR_LINE"), now[0])
    assert manager.tick().linear > 0.0

    manager.invalidate(received_at=now[0])

    assert manager.tick().linear == 0.0
    assert manager.status().reason == "invalid_observation"


def test_full_confidence_threshold_has_no_division_by_zero():
    now = [1.0]
    manager = LineFollowManager(
        EventBus("rosy_01"),
        config=LineFollowConfig(min_confidence=1.0),
        clock=lambda: now[0],
    )
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    manager.observe(observation("CAMERA_LINE", confidence=1.0), now[0])

    assert manager.tick().linear > 0.0


def test_source_timestamp_age_can_make_a_just_received_sample_stale(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.CAMERA_LINE)

    manager.observe(
        observation("CAMERA_LINE", stamp=10.0),
        received_at=now[0], source_now=10.31,
    )

    assert manager.tick(now[0]).linear == 0.0
    assert manager.status().reason == "camera_observation_stale"


def test_future_source_timestamp_is_rejected(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.CAMERA_LINE)

    with pytest.raises(ValueError, match="future"):
        manager.observe(
            observation("CAMERA_LINE", stamp=10.0),
            received_at=now[0], source_now=9.0,
        )


def test_mode_switch_and_observation_are_thread_safe(rig):
    now, _events, manager = rig
    errors = []

    def switch_modes():
        try:
            for _ in range(500):
                manager.set_mode(LineFollowMode.IR_LINE)
                manager.set_mode(LineFollowMode.CAMERA_LINE)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    def feed_both_sources():
        try:
            for _ in range(500):
                manager.observe(observation("IR_LINE"), now[0])
                manager.observe(observation("CAMERA_LINE"), now[0])
                manager.tick(now[0])
                status = manager.status()
                if status.state == "TRACKING" and status.source != status.mode:
                    errors.append(AssertionError("tracking source differs from selected mode"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=switch_modes), threading.Thread(target=feed_both_sources)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []


def test_decision_cannot_be_applied_after_mode_generation_changes(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.IR_LINE)
    manager.observe(observation("IR_LINE"), now[0])
    old_decision = manager.tick(now[0])

    manager.set_mode(LineFollowMode.CAMERA_LINE)
    applied = []

    assert manager.apply_if_current(old_decision, applied.append) is False
    assert applied == []


def test_decision_cannot_be_applied_after_new_fail_closed_evidence(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.IR_LINE)
    manager.observe(observation("IR_LINE"), now[0])
    old_decision = manager.tick(now[0])

    manager.observe(LineObservation(
        source=LineFollowMode.IR_LINE,
        stamp=now[0],
        visible=False,
        error=None,
        confidence=0.0,
    ), now[0])
    applied = []

    assert manager.apply_if_current(old_decision, applied.append) is False
    assert applied == []


def test_decision_cannot_be_applied_after_invalidation(rig):
    now, _events, manager = rig
    manager.set_mode(LineFollowMode.IR_LINE)
    manager.observe(observation("IR_LINE"), now[0])
    old_decision = manager.tick(now[0])

    manager.invalidate(now[0])
    applied = []

    assert manager.apply_if_current(old_decision, applied.append) is False
    assert applied == []
