"""D-407 개정 / D-607 (2026-10-10): line-follow commands motion but odom stays put -> a Fleet-only
stuck (cause no_progress, or dithering with >= 2 sign flips). Detection never changes the motion."""
from types import SimpleNamespace

import pytest

from core.bridge import traffic_gate
from core_common.robot_body import PINKY_PRO as B
from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)
from core_features.line_follow.progress_watch import ProgressWatch

BODY = dict(body_front_x_m=B.front_x_m, body_rear_x_m=B.rear_x_m, body_half_width_m=B.half_width_m,
            body_rotation_radius_m=B.rotation_radius_m, body_lidar_x_m=B.lidar_x_m)
CAM = LineFollowMode.CAMERA_LINE


class _Events:
    def __init__(self):
        self.events = []

    def publish(self, name, severity="info", source="", data=None):
        self.events.append((name, data or {}))

    def named(self, name):
        return [d for n, d in self.events if n == name]


class _Command:
    twist = None

    def set_nav_twist(self, twist, now=None):
        self.twist = twist

    def clear_navigation(self):
        self.twist = None


class _Traffic:
    """Passes the line twist, or zeroes it while ``held`` (a D-525 signal / D-517 M4 wait)."""

    held = False

    def gate(self, linear, angular, now):
        return SimpleNamespace(linear=0.0 if self.held else linear, angular=0.0 if self.held else angular)

    def apply_if_current(self, decision, apply):
        apply(decision)
        return True


def _manager(**overrides):
    events = _Events()
    m = LineFollowManager(events, config=LineFollowConfig(**{**BODY, **overrides}), clock=lambda: 0.0,
                          angular_ceiling=lambda: 0.5)
    m.bind_recovery(console_linked=lambda: True, calibration_active=lambda: False,
                    linear_ceiling=lambda: 0.15, preview_seq=lambda: 1)
    m.set_mode(CAM)
    return m, events


def _drive(m, start, stop, *, error=lambda t: 0.0, x=lambda t: 0.0, lane=lambda t: True, traffic=None):
    """20 Hz: odom at x(t), a camera frame when lane(t), one tick through the real traffic seam."""
    traffic, command, t, issued = traffic or _Traffic(), _Command(), start, []
    while t < stop - 1e-9:
        m.observe_clearance(1.0, received_at=t)
        m.observe_body_points([(1.0, 0.0), (-0.40, 0.0)], range_min=0.0, received_at=t)
        stamp = round(t * 1e9)
        m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom", x=x(t), y=0.0, yaw=0.0,
                              received_at=t)
        if lane(t):
            m.observe(LineObservation(source=CAM, stamp=t, visible=True, error=error(t), confidence=0.9),
                      received_at=t, source_now=t)
        traffic_gate.apply_line_candidate(m, traffic, command, m.tick(t + 0.01), t + 0.01)
        issued.append(command.twist)
        t = round(t + 0.05, 6)
    return issued


def test_commanded_but_still_opens_no_progress_and_keeps_driving():
    m, events = _manager()
    _drive(m, 0.0, 4.9)
    assert events.named("nav.line_stuck_opened") == []                 # not before 5 s of odom
    issued = _drive(m, 4.9, 6.0)
    opened = events.named("nav.line_stuck_opened")
    assert [o["cause"] for o in opened] == ["no_progress"]
    stuck = m.status().stuck
    assert stuck.phase == "WAITING_CONSOLE" and stuck.ask_remaining_s is None and stuck.detail
    assert [a["reason"] for a in events.named("nav.line_stuck_asked")] == ["no_progress"]
    assert issued[-1].linear > 0.0                                      # report only: still drives
    assert events.named("nav.line_stuck_local_attempt") == []


def test_steering_flips_in_place_open_dithering():
    m, events = _manager()
    _drive(m, 0.0, 6.0, error=lambda t: 0.3 if int(t) % 2 else -0.3)
    assert [o["cause"] for o in events.named("nav.line_stuck_opened")] == ["dithering"]


