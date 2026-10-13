"""D-407 개정 2026-10-10: CAMERA_LINE LOST resumes in the same mode once the lane is back."""

from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)
from test_line_follow_stuck import _manager as _stuck_manager, _run as _stuck_run

REV = "a" * 64
DT = 0.1


class _Events:
    def __init__(self):
        self.events = []

    def publish(self, name, severity="info", source="", data=None):
        self.events.append((name, data or {}))

    def named(self, name):
        return [d for n, d in self.events if n == name]


def _manager(**overrides):
    events = _Events()
    m = LineFollowManager(events, config=LineFollowConfig(**overrides), clock=lambda: 0.0)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    return m, events


def _camera(m, t, seen=True):
    m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=seen,
                              error=0.0 if seen else None, confidence=0.9 if seen else 0.0),
              received_at=t, source_now=t)


def _ir(m, t, error=None):
    m.observe(LineObservation(source=LineFollowMode.IR_LINE, stamp=t, visible=error is not None,
                              error=error, confidence=0.9 if error is not None else 0.0,
                              ir_calibrated=True, calibration_revision=REV),
              received_at=t, source_now=t)


def _run(m, start, stop, *, seen=True, each=None):
    t, decision = start, None
    while t < stop - 1e-9:
        _camera(m, t, seen)
        if each is not None:
            each(m, t)
        decision = m.tick(t + 0.01)
        t = round(t + DT, 6)
    return decision, t


def _lost(m, each=None):
    _run(m, 0.0, 0.5, each=each)
    _, t = _run(m, 0.5, 4.0, seen=False, each=each)
    assert m.status().state == "LOST" and m.status().reason == "camera_reselection_required"
    return t


def test_lost_resumes_in_the_same_mode_after_stable_frames():
    m, events = _manager()
    t = _lost(m)
    generation = m._generation
    decision, t = _run(m, t, t + 0.95)               # 10 frames, but only 0.91 s
    assert decision.linear == 0.0 and m.status().state == "LOST"
    assert events.named("nav.lane_reacquired") == []
    decision, _ = _run(m, t, t + 0.2)
    assert decision.linear > 0.0 and m.status().state == "TRACKING"
    assert m.mode is LineFollowMode.CAMERA_LINE and m._generation == generation
    assert len(events.named("nav.lane_reacquired")) == 1


def test_flickering_lane_does_not_resume():
    m, events = _manager()
    t = _lost(m)
    for k in range(40):
        ts = round(t + k * DT, 6)
        _camera(m, ts, seen=k % 2 == 0)
        assert m.tick(ts + 0.01).linear == 0.0
    assert m.status().state == "LOST" and events.named("nav.lane_reacquired") == []


def test_one_frame_then_silence_does_not_resume():
    m, _ = _manager()
    t = _lost(m)
    _camera(m, t)
    for k in range(30):
        assert m.tick(t + 0.01 + k * DT).linear == 0.0
    assert m.status().state == "LOST"


def test_disabled_keeps_the_reselection_latch():
    m, _ = _manager(lost_auto_resume=False)
    t = _lost(m)
    decision, _ = _run(m, t, t + 3.0)
    assert decision.linear == 0.0 and m.status().reason == "camera_reselection_required"


def test_no_resume_while_an_obstacle_holds_then_resumes_when_it_clears():
    m, events = _manager()
    t = _lost(m)
    decision, t = _run(m, t, t + 2.0, each=lambda m, ts: m.observe_clearance(0.05, received_at=ts))
    assert decision.linear == 0.0 and m.status().reason == "obstacle_ahead"
    assert m._lost_latched and events.named("nav.lane_reacquired") == []
    decision, _ = _run(m, t, t + 0.5, each=lambda m, ts: m.observe_clearance(None, received_at=ts))
    assert decision.linear > 0.0 and m.status().state == "TRACKING"


def test_no_resume_on_ir_departure_or_edge_then_resumes_when_ir_clear():
    m, events = _manager(ir_guard_enabled=True, ir_calibration_revision=REV)
    t = _lost(m, each=lambda m, ts: _ir(m, ts))
    decision, t = _run(m, t, t + 2.0, each=lambda m, ts: _ir(m, ts, error=0.0))
    assert decision.linear == 0.0 and m.status().reason == "lane_departure" and m._lost_latched
    decision, t = _run(m, t, t + 2.0, each=lambda m, ts: _ir(m, ts, error=-0.9))
    assert decision.linear == 0.0 and m.status().state == "LOST"
    assert events.named("nav.lane_reacquired") == []
    decision, _ = _run(m, t, t + 0.3, each=lambda m, ts: _ir(m, ts))
    assert decision.linear > 0.0 and m.status().state == "TRACKING"


def test_ir_line_keeps_the_reselection_latch():
    m, _ = _manager(ir_calibration_revision=REV)
    m.set_mode(LineFollowMode.IR_LINE)
    t = 0.0
    while t < 4.0:
        _ir(m, t)                                    # nothing under the IR row
        m.tick(t + 0.01)
        t = round(t + DT, 6)
    while t < 7.0:
        _ir(m, t, error=0.0)
        assert m.tick(t + 0.01).linear == 0.0
        t = round(t + DT, 6)
    assert m.status().reason == "reselection_required"


def test_stuck_back_off_flow_ends_in_resume_when_the_lane_returns():
    # 8kcn 2026-10-10: not visible -> back-off -> stuck_resumed -> LOST for 40 s with 0.9 frames.
    m, events = _stuck_manager(linked=False)
    _stuck_run(m, 0.0, 0.5, front=1.0)
    _stuck_run(m, 0.5, 30.0, front=1.0, lane=False)
    assert m.status().state == "LOST" and events.named("nav.line_stuck_opened")
    decision = _stuck_run(m, 30.0, 31.5, front=1.0)
    assert decision.linear > 0.0 and m.status().state == "TRACKING"
    assert m.status().stuck is None and len(events.named("nav.lane_reacquired")) == 1
