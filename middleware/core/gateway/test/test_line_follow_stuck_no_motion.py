"""2026-10-10 user: an active line mode that commands zero for stuck_report_s (5 s), for any
reason, opens a D-407 stuck (cause no_motion) that only Fleet or a person answers."""

import pytest

from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)

GEOMETRY = dict(body_lidar_x_m=-0.017, body_rear_x_m=-0.076, body_rotation_radius_m=0.08257)
REAR_FROM_LIDAR = 0.059
CAM, IR = LineFollowMode.CAMERA_LINE, LineFollowMode.IR_LINE


class _Events:
    def __init__(self):
        self.events = []

    def publish(self, name, severity="info", source="", data=None):
        self.events.append((name, data or {}))

    def named(self, name):
        return [d for n, d in self.events if n == name]


def _manager(*, angular=0.5, **overrides):
    events = _Events()
    config = LineFollowConfig(**{"recovery_local_enabled": True, **GEOMETRY, **overrides})
    m = LineFollowManager(events, config=config, clock=lambda: 0.0, angular_ceiling=lambda: angular)
    m.bind_recovery(console_linked=lambda: False, calibration_active=lambda: False,
                    linear_ceiling=lambda: 0.15, preview_seq=lambda: 7)
    m.set_mode(CAM)
    return m, events


def _scan(m, t, front=1.0, rear=0.30):
    m.observe_clearance(front, received_at=t)
    m.observe_body_points([(front, 0.0), (-(rear + REAR_FROM_LIDAR), 0.0)], range_min=0.0,
                          received_at=t)


def _lane(m, t, **kw):
    m.observe(LineObservation(source=CAM, stamp=t, visible=True, error=0.0, confidence=0.9, **kw),
              received_at=t, source_now=t)


def _ir_centre(m, t):
    m.observe(LineObservation(source=IR, stamp=t, visible=True, error=0.0, confidence=0.9,
                              ir_calibrated=True), received_at=t, source_now=t)


#: reason -> (config overrides, angular ceiling, per-tick feed)
CASES = {
    "nominal_ground_requires_driver": (
        {}, 0.5, lambda m, t: (_scan(m, t), _lane(m, t, ground="NOMINAL"))),
    "angular_limit_zero": ({}, 0.0, lambda m, t: (_scan(m, t), _lane(m, t))),
    "obstacle_sensor_stale": ({}, 0.5, lambda m, t: _lane(m, t)),     # one scan at t=0, then none
    "lane_departure": ({"ir_guard_enabled": True}, 0.5,
                       lambda m, t: (_scan(m, t), _lane(m, t), _ir_centre(m, t))),
}


def _run(m, feed, start, stop):
    t, decision = start, None
    while t < stop - 1e-9:
        feed(m, t)
        decision = m.tick(t + 0.01)
        t = round(t + 0.1, 6)
    return decision


def _case(reason):
    overrides, angular, feed = CASES[reason]
    m, events = _manager(angular=angular, **overrides)
    _scan(m, 0.0)
    return m, events, feed


@pytest.mark.parametrize("reason", sorted(CASES))
def test_any_zero_command_reason_opens_one_no_motion_stuck_after_5_s(reason):
    m, events, feed = _case(reason)
    _run(m, feed, 0.0, 4.8)
    assert events.named("nav.line_stuck_opened") == [], reason        # not before 5 s
    decision = _run(m, feed, 4.8, 7.0)
    opened = events.named("nav.line_stuck_opened")
    assert [(o["cause"], o["detail"]) for o in opened] == [("no_motion", m.status().stuck.detail)]
    assert opened[0]["detail"] == reason
    stuck = m.status().stuck
    assert stuck.cause == "no_motion" and stuck.phase == "WAITING_CONSOLE"
    assert stuck.ask_remaining_s is None                               # no local fallback timer
    assert [a["reason"] for a in events.named("nav.line_stuck_asked")] == ["no_motion"]
    assert decision.linear == 0.0 and decision.angular == 0.0          # never backs off unasked
    assert events.named("nav.line_stuck_local_attempt") == []


def test_tracking_never_opens_one():
    m, events = _manager()
    _run(m, lambda m, t: (_scan(m, t), _lane(m, t)), 0.0, 12.0)
    assert m.status().state == "TRACKING"
    assert events.named("nav.line_stuck_opened") == []


def test_off_never_opens_one():
    m, events, feed = _case("nominal_ground_requires_driver")
    m.set_mode(LineFollowMode.OFF)
    _run(m, feed, 0.0, 12.0)
    assert events.named("nav.line_stuck_opened") == []


def test_stuck_report_s_zero_turns_it_off():
    m, events = _manager(stuck_report_s=0.0)
    _run(m, CASES["nominal_ground_requires_driver"][2], 0.0, 12.0)
    assert events.named("nav.line_stuck_opened") == []


def test_config_rejects_a_negative_report_time():
    with pytest.raises(ValueError, match="stuck_report_s"):
        LineFollowConfig(stuck_report_s=-1.0)


def test_motion_again_closes_it_as_cleared():
    m, events, feed = _case("nominal_ground_requires_driver")
    _run(m, feed, 0.0, 6.0)
    assert m.status().stuck is not None
    _run(m, lambda m, t: (_scan(m, t), _lane(m, t)), 6.0, 6.5)
    assert [c["reason"] for c in events.named("nav.line_stuck_closed")] == ["cleared"]
    assert m.status().stuck is None and m.status().state == "TRACKING"


def test_fleet_back_and_retry_is_rechecked_and_driven_by_core():
    m, events, feed = _case("nominal_ground_requires_driver")
    _run(m, feed, 0.0, 6.0)
    stuck_id = m.status().stuck.stuck_id
    assert m.stuck_decision(stuck_id, "BACK_AND_RETRY", by="fleet-resolver", now=6.0) == "back"
    feed(m, 6.0)
    back = m.tick(6.01)
    assert back.linear == pytest.approx(-0.03) and back.angular == 0.0
    assert m.status().reason == "stuck_back_off"


def test_fleet_back_and_retry_refused_when_the_rear_is_blocked():
    m, events = _manager()
    def feed(m, t):
        _scan(m, t, rear=0.02)
        _lane(m, t, ground="NOMINAL")

    _run(m, feed, 0.0, 6.0)
    with pytest.raises(Exception, match="rear_blocked"):
        m.stuck_decision(m.status().stuck.stuck_id, "BACK_AND_RETRY", by="fleet-resolver", now=6.0)
    assert m.tick(6.01).linear == 0.0