def test_hold_drive_alternation_does_not_restart_the_window():
    m, events = _manager()
    _drive(m, 0.0, 7.0, lane=lambda t: (t % 1.0) < 0.5)                 # camera stale half of each second
    assert [o["cause"] for o in events.named("nav.line_stuck_opened")] == ["no_progress"]


def test_progress_closes_it_as_cleared():
    m, events = _manager()
    _drive(m, 0.0, 6.0)
    assert m.status().stuck is not None
    _drive(m, 6.0, 12.0, x=lambda t: 0.03 * (t - 6.0))                  # a body length in 5 s
    assert [c["reason"] for c in events.named("nav.line_stuck_closed")] == ["cleared"]
    assert m.status().stuck is None


def test_normal_driving_never_opens_one():
    m, events = _manager()
    _drive(m, 0.0, 30.0, x=lambda t: 0.03 * t)
    assert events.named("nav.line_stuck_opened") == []


def test_slow_creep_under_restuck_m_in_restuck_s_is_no_progress():
    m, events = _manager()
    _drive(m, 0.0, 19.0, x=lambda t: 0.013 * t)                        # 0.065 m per 5 s: moving
    assert events.named("nav.line_stuck_opened") == []
    _drive(m, 19.0, 21.5, x=lambda t: 0.013 * t)                       # 0.26 m in 20 s < 0.30
    assert [o["cause"] for o in events.named("nav.line_stuck_opened")] == ["no_progress"]


def test_a_traffic_wait_is_not_a_stuck():
    m, events = _manager()
    traffic = _Traffic()
    traffic.held = True
    _drive(m, 0.0, 12.0, traffic=traffic)
    assert events.named("nav.line_stuck_opened") == []


def test_fleet_wait_holds_the_robot():
    m, events = _manager()
    _drive(m, 0.0, 6.0)
    sid = m.status().stuck.stuck_id
    assert m.stuck_decision(sid, "WAIT", by="fleet-resolver", now=6.0) == "hold"
    issued = _drive(m, 6.0, 8.0)
    assert issued[-1].linear == 0.0 and issued[-1].angular == 0.0
    assert m.status().stuck.stuck_id == sid                             # still stuck: no progress


def test_no_urdf_body_no_rule():
    m, events = _manager(body_front_x_m=None)
    _drive(m, 0.0, 12.0)
    assert events.named("nav.line_stuck_opened") == []


def test_config_rejects_a_non_positive_yaw_limit():
    with pytest.raises(ValueError):
        LineFollowConfig(no_progress_yaw_deg=0.0)


def test_watch_needs_a_full_window_and_a_turn_is_progress():
    w = ProgressWatch()
    for i in range(101):                                                # 5 s pivot to 0.5 rad...
        t = i * 0.05
        w.note(t, "k", 0.0, 0.0, 0.2 * t, 0.0, 0.3, "tracking", 21.0)
        if t < 5.0:
            assert w.cause(t, 5.0, 0.059, 0.5236, 20.0, 0.30) is None    # less odom than the window
    assert w.cause(5.0, 5.0, 0.059, 0.5236, 20.0, 0.30) is None          # 1 rad turned: moving


def test_a_d468_owned_tick_still_opens_it():
    """D-468 owns the tick (8kcn space_or_floor_unconfirmed, 2026-10-10): D-407 is not stepped, yet the stuck opens."""
    m, events = _manager()
    t = 0.0
    while t < 6.0:
        stamp = round(t * 1e9)
        m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom", x=0.0, y=0.0, yaw=0.0,
                              received_at=t)
        m.note_issued(0.03 if t < 1.5 else 0.0, 0.0, t)                # one push, then D-468 holds
        t = round(t + 0.05, 6)
    with m._lock:
        m._local_owned_tick(6.0)
    assert [o["cause"] for o in events.named("nav.line_stuck_opened")] == ["no_progress"]
    assert m.status().stuck.cause == "no_progress"
