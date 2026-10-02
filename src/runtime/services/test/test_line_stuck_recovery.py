"""D-407 stuck recovery state machine (ROS-free): ask the console, else back off and re-judge."""
import dataclasses
import itertools
import math

import pytest

from core_features.line_follow.clearance import (body_clearances, self_mask_from_config,
                                                 self_mask_rear_blind_m)
from core_features.line_follow.model import LineFollowConfig
from core_features.line_follow.stuck_recovery import (ASKING, BACKING, SETTLING, WAITING_CONSOLE,
                                                      AnswerRefused, ForwardTrail, StuckInput,
                                                      StuckRecovery)


class Bus:
    def __init__(self):
        self.events = []

    def publish(self, name, severity="info", source="", data=None):
        self.events.append((name, data or {}))

    def named(self, name):
        return [data for event, data in self.events if event == name]


GEOMETRY = dict(body_lidar_x_m=-0.017, body_rear_x_m=-0.076, body_rotation_radius_m=0.08257)


def _machine(**overrides):
    counter = itertools.count(1)
    config = LineFollowConfig(**{"recovery_local_enabled": True, **GEOMETRY, **overrides})
    bus = Bus()
    return StuckRecovery(bus, config, new_id=lambda: f"stuck-{next(counter)}"), bus


def _inp(now, **kw):
    base = dict(now=now, cause="obstacle_ahead", scan_age_s=0.05, geometry_known=True,
                rear_m=0.30, rear_blind_m=0.0, console_linked=True, linear_ceiling=0.15,
                trail_age_s=1.0)
    base.update(kw)
    return StuckInput(**base)


# ---- opening -------------------------------------------------------------------------
def test_no_cause_passes_and_opens_nothing():
    machine, bus = _machine()
    assert machine.step(_inp(0.0, cause=None)).kind == "pass"
    assert machine.stuck_id is None and bus.events == []


def test_opens_once_per_stuck_with_unique_id_and_asks_console():
    machine, bus = _machine()
    assert machine.step(_inp(0.0, front_band_m=0.18, preview_seq=7)).kind == "hold"
    assert machine.step(_inp(1.0)).kind == "hold"
    opened = bus.named("nav.line_stuck_opened")
    assert len(opened) == 1 and opened[0]["stuck_id"] == "stuck-1"
    assert opened[0]["cause"] == "obstacle_ahead" and opened[0]["preview_seq"] == 7
    assert opened[0]["front_clearance_m"] == 0.18 and opened[0]["rear_clearance_m"] == 0.30
    asked = bus.named("nav.line_stuck_asked")
    assert asked[0]["local_fallback_s"] == 15.0 and machine.phase == ASKING
    machine.answer(2.0, "stuck-1", "RESUME", "operator")
    machine.step(_inp(10.0, cause="lane_lost"))
    assert machine.stuck_id == "stuck-2"


def test_never_opens_during_a_calibration_session():
    machine, bus = _machine()
    assert machine.step(_inp(0.0, calibration_active=True)).kind == "pass"
    assert machine.stuck_id is None


def test_stuck_closes_when_the_obstacle_clears_by_itself():
    machine, bus = _machine()
    machine.step(_inp(0.0))
    assert machine.step(_inp(2.0, cause=None)).kind == "pass"
    assert bus.named("nav.line_stuck_closed")[0]["reason"] == "cleared"


# ---- answers ------------------------------------------------------------------------
def test_answer_must_match_the_open_stuck_id():
    machine, bus = _machine()
    with pytest.raises(AnswerRefused) as none_open:
        machine.answer(0.0, "stuck-1", "WAIT", "operator")
    assert none_open.value.code == "STUCK_ID_MISMATCH"
    machine.step(_inp(0.0))
    machine.answer(1.0, "stuck-1", "ABORT", "operator")
    machine.step(_inp(5.0))                                  # a new stuck: stuck-2
    with pytest.raises(AnswerRefused) as late:
        machine.answer(6.0, "stuck-1", "RESUME", "operator")
    assert late.value.code == "STUCK_ID_MISMATCH" and machine.stuck_id == "stuck-2"
    rejected = [a for a in bus.named("nav.line_stuck_answered") if not a["accepted"]]
    assert [a["reason"] for a in rejected] == ["stuck_id_mismatch", "stuck_id_mismatch"]


