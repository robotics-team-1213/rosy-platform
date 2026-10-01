"""D-407: stuck recovery inside the CORE line-follow manager (one cmd_vel path, D-2)."""

import pytest

from core.bridge import traffic_gate
from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)
from core_features.line_follow.stuck_recovery import AnswerRefused
from core_features.traffic_policy import TrafficPolicyManager

GEOMETRY = dict(body_lidar_x_m=-0.017, body_rear_x_m=-0.076, body_rotation_radius_m=0.08257)
REAR_FROM_LIDAR = 0.059


class _Events:
    def __init__(self):
        self.events = []

    def publish(self, name, severity="info", source="", data=None):
        self.events.append((name, data or {}))

    def named(self, name):
        return [d for n, d in self.events if n == name]


def _manager(*, linked=False, calibrating=False, bind=True, **overrides):
    events = _Events()
    config = LineFollowConfig(**{"recovery_local_enabled": True, **GEOMETRY, **overrides})
    m = LineFollowManager(events, config=config, clock=lambda: 0.0)
    if bind:
        m.bind_recovery(console_linked=lambda: linked, calibration_active=lambda: calibrating,
                        linear_ceiling=lambda: 0.15, preview_seq=lambda: 42)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    return m, events


def _feed(m, t, *, front, rear=0.30, lane=True):
    """One scan + one camera frame at t. rear is measured from the body rear."""
    m.observe_clearance(front, received_at=t)
    m.observe_body_points([(front, 0.0), (-(rear + REAR_FROM_LIDAR), 0.0)], range_min=0.0,
                          received_at=t)
    if lane:
        m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                                  error=0.0, confidence=0.9), received_at=t, source_now=t)


def _run(m, start, stop, **feed):
    t, decision = start, None
    while t < stop - 1e-9:
        _feed(m, t, **feed)
        decision = m.tick(t + 0.01)
        t = round(t + 0.1, 6)
    return decision


def _blocked_until_stuck(m):
    _run(m, 0.0, 5.5, front=0.15)                  # obstacle_escalate_s = 5 s


def test_obstacle_escalation_opens_one_stuck_with_body_clearances():
    m, events = _manager(linked=True)
    _blocked_until_stuck(m)
    opened = events.named("nav.line_stuck_opened")
    assert len(opened) == 1
    assert opened[0]["cause"] == "obstacle_ahead" and opened[0]["preview_seq"] == 42
    assert opened[0]["rear_clearance_m"] == pytest.approx(0.30)
    assert opened[0]["front_clearance_m"] == pytest.approx(0.15)
    status = m.status()
    assert status.stuck.phase == "ASKING" and status.stuck.stuck_id == opened[0]["stuck_id"]
    assert len(events.named("nav.line_obstacle_hold")) == 1


def test_unbound_inputs_fail_closed_and_never_open_a_stuck():
    m, events = _manager(bind=False)
    _blocked_until_stuck(m)
    assert events.named("nav.line_stuck_opened") == [] and m.status().stuck is None


def test_calibration_session_blocks_recovery():
    m, events = _manager(calibrating=True)
    _blocked_until_stuck(m)
    assert events.named("nav.line_stuck_opened") == []


def test_no_console_backs_off_through_the_line_decision_then_resumes():
    m, events = _manager(linked=False)
    _blocked_until_stuck(m)
    _feed(m, 5.5, front=0.15)
    back = m.tick(5.51)
    assert back.linear == pytest.approx(-0.03) and back.angular == 0.0
    assert m.status().state == "RECOVERING" and m.status().reason == "stuck_back_off"
    assert back.mode is LineFollowMode.CAMERA_LINE           # same generation-checked path

    # The back-off goes out through the one CORE line -> CommandManager seam (D-2).
    class Command:
        twist = None

        def set_nav_twist(self, twist, now=None):
            self.twist = twist

        def clear_navigation(self):
            self.twist = None
    command = Command()
    assert traffic_gate.apply_line_candidate(m, TrafficPolicyManager(_Events()), command,
                                             back, 5.51)
    assert command.twist.linear == pytest.approx(-0.03)

    # Opened and started at the 5.01 tick: 0.08 m at 0.03 m/s ends at 7.68, then 1 s still,
    # then re-judge with the front clear.
    last = _run(m, 5.6, 7.6, front=0.15)
    assert last.linear == pytest.approx(-0.03)
    assert _run(m, 7.6, 8.6, front=0.50).linear == 0.0          # settling until 8.71
    assert m.status().stuck.phase == "SETTLING"
    _run(m, 8.6, 9.0, front=0.50)
    assert events.named("nav.line_stuck_closed")[-1]["reason"] == "recovered"
    assert _run(m, 9.0, 9.3, front=0.50).linear > 0.0
    assert m.status().stuck is None


