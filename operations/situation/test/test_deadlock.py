"""D-577 (d): deadlock / livelock / stall facts from Fleet's traffic table and robot states (synthetic snapshots)."""

from __future__ import annotations

import math

from rosy_situation.analyzers import Analyzer
from rosy_situation.deadlock import TrafficWatch


def _row(rid, x=0.0, y=0.0, *, online=True, age=0.1, linear=0.0):
    return {"robot_id": rid, "online": online, "state_age_s": age,
            "state": {"pose": {"x": x, "y": y, "yaw": 0.0},
                      "line_follow": {"mode": "OFF", "linear": linear, "angular": 0.0, "stuck": None}}}


def _trip(rid, front, end, waiting=(), state="running"):
    return {"robot_id": rid, "front_d_m": front, "authority_end_m": end, "waiting_for": list(waiting),
            "trip_state": state, "lap": None, "convoy": None}


def _unit(uid, holders, waiting=(), state="GRANTED", zone=None):
    return {"id": uid, "state": state, "holders": list(holders), "waiting": list(waiting), "zone": zone,
            "capacity": 1, "two_way": False}


def _snap(t, rows, trips=(), units=(), cycle=None, resolver=(), pending=()):
    return {"observed_at": float(t), "state": {"robots": list(rows)},
            "traffic": {"robots": list(trips), "units": list(units), "wait_cycle": cycle, "resolver": list(resolver)},
            "line_stuck": {"pending": list(pending), "answers": []}}


def _kinds(facts):
    return sorted((f["kind"], tuple(f["robot_ids"])) for f in facts)


def _deadlock(t, *, cycle=("a", "b"), xa=0.0, b_age=0.1, b_front=1.0):
    """a and b each hold the unit the other waits for, both at their authority end."""
    rows = [_row("a", x=xa), _row("b", x=5.0, age=b_age)]
    trips = [_trip("a", 1.0, 1.0, ["b"]), _trip("b", b_front, 1.0, ["a"])]
    units = [_unit("u1", ["a"], ["b"]), _unit("u2", ["b"], ["a"])]
    return _snap(t, rows, trips, units, list(cycle) if cycle else None)


def test_a_wait_cycle_of_still_robots_is_confirmed_after_three_snapshots():
    watch = TrafficWatch()
    assert watch(_deadlock(0)) == [] and watch(_deadlock(1)) == []
    facts = watch(_deadlock(2))
    assert _kinds(facts) == [("wait_cycle_confirmed", ("a", "b"))]
    assert facts[0]["value"]["fleet_agrees"] is True and facts[0]["confidence"] == 0.9


def test_a_cycle_fleet_does_not_report_is_flagged_as_a_disagreement():
    watch = TrafficWatch()
    for t in range(3):
        facts = watch(_deadlock(t, cycle=None))
    assert _kinds(facts) == [("wait_cycle_confirmed", ("a", "b"))]
    assert facts[0]["value"]["fleet_agrees"] is False and facts[0]["evidence"]["fleet_wait_cycle"] is None


def test_a_false_cycle_from_a_stale_pose_is_never_confirmed():
    watch = TrafficWatch()
    for t in range(5):
        facts = watch(_deadlock(t, b_age=4.0))
        assert _kinds(facts) == [("wait_cycle_stale_input", ("a", "b"))]
    assert facts[0]["value"]["stale"] == {"b": ["state_age"]}
    unplaced = TrafficWatch()(_deadlock(0, b_front=None))
    assert unplaced[0]["value"]["stale"] == {"b": ["not_placed"]}


def test_a_robot_the_table_holds_but_that_moves_is_reported_and_breaks_the_confirmation():
    watch = TrafficWatch()
    out = [watch(_deadlock(t, xa=0.05 * t)) for t in range(4)]
    assert out[0] == [] and out[1] == []
    assert _kinds(out[2]) == [("waiting_but_moving", ("a",))]
    assert out[2][0]["value"]["moved_m"] == 0.1 and out[2][0]["evidence"]["in_cycle"] is True


def test_a_cycle_that_keeps_reforming_is_a_livelock_but_a_one_snapshot_flicker_is_not():
    gone = {"traffic": {}}
    watch = TrafficWatch()
    facts = []
    for t in range(0, 40, 3):        # formed at 0, 3, 6, ...: gone for two snapshots each time
        facts = watch(_deadlock(t)) + watch(_deadlock(t + 1) | gone) + watch(_deadlock(t + 2) | gone)
        if t == 3:
            assert "livelock" not in [f["kind"] for f in facts]
    assert ("livelock", ("a", "b")) in _kinds(facts)
    flicker = TrafficWatch()
    for t in range(0, 40, 2):        # Fleet's cycle drops out for one snapshot: still one deadlock
        facts = flicker(_deadlock(t)) + flicker(_deadlock(t + 1) | gone)
        assert "livelock" not in [f["kind"] for f in facts], t