def test_wait_holds_and_never_falls_back_to_local():
    machine, bus = _machine()
    machine.step(_inp(0.0))
    assert machine.answer(1.0, "stuck-1", "WAIT", "operator") == "hold"
    assert machine.step(_inp(100.0)).kind == "hold"
    assert machine.phase == WAITING_CONSOLE and bus.named("nav.line_stuck_local_attempt") == []


def test_resume_refused_with_an_object_inside_stop_distance():
    machine, bus = _machine()
    machine.step(_inp(0.0, front_band_m=0.15))
    with pytest.raises(AnswerRefused) as refused:
        machine.answer(1.0, "stuck-1", "RESUME", "operator")
    assert refused.value.code == "STUCK_DECISION_REFUSED" and machine.stuck_id == "stuck-1"
    machine.step(_inp(2.0, front_band_m=0.22))               # between stop and resume: allowed
    assert machine.answer(3.0, "stuck-1", "RESUME", "operator") == "resume"
    assert machine.stuck_id is None
    assert bus.named("nav.line_stuck_closed")[0]["reason"] == "console_resume"


def test_resume_refused_on_a_stale_scan():
    machine, _ = _machine()
    machine.step(_inp(0.0, scan_age_s=2.0))
    with pytest.raises(AnswerRefused):
        machine.answer(1.0, "stuck-1", "RESUME", "operator")


@pytest.mark.parametrize("decision, outcome", [("MANUAL", "manual"), ("ABORT", "idle")])
def test_manual_and_abort_close_the_stuck(decision, outcome):
    machine, bus = _machine()
    machine.step(_inp(0.0))
    assert machine.answer(1.0, "stuck-1", decision, "operator") == outcome
    assert machine.stuck_id is None


def test_back_and_retry_runs_the_back_off_now():
    machine, bus = _machine()
    machine.step(_inp(0.0))
    assert machine.answer(1.0, "stuck-1", "BACK_AND_RETRY", "operator") == "back"
    action = machine.step(_inp(1.05))
    assert action.kind == "back" and action.linear == pytest.approx(-0.03)
    assert bus.named("nav.line_stuck_local_attempt")[0]["trigger"] == "console"


def test_back_and_retry_refused_when_local_recovery_is_off():
    machine, _ = _machine(recovery_local_enabled=False)
    machine.step(_inp(0.0))
    with pytest.raises(AnswerRefused):
        machine.answer(1.0, "stuck-1", "BACK_AND_RETRY", "operator")


# ---- timeout and local recovery ----------------------------------------------------
def test_no_answer_within_ask_s_starts_the_back_off():
    machine, bus = _machine()
    machine.step(_inp(0.0))
    assert machine.step(_inp(14.9)).kind == "hold"
    action = machine.step(_inp(15.0))
    assert action.kind == "back" and machine.phase == BACKING
    assert bus.named("nav.line_stuck_local_attempt")[0]["trigger"] == "ask_timeout"


def test_no_console_link_backs_off_without_waiting():
    machine, bus = _machine()
    assert machine.step(_inp(0.0, console_linked=False)).kind == "back"
    assert bus.named("nav.line_stuck_local_attempt")[0]["trigger"] == "no_console"


def test_local_recovery_disabled_by_default_waits_for_the_console():
    machine, bus = _machine(recovery_local_enabled=False)
    assert LineFollowConfig().recovery_local_enabled is False
    machine.step(_inp(0.0, console_linked=False))
    assert machine.step(_inp(30.0)).kind == "hold" and machine.phase == WAITING_CONSOLE
    assert bus.named("nav.line_stuck_asked")[-1]["reason"] == "local_disabled"


def test_back_off_distance_speed_and_settle_then_resume():
    machine, bus = _machine()
    machine.step(_inp(0.0, console_linked=False))             # starts at t=0
    # speed = min(manual 0.15, 0.03) = 0.03 m/s, 0.08 m -> 2.667 s
    assert machine.step(_inp(2.6)).linear == pytest.approx(-0.03)
    assert machine.step(_inp(2.7)).kind == "hold" and machine.phase == SETTLING
    assert machine.step(_inp(3.6, lane_visible=True)).kind == "hold"    # 1 s still
    assert machine.step(_inp(3.7, lane_visible=True, front_clear=True)).kind == "resume"
    assert bus.named("nav.line_stuck_local_result")[-1]["result"] == "recovered"
    assert bus.named("nav.line_stuck_closed")[-1]["reason"] == "recovered"