def test_back_off_refused_when_rear_is_too_close():
    m, events = _manager(linked=False)
    _run(m, 0.0, 5.5, front=0.15, rear=0.05)
    assert all(m.tick(5.5).linear == 0.0 for _ in range(3))
    assert events.named("nav.line_stuck_local_result")[-1]["reason"] == "rear_blocked"


def test_rear_blind_zone_refuses_the_back_off():
    m, events = _manager(linked=False)
    t = 0.0
    while t < 5.5:
        m.observe_clearance(0.15, received_at=t)
        m.observe_body_points([(0.15, 0.0)], range_min=0.15, received_at=t)   # C1 range_min
        m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                                  error=0.0, confidence=0.9), received_at=t, source_now=t)
        m.tick(t + 0.01)
        t = round(t + 0.1, 6)
    assert events.named("nav.line_stuck_local_result")[-1]["reason"] == "rear_blind"


def test_console_resume_lets_the_robot_approach_down_to_stop_distance():
    m, events = _manager(linked=True)
    _blocked_until_stuck(m)
    _run(m, 5.5, 5.8, front=0.24)                 # between stop 0.20 and resume 0.28: held
    assert m.tick(5.81).linear == 0.0
    stuck_id = m.status().stuck.stuck_id
    assert m.stuck_decision(stuck_id, "RESUME", by="operator") == "resume"
    assert _run(m, 5.9, 6.2, front=0.24).linear > 0.0
    assert _run(m, 6.2, 6.5, front=0.19).linear == 0.0          # re-blocks inside stop distance
    assert m.status().reason == "obstacle_ahead"


def test_console_resume_refused_inside_stop_distance_and_late_answer_rejected():
    m, events = _manager(linked=True)
    _blocked_until_stuck(m)
    stuck_id = m.status().stuck.stuck_id
    with pytest.raises(AnswerRefused) as refused:
        m.stuck_decision(stuck_id, "RESUME", by="operator")
    assert refused.value.code == "STUCK_DECISION_REFUSED"
    with pytest.raises(AnswerRefused) as stale:
        m.stuck_decision("stuck-old", "WAIT", by="operator")
    assert stale.value.code == "STUCK_ID_MISMATCH"


def test_lane_lost_opens_a_stuck_and_resume_unlatches():
    m, events = _manager(linked=True)
    _run(m, 0.0, 0.5, front=1.0)
    _run(m, 0.5, 4.0, front=1.0, lane=False)
    assert m.status().state == "LOST"
    assert events.named("nav.line_stuck_opened")[-1]["cause"] == "lane_lost"
    m.stuck_decision(m.status().stuck.stuck_id, "RESUME", by="operator")
    assert _run(m, 4.0, 4.3, front=1.0).linear > 0.0


@pytest.mark.parametrize("stop", ["off", "hold_loss"])
def test_off_and_driver_hold_loss_win_over_backing(stop):
    m, events = _manager(linked=False)
    if stop == "hold_loss":
        m.set_mode(LineFollowMode.CAMERA_LINE, hold_s=2.0)
        for i in range(55):
            m.hold(now=i * 0.1)
    _blocked_until_stuck(m)
    _feed(m, 5.5, front=0.15)
    assert m.tick(5.51).linear < 0.0                             # backing
    if stop == "off":
        m.stop()                                                 # e-stop / IDLE / OFF all land here
        assert m.tick(5.6).linear == 0.0
        reason = "mode_off"
    else:
        assert m.tick(8.0).linear == 0.0                         # no hold() for 2 s
        reason = "driver_released"
    assert m.status().stuck is None
    assert events.named("nav.line_stuck_closed")[-1]["reason"] == reason


def test_manual_and_abort_answers_close_the_stuck():
    m, events = _manager(linked=True)
    _blocked_until_stuck(m)
    assert m.stuck_decision(m.status().stuck.stuck_id, "ABORT", by="operator") == "idle"
    assert m.status().stuck is None