def test_a_trip_robot_moving_without_route_progress_is_a_livelock():
    watch = TrafficWatch()
    facts = []
    for t in range(22):              # odom wobbles 0.08 m, route front never moves
        facts = watch(_snap(t, [_row("a", x=0.08 * (t % 2))], [_trip("a", 1.0, 3.0)]))
        if t < 20:
            assert facts == [], t
    assert _kinds(facts) == [("livelock", ("a",))] and facts[0]["value"]["path_m"] >= 0.1


def test_a_trip_robot_with_authority_that_does_not_move_is_stalled_with_what_it_holds():
    watch = TrafficWatch()
    units = [_unit("ring_1", ["a"], ["b"], zone="ring_zone")]
    for t in range(21):
        facts = watch(_snap(t, [_row("a"), _row("b", x=3.0)], [_trip("a", 1.0, 2.0), _trip("b", 0.5, 0.5, ["a"])],
                            units))
        if t < 20:
            assert [f for f in facts if f["kind"] == "stalled"] == [], t
    stalled = [f for f in facts if f["kind"] == "stalled"]
    assert _kinds(stalled) == [("stalled", ("a",))]
    assert stalled[0]["value"]["zones"] == ["ring_zone"] and stalled[0]["value"]["waited_by"] == ["b"]
    # an open stuck is the resolver's, not a stall
    other = TrafficWatch()
    for t in range(25):
        facts = other(_snap(t, [_row("a")], [_trip("a", 1.0, 2.0)], pending=[{"robot_id": "a", "stuck_id": "s"}]))
    assert facts == []


def test_an_unknown_unit_held_past_30_s_is_reported():
    watch = TrafficWatch()
    unit = [_unit("u9", ["a"], state="UNKNOWN", zone="z")]
    assert watch(_snap(0, [_row("a")], units=unit)) == []
    assert watch(_snap(30, [_row("a")], units=unit)) == []
    facts = watch(_snap(31, [_row("a")], units=unit))
    assert _kinds(facts) == [("unknown_occupancy_long", ("a",))] and facts[0]["value"]["unit"] == "u9"


def _normal_hour():
    """Two robots on a repeat route for an hour; b waits 10 s at its authority end every 2 minutes."""
    for t in range(3600):
        a_front = 0.1 * t
        b_front = 0.1 * (t - 10 * (t // 120) - min(t % 120, 10))     # still while it waits
        if t % 120 < 10:
            b_wait, units = ["a"], [_unit("u_a", ["a"], ["b"])]
        else:
            b_wait, units = [], [_unit("u_a", ["a"])]
        rows = [_row("a", x=a_front, linear=0.1), _row("b", x=b_front, linear=0.0 if b_wait else 0.1)]
        trips = [_trip("a", a_front, a_front + 1.0), _trip("b", b_front, b_front if b_wait else b_front + 1.0, b_wait)]
        yield _snap(t, rows, trips, units)


def test_an_hour_of_normal_traffic_says_nothing_and_the_same_input_gives_the_same_facts():
    watch = TrafficWatch()
    assert [f for snap in _normal_hour() for f in watch(snap)] == []
    first, second = TrafficWatch(), TrafficWatch()
    run = [_deadlock(t, xa=0.05 * (t > 4) * t, b_age=4.0 if t > 8 else 0.1) for t in range(12)]
    assert [first(s) for s in run] == [second(s) for s in run]


def test_every_kind_passes_fleet_validation_and_carries_no_command_word():
    from fleet.stuck.ai_facts import AiFact

    watch, facts = TrafficWatch(), []
    for t in range(40):
        facts += watch(_deadlock(t, xa=0.05 * t if t > 30 else 0.0, b_age=4.0 if 10 < t < 13 else 0.1))
    facts += TrafficWatch()(_snap(0, [_row("a")], units=[_unit("u", ["a"], state="UNKNOWN")]))
    assert {"wait_cycle_confirmed", "wait_cycle_stale_input", "waiting_but_moving"} <= {f["kind"] for f in facts}
    for fact in facts:
        AiFact.model_validate(fact).check(fact["observed_at"])
        assert not math.isnan(fact["confidence"])


def test_a_fact_fleet_would_refuse_is_dropped_so_it_cannot_sink_the_batch():
    unit = [_unit("u9", ["a"], state="UNKNOWN", zone="STOP")]         # a zone named like a command word
    watch = TrafficWatch()
    watch(_snap(0, [_row("a")], units=unit))
    assert watch(_snap(31, [_row("a")], units=unit)) == []
    many = [f"r{i}" for i in range(17)]
    crowd = [_unit("u1", many, state="UNKNOWN")]
    watch = TrafficWatch()
    watch(_snap(0, [], units=crowd))
    assert watch(_snap(31, [], units=crowd)) == []


def test_the_service_analyzer_adds_traffic_facts_without_changing_proposals():
    analyzer = Analyzer()
    for t in range(3):
        facts = analyzer(_deadlock(t))
    assert ("wait_cycle_confirmed", ("a", "b")) in _kinds(facts)
    assert analyzer.proposals == []