def test_back_off_speed_follows_a_lower_manual_limit():
    machine, _ = _machine()
    assert machine.step(_inp(0.0, console_linked=False, linear_ceiling=0.02)).linear == \
        pytest.approx(-0.02)


@pytest.mark.parametrize("kw, why", [
    (dict(rear_m=0.05), "rear_blocked"),
    (dict(rear_m=0.06), "rear_blocked"),
    (dict(scan_age_s=0.6), "scan_stale"),
    (dict(scan_age_s=None), "no_scan"),
    (dict(geometry_known=False), "body_geometry_unset"),
    (dict(rear_blind_m=0.09), "rear_blind"),
    (dict(linear_ceiling=0.0), "linear_limit_zero"),
])
def test_back_off_refused_before_start(kw, why):
    machine, bus = _machine()
    assert machine.step(_inp(0.0, console_linked=False, **kw)).kind == "hold"
    result = bus.named("nav.line_stuck_local_result")[-1]
    assert {k: result[k] for k in ("stuck_id", "attempt", "result", "reason")} == {
        "stuck_id": "stuck-1", "attempt": 0, "result": "refused", "reason": why}
    # The refusal carries the scan it was judged on (Gazebo 2026-10-02 diagnosis).
    expected = _inp(0.0, console_linked=False, **kw)
    assert (result["rear_clearance_m"], result["rear_blind_m"], result["trail_m"],
            result["trail_yaw_deg"]) == (expected.rear_m, expected.rear_blind_m,
                                         expected.trail_m, expected.trail_yaw_deg)
    assert machine.phase == WAITING_CONSOLE


@pytest.mark.parametrize("kw, why", [(dict(rear_m=0.05), "rear_blocked"),
                                     (dict(scan_age_s=0.8), "scan_stale")])
def test_back_off_stops_immediately_when_rear_closes_or_scan_goes_stale(kw, why):
    machine, bus = _machine()
    machine.step(_inp(0.0, console_linked=False))
    assert machine.step(_inp(1.0, **kw)).kind == "hold"
    assert bus.named("nav.line_stuck_local_result")[-1]["result"] == "aborted"
    assert bus.named("nav.line_stuck_local_result")[-1]["reason"] == why
    assert machine.step(_inp(1.1)).kind == "hold"             # no restart on its own


def test_max_attempts_then_console_only_without_another_timeout():
    machine, bus = _machine()
    t = 0.0
    machine.step(_inp(t, console_linked=False))
    for _ in range(2):
        t += 2.7
        machine.step(_inp(t))                                 # -> SETTLING
        t += 1.0
        machine.step(_inp(t, lane_visible=False))            # re-judge fails
    assert len(bus.named("nav.line_stuck_local_attempt")) == 2
    assert machine.phase == WAITING_CONSOLE
    assert bus.named("nav.line_stuck_asked")[-1]["local_fallback_s"] is None
    assert machine.step(_inp(t + 60.0)).kind == "hold"
    with pytest.raises(AnswerRefused):
        machine.answer(t + 61.0, "stuck-1", "BACK_AND_RETRY", "operator")


def test_reset_closes_and_wins_over_backing():
    machine, bus = _machine()
    machine.step(_inp(0.0, console_linked=False))
    machine.reset("estop", 0.5)
    assert machine.stuck_id is None
    assert bus.named("nav.line_stuck_closed")[-1]["reason"] == "estop"
    assert machine.step(_inp(0.6, cause=None)).kind == "pass"


def test_status_reports_phase_and_remaining_ask_time():
    machine, _ = _machine()
    assert machine.status(0.0) is None
    machine.step(_inp(0.0))
    status = machine.status(5.0)
    assert status["phase"] == ASKING and status["ask_remaining_s"] == 10.0
    assert status["stuck_id"] == "stuck-1" and status["max_attempts"] == 2


# ---- config + geometry ----------------------------------------------------------------
def test_recovery_config_bounds():
    with pytest.raises(ValueError):
        LineFollowConfig(recovery_back_m=0.5)
    with pytest.raises(ValueError):
        LineFollowConfig(recovery_max_attempts=True)
    with pytest.raises(ValueError):
        LineFollowConfig(body_rear_x_m=0.05)
    assert LineFollowConfig(**GEOMETRY).body_geometry_known
    assert not LineFollowConfig().body_geometry_known
    assert dataclasses.replace(LineFollowConfig(), recovery_ask_s=3.0).recovery_ask_s == 3.0


def test_body_clearances_measure_from_the_urdf_body_rear():
    # LiDAR at x=-0.017, body rear at x=-0.076: a return 0.20 m behind the LiDAR is
    # 0.20 - 0.059 = 0.141 m behind the body rear.
    points = [(-0.20, 0.0), (0.25, 0.01), (0.0, 0.30), (-0.20, 0.5)]
    got = body_clearances(points, lidar_x_m=-0.017, rear_x_m=-0.076, half_width_m=0.09,
                          rotation_radius_m=0.08257)
    assert got["rear_m"] == pytest.approx(0.141)
    assert got["front_band_m"] == pytest.approx(0.25)
    assert got["turn_m"] == pytest.approx(0.217 - 0.08257)      # nearest to base_footprint
    empty = body_clearances([], lidar_x_m=-0.017, rear_x_m=-0.076, half_width_m=0.09)
    assert empty == {"front_band_m": None, "rear_m": None, "turn_m": None}


# ---- rear blind band: user decision 2026-10-02, review M1/M2/L4 -------------------------
@pytest.mark.parametrize("trail_m, yaw, ok", [
    (0.10, 2.0, True),         # drove 0.10 m forward, nearly straight: may back 0.08 m
    (0.08, 0.0, True),
    (0.05, 0.0, False),        # never back further than it came
    (0.10, 20.0, False),       # turned in place: the blind band is not where it came from
    (None, None, False),       # no / stale history
])
def test_blind_band_only_over_the_trail_just_driven(trail_m, yaw, ok):
    machine, bus = _machine()
    action = machine.step(_inp(0.0, console_linked=False, rear_blind_m=0.09,
                               trail_m=trail_m, trail_yaw_deg=yaw))
    assert (action.kind == "back") is ok
    if not ok:
        assert bus.named("nav.line_stuck_local_result")[-1]["reason"] == "rear_blind"


def test_blind_band_trail_still_needs_visible_rear_clearance():
    machine, bus = _machine()
    machine.step(_inp(0.0, console_linked=False, rear_blind_m=0.09, trail_m=0.2,
                      trail_yaw_deg=0.0, rear_m=0.05))
    assert bus.named("nav.line_stuck_local_result")[-1]["reason"] == "rear_blocked"


def test_trail_is_checked_at_start_not_as_it_is_used_up():
    machine, bus = _machine()
    assert machine.step(_inp(0.0, console_linked=False, rear_blind_m=0.09, trail_m=0.10,
                             trail_yaw_deg=0.0)).kind == "back"
    assert machine.step(_inp(1.0, rear_blind_m=0.09, trail_m=0.07, trail_yaw_deg=0.0)).kind == "back"
    assert machine.step(_inp(1.1, rear_blind_m=0.09, rear_m=0.05)).kind == "hold"   # live check


def test_unknown_range_min_refuses_the_back_off():
    machine, bus = _machine()
    machine.step(_inp(0.0, console_linked=False, rear_blind_m=None))
    assert bus.named("nav.line_stuck_local_result")[-1]["reason"] == "rear_blind"


def test_resume_without_any_scan_is_refused_when_a_lidar_stop_is_in_use():
    machine, _ = _machine()
    machine.step(_inp(0.0, scan_age_s=None, lidar_expected=True, cause="lane_lost"))
    with pytest.raises(AnswerRefused):
        machine.answer(1.0, "stuck-1", "RESUME", "operator")
    bench, _ = _machine()                                    # no LiDAR at all, lane lost
    bench.step(_inp(0.0, scan_age_s=None, lidar_expected=False, cause="lane_lost"))
    assert bench.answer(1.0, "stuck-1", "RESUME", "operator") == "resume"
    blocked, _ = _machine()                                  # an obstacle stuck needs a scan
    blocked.step(_inp(0.0, scan_age_s=None))
    with pytest.raises(AnswerRefused):
        blocked.answer(1.0, "stuck-1", "RESUME", "operator")


def test_forward_trail_integrates_issued_twists():
    trail = ForwardTrail()
    t = 0.0
    for _ in range(60):                       # 3 s forward at 0.05 m/s, 20 Hz
        trail.record(t, 0.05, 0.0)
        t = round(t + 0.05, 6)
    for _ in range(200):                      # then 10 s held at zero
        trail.record(t, 0.0, 0.0)
        t = round(t + 0.05, 6)
    net, yaw = trail.measure(t, 5.0)
    assert net == pytest.approx(0.15, abs=1e-6) and yaw == 0.0
    trail.record(t, -0.03, 0.0)               # a back-off spends the trail
    t2 = t + 0.25
    trail.record(t2, 0.0, 0.0)
    assert trail.measure(t2, 5.0)[0] == pytest.approx(0.15 - 0.0075, abs=1e-6)
    assert trail.measure(t2 + 2.0, 5.0) == (None, None)     # history stale


def test_forward_trail_window_and_rotation():
    trail = ForwardTrail()
    t = 0.0
    for _ in range(200):                      # 10 s at 0.02 m/s: only the last 5 s count
        trail.record(t, 0.02, 0.0)
        t = round(t + 0.05, 6)
    assert trail.measure(t, 5.0)[0] == pytest.approx(0.02 * 5.05, abs=1e-3)
    spin = ForwardTrail()
    spin.record(0.0, 0.05, 0.0)
    spin.record(0.05, 0.0, 0.5)               # rotation in place
    spin.record(0.30, 0.0, 0.0)
    assert spin.measure(0.30, 5.0)[1] == pytest.approx(math.degrees(0.5 * 0.25))
    assert ForwardTrail().measure(0.0, 5.0) == (None, None)


def test_self_mask_window_reaching_the_rear_band_is_blind():
    rear = self_mask_from_config([{"from_deg": 170, "to_deg": 180, "max_range_m": 0.2}])
    side = self_mask_from_config([{"from_deg": -66, "to_deg": -52, "max_range_m": 0.17}])
    kw = dict(lidar_x_m=-0.017, rear_x_m=-0.076, half_width_m=0.09)
    assert self_mask_rear_blind_m(rear, **kw) == pytest.approx(0.2 - 0.059, abs=1e-3)
    assert self_mask_rear_blind_m(side, **kw) == 0.0
    assert self_mask_rear_blind_m((), **kw) == 0.0


# ---- re-stuck after recovery: clarification 2026-10-02 --------------------------------
def _recover(machine, t, **kw):
    """Open (no console) -> back off -> settle -> recovered. Returns the time after."""
    machine.step(_inp(t, console_linked=False, **kw))
    t += 2.7
    machine.step(_inp(t, **kw))                                   # -> SETTLING
    t += 1.0
    machine.step(_inp(t, lane_visible=True, front_clear=True, **kw))
    return t


def test_rapid_re_stucks_carry_attempts_then_wait_for_the_console():
    machine, bus = _machine()
    t = _recover(machine, 0.0)
    assert bus.named("nav.line_stuck_closed")[-1]["reason"] == "recovered"
    t = _recover(machine, t + 1.0, moved_since_recovery_m=0.05)
    second = bus.named("nav.line_stuck_opened")[-1]
    assert second["restuck_of"] == "stuck-1" and second["attempts"] == 1
    assert len(bus.named("nav.line_stuck_local_attempt")) == 2
    machine.step(_inp(t + 1.0, console_linked=False, moved_since_recovery_m=0.05))
    third = bus.named("nav.line_stuck_opened")[-1]
    assert third["restuck_of"] == "stuck-2" and third["attempts"] == 2
    assert machine.phase == WAITING_CONSOLE
    assert bus.named("nav.line_stuck_asked")[-1]["reason"] == "attempts_exhausted"
    assert machine.step(_inp(t + 60.0, moved_since_recovery_m=0.05)).kind == "hold"
    assert len(bus.named("nav.line_stuck_local_attempt")) == 2       # no third back-off


@pytest.mark.parametrize("after_s, moved, carried", [
    (5.0, 1.0, True),       # inside recovery_restuck_s, even after driving on
    (30.0, 0.10, True),     # later, but has not driven recovery_restuck_m yet
    (30.0, None, True),     # unknown travel: same stuck (conservative)
    (30.0, 0.50, False),    # later and drove on: a new stuck
])
def test_restuck_window_is_time_or_distance(after_s, moved, carried):
    machine, bus = _machine()
    t = _recover(machine, 0.0)
    machine.step(_inp(t + after_s, console_linked=True, moved_since_recovery_m=moved))
    opened = bus.named("nav.line_stuck_opened")[-1]
    assert (opened["restuck_of"] == "stuck-1") is carried
    assert opened["attempts"] == (1 if carried else 0)


def test_mode_reset_forgets_the_recovered_stuck():
    machine, bus = _machine()
    t = _recover(machine, 0.0)
    machine.reset("mode_off", t)
    machine.step(_inp(t + 1.0, moved_since_recovery_m=0.0))
    assert bus.named("nav.line_stuck_opened")[-1]["restuck_of"] is None


def test_forward_trail_net_since():
    trail = ForwardTrail()
    for i in range(20):
        trail.record(i * 0.05, 0.05, 0.0)
    assert trail.net_since(0.5, 1.0) == pytest.approx(0.05 * 0.5, abs=1e-6)


# ---- trail max age: decision 2026-10-02 ----------------------------------------------
@pytest.mark.parametrize("age, ok", [(29.0, True), (30.0, True), (31.0, False), (None, False)])
def test_trail_only_counts_while_its_last_forward_command_is_recent(age, ok):
    machine, bus = _machine()
    action = machine.step(_inp(0.0, console_linked=False, rear_blind_m=0.09, trail_m=0.10,
                               trail_yaw_deg=0.0, trail_age_s=age))
    assert (action.kind == "back") is ok
    if ok:
        assert bus.named("nav.line_stuck_local_attempt")[-1]["trail_age_s"] == age
    else:
        refused = bus.named("nav.line_stuck_local_result")[-1]
        assert refused["reason"] == "rear_blind" and refused["trail_age_s"] == age


def test_trail_age_is_not_rechecked_while_backing():
    machine, _ = _machine()
    machine.step(_inp(0.0, console_linked=False, rear_blind_m=0.09, trail_m=0.10,
                      trail_yaw_deg=0.0, trail_age_s=29.5))
    assert machine.step(_inp(1.0, rear_blind_m=0.09, trail_m=0.07, trail_yaw_deg=0.0,
                             trail_age_s=30.5)).kind == "back"


def test_forward_trail_last_forward_at():
    trail = ForwardTrail()
    assert trail.last_forward_at() is None
    trail.record(1.0, 0.05, 0.0)
    trail.record(1.05, 0.0, 0.0)
    trail.record(1.10, -0.03, 0.0)
    assert trail.last_forward_at() == 1.0


# ---- D-407 console re-run 2026-10-02: event fields ---------------------------------------
@pytest.mark.parametrize("state", ["clear", "blocked", "unknown"])
def test_opened_event_says_whether_the_rear_is_clear_or_unknown(state):
    machine, bus = _machine()
    machine.step(_inp(0.0, rear_m=None, rear_state=state))
    opened = bus.named("nav.line_stuck_opened")[-1]
    assert opened["rear_clearance_m"] is None and opened["rear_state"] == state


def test_refused_back_and_retry_answer_carries_the_judged_scan():
    machine, bus = _machine()
    machine.step(_inp(0.0, rear_blind_m=0.09, trail_m=0.15, trail_yaw_deg=14.6,
                      trail_age_s=20.1))
    with pytest.raises(AnswerRefused):
        machine.answer(1.0, "stuck-1", "BACK_AND_RETRY", "operator", "a1b2c3d4e5f6")
    answered = bus.named("nav.line_stuck_answered")[-1]
    assert answered["accepted"] is False and answered["reason"] == "rear_blind"
    assert (answered["trail_m"], answered["trail_yaw_deg"], answered["trail_age_s"],
            answered["rear_blind_m"]) == (0.15, 14.6, 20.1, 0.09)
    assert answered["principal_ref"] == "a1b2c3d4e5f6" and "token_id" not in answered
