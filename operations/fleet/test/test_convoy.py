"""D-517 9 M3: lane convoy (leader + followers) on the block table — moving block behind the member
ahead, fixed blocks when it is unknown, never an overlap, an overtake or a smaller end."""

import math
import random

import pytest

from fleet.traffic.blocks import Robot, Span, TableState, follow, loop_capacity, step
from fleet.traffic.lane_traffic import _shift

from test_blocks import _loop, _spans

STOP = 0.12  # d_stop(v) the follower keeps behind the member's rear


def _ahead(robots, robot_id):
    return {r.id: r for r in robots}[robot_id]


def _convoy_run(n_followers, others, *, ticks, seed, u=0.05, body=0.12, unknown_rate=0.0, stall_rate=0.0,
                leader_ends_at=None, blocks=40, length=0.65, trim_rate=0.0):
    """Every robot drives the same cycle (one route, metres along it). Estimates are true ± u; CORE
    drives to its last authority measured from the estimate it came with (odom-anchored, D-517 4) and
    keeps driving to it while it gets none (no expiry: the worst case). ``trim_rate``: each tick a robot
    whose padded rear is past its first lap may drop that lap (``lane_traffic._shift``, its own route
    metres move by a lap) at random, so trims land while units are shared and members go UNKNOWN."""
    layout, cycle = _loop(blocks, length, zone_at=(blocks // 3, 2))
    lap = sum(size for _unit, size in cycle)
    spans = _spans(cycle, 0, laps=ticks // 5 + 4)
    rng = random.Random(seed)
    spacing = length  # the convoy starts one block apart, the others spread over the rest of the loop
    convoy = [Robot("lead", spans, None, 0.3, u, body)] + [
        Robot(f"f{i}", spans, None, 0.3, u, body, convoy="lead") for i in range(1, n_followers + 1)]
    true_d = {r.id: (n_followers + 1) * spacing - i * spacing for i, r in enumerate(convoy)}
    plain = [Robot(f"x{i}", spans, None, 0.3, u, body) for i in range(others)]
    free = lap - (n_followers + 2) * spacing
    for i, r in enumerate(plain):
        true_d[r.id] = true_d["lead"] + spacing + (i + 1) * free / (others + 1)
    robots = convoy + plain
    assert len(robots) <= loop_capacity(_spans(cycle, 0, 1), layout, 3)
    state, last_auth, prev = TableState(), {}, {}
    shrinks, conflicts, gaps, followed = [], [], [], 0
    progress = {r.id: 0.0 for r in robots}
    order = [r.id for r in convoy]
    per_lap, laps_off = len(cycle), {r.id: 0 for r in robots}
    for tick in range(ticks):
        live = robots if leader_ends_at is None or tick < leader_ends_at else robots[1:]
        for r in live:
            own = true_d[r.id] - laps_off[r.id] * lap
            if trim_rate and rng.random() < trim_rate and own - body - 2 * u > lap:
                _shift(state, r.id, r.spans, lap)
                r.spans = tuple(Span(s.unit, s.d0 - lap, s.d1 - lap) for s in r.spans[per_lap:])
                laps_off[r.id] += 1
                if r.id in prev:
                    prev[r.id] -= lap
        for r in robots:
            r.lookahead_m = rng.choice((0.1, 0.3, 0.6))
            r.d = None if tick and rng.random() < unknown_rate else (
                true_d[r.id] - laps_off[r.id] * lap + rng.uniform(-u, u))
        members = [r for r in convoy if r in live]
        for r in convoy[1:]:
            follow(r, members, lambda m, after, r=r: (
                m.d + (laps_off[m.id] - laps_off[r.id]) * lap if m.d + (laps_off[m.id] - laps_off[r.id]) * lap > after
                else None), STOP)
            followed += r.follows is not None
        result = step(layout, live, state, now=tick * 0.5)
        conflicts.extend(result.conflicts)
        for r in live:
            if r.id in result.authority_end:
                if result.authority_end[r.id] < prev.get(r.id, -math.inf) - 1e-9:
                    shrinks.append((tick, r.id))
                prev[r.id] = result.authority_end[r.id]
                last_auth[r.id] = (result.authority_end[r.id], r.d, true_d[r.id])
        for r in live:
            if r.id not in last_auth or rng.random() < stall_rate:
                continue
            authority, est, true_then = last_auth[r.id]
            move = min(rng.uniform(0.0, 0.1), max(0.0, true_then + (authority - est) - true_d[r.id]))
            true_d[r.id] += move
            progress[r.id] += move
        # truth: no two real bodies overlap anywhere on the cycle
        fronts = sorted((true_d[r.id] % lap, r.id) for r in robots)
        for (a, ra), (b, rb) in zip(fronts, fronts[1:] + [(fronts[0][0] + lap, fronts[0][1])]):
            assert b - body >= a - 1e-9, f"tick {tick}: {ra} and {rb} overlap"
        # no overtaking in the convoy, and each follower stays d_stop behind the member ahead of it
        assert sorted(order, key=lambda rid: -true_d[rid]) == order, f"tick {tick}: overtaken"
        for ahead, behind in zip(order, order[1:]):
            gaps.append(true_d[ahead] - body - true_d[behind])
    return {"conflicts": conflicts, "shrinks": shrinks, "min_gap": min(gaps), "progress": progress,
            "followed": followed}


@pytest.mark.parametrize("n_followers,others,seed", [(1, 2, 1), (2, 3, 2), (3, 3, 3), (4, 3, 4)])
def test_a_convoy_among_other_robots_never_overlaps_overtakes_or_shrinks(n_followers, others, seed):
    run = _convoy_run(n_followers, others, ticks=600, seed=seed)
    assert run["conflicts"] == [] and run["shrinks"] == []
    assert run["min_gap"] >= STOP - 1e-9
    assert run["followed"] > 0.9 * 600 * n_followers, "the moving block hardly ran"
    assert min(run["progress"].values()) > 2 * 0.65


@pytest.mark.parametrize("seed", [5, 6, 7])
def test_unknown_poses_and_stalls_fall_back_to_fixed_blocks_without_overlap(seed):
    run = _convoy_run(3, 3, ticks=800, seed=seed, unknown_rate=0.2, stall_rate=0.2)
    assert run["conflicts"] == [] and run["shrinks"] == []
    assert run["min_gap"] >= STOP - 1e-9
    assert min(run["progress"].values()) > 0.65


@pytest.mark.parametrize("seed", [10, 11, 12])
def test_lap_trims_while_a_unit_is_shared_and_members_go_unknown(seed):
    """Safety-Review CRITICAL: a lap trim keeps the shared marks on the same units; random trims, UNKNOWN
    poses and a leader that ends."""
    run = _convoy_run(3, 2, ticks=800, seed=seed, unknown_rate=0.15, trim_rate=0.05, leader_ends_at=500)
    assert run["conflicts"] == [] and run["shrinks"] == []
    assert run["min_gap"] >= 0.0


def test_a_lap_trim_keeps_the_shared_unit_and_an_unknown_member_stops_the_follower_before_it():
    """Safety-Review CRITICAL: ``_shift`` re-indexed held but not shared; after a trim the follower
    passed the unit it shared with a member that went UNKNOWN."""
    layout, cycle = _loop(10, 0.65)
    spans, lap, u = _spans(cycle, 0, 3), 6.5, 0.05
    lead = Robot("lead", spans, lap + 1.0, 0.3, u, 0.12)
    tail = Robot("f", spans, lap + 0.62, 0.3, u, 0.12, convoy="lead")
    state = TableState()
    front = lambda m, after: m.d if m.d > after else None  # noqa: E731
    step(layout, [lead], state, now=0.0)
    follow(tail, [lead], front, STOP)
    step(layout, [lead, tail], state, now=0.5)
    assert state.shared["f"] == {11: "lead"}  # b1 of the second lap, shared with the leader
    _shift(state, "f", tail.spans, lap)  # the follower drops its first lap; the leader has not yet
    tail.spans = tuple(Span(s.unit, s.d0 - lap, s.d1 - lap) for s in spans[10:])
    tail.d -= lap
    assert state.shared["f"] == {1: "lead"} and state.held["f"][1] == ("b1", True)
    lead.d = None
    follow(tail, [lead], lambda m, after: None, STOP)
    result = step(layout, [lead, tail], state, now=1.0)
    assert result.authority_end.get("f", -math.inf) <= 0.65 - u + 1e-9 and result.waiting_for["f"] == ("lead",)
    assert state.authority["f"] == pytest.approx(1.0 - 0.12 - (STOP + 2 * u + u))  # the earlier end, shifted


def test_a_recovering_member_is_not_followed_and_the_follower_stops_before_its_unit():
    """Safety-Review MAJOR: a member that may reverse (D-407 stuck, D-468 retrace) gives no moving block."""
    layout, cycle = _loop(10, 0.65)
    spans = _spans(cycle, 0, 3)
    lead = Robot("lead", spans, 1.4, 0.3, 0.05, 0.12, recovering=True)
    tail = Robot("f", spans, 0.4, 0.3, 0.05, 0.12, convoy="lead")
    state = TableState()
    step(layout, [lead], state, now=0.0)
    assert follow(tail, [lead], lambda m, after: m.d if m.d > after else None, STOP) is None
    assert tail.follows is None and tail.follow_end == math.inf
    result = step(layout, [lead, tail], state, now=0.5)
    assert result.authority_end["f"] <= 0.65 - 0.05 + 1e-9 and "f" not in state.shared


def test_a_zone_at_capacity_takes_no_follower_beside_its_member():
    """Safety-Review MINOR: in a zone of capacity c a follower and its member count as two, never c + 1."""
    layout, cycle = _loop(10, 0.65, zone_at=(1, 2), zone_cap=2)  # zone [0.65, 1.95), capacity 2
    spans = _spans(cycle, 0, 3)
    lead = Robot("lead", spans, 1.5, 0.3, 0.05, 0.12)
    other = Robot("x", spans, 1.9, 0.3, 0.05, 0.12)
    tail = Robot("f", spans, 0.6, 0.6, 0.05, 0.12, convoy="lead")
    state = TableState()
    step(layout, [lead, other], state, now=0.0)
    follow(tail, [lead], lambda m, after: m.d if m.d > after else None, STOP)
    result = step(layout, [lead, other, tail], state, now=0.5)
    assert 1 not in state.held["f"] and not state.shared.get("f") and result.conflicts == ()
    assert result.authority_end["f"] <= 0.65 - 0.05 + 1e-9 and set(result.waiting_for["f"]) == {"lead", "x"}


def test_two_followers_that_read_each_other_ahead_do_not_both_stand(monkeypatch):
    """Safety-Review MAJOR (liveness): nose to tail within the noise threshold each follower reads the
    other ahead; the earlier-started one drops the later one and moves."""
    from types import SimpleNamespace

    import fleet.traffic.lane_traffic as lane_traffic
    monkeypatch.setattr(lane_traffic, "_front_on", lambda graph, live, other, d, after, body: d if d > after else None)
    layout, cycle = _loop(10, 0.65)
    spans = _spans(cycle, 0, 3)
    f1 = Robot("f1", spans, 2.0, 0.3, 0.05, 0.12, convoy="lead")
    f2 = Robot("f2", spans, 2.0 - 0.12 + 0.01, 0.3, 0.05, 0.12, convoy="lead")  # leader not localized
    trips = {rid: SimpleNamespace(view={"created_at": t, "caps": {"max_speed": 0.2}})
             for rid, t in (("lead", 0.0), ("f1", 1.0), ("f2", 2.0))}
    service = lane_traffic.TrafficService(None)
    state = TableState()
    for tick in range(3):
        for r in (f2, f1):  # either order of the robot list
            service._link(None, [r, f1 if r is f2 else f2], trips)
            assert (f1.follows, f2.follows) == (None, "f1")
        result = step(layout, [f1, f2], state, now=tick * 0.5)
        assert result.authority_end["f1"] > f1.d and result.conflicts == ()


def test_the_demo_uncertainty_keeps_the_gap():
    run = _convoy_run(2, 1, ticks=600, seed=8, u=0.195, unknown_rate=0.1, blocks=24)
    assert run["conflicts"] == [] and run["shrinks"] == [] and run["min_gap"] >= STOP - 1e-9


def test_a_leader_whose_trip_ends_leaves_followers_on_fixed_blocks():
    """Leader canceled: it stands where it is (its units stay blocked) and the convoy dissolves."""
    run = _convoy_run(2, 2, ticks=400, seed=9, leader_ends_at=100)
    assert run["conflicts"] == [] and run["shrinks"] == []
    assert run["min_gap"] >= 0.0


def test_a_follower_shares_only_the_unit_of_the_member_it_follows():
    layout, cycle = _loop(10, 0.65)
    spans = _spans(cycle, 0, 3)
    lead = Robot("lead", spans, 1.0, 0.3, 0.05, 0.12)
    other = Robot("x", spans, 1.0, 0.3, 0.05, 0.12)
    tail = Robot("f", spans, 0.62, 0.3, 0.05, 0.12, convoy="lead")
    for ahead in (lead, other):  # ahead in b1 [0.65, 1.3), the follower's front in b0
        state = TableState()
        step(layout, [ahead], state, now=0.0)
        follow(tail, [ahead] if ahead is lead else [], lambda m, after: m.d if m.d > after else None, STOP)
        result = step(layout, [ahead, tail], state, now=0.5)
        if ahead is lead:
            assert result.authority_end["f"] == pytest.approx(1.0 - 0.12 - (STOP + 0.1 + 0.05))
            assert 1 in state.held["f"] and state.shared["f"] == {1: "lead"} and result.conflicts == ()
        else:
            assert 1 not in state.held["f"] and result.waiting_for["f"] == ("x",)


def test_a_follower_whose_end_would_shrink_gets_none_and_waits():
    layout, cycle = _loop(10, 0.65)
    spans = _spans(cycle, 0, 3)
    lead = Robot("lead", spans, 1.4, 0.3, 0.05, 0.12)  # its padded rear reaches b1
    tail = Robot("f", spans, 0.6, 0.3, 0.05, 0.12, convoy="lead")
    state = TableState()
    front = lambda m, after: m.d if m.d > after else None  # noqa: E731
    follow(tail, [lead], front, STOP)
    first = step(layout, [lead, tail], state, now=0.0).authority_end["f"]
    lead.d = None  # leader UNKNOWN: fixed blocks, which end before the shared unit
    follow(tail, [lead], front, STOP)
    later = step(layout, [lead, tail], state, now=0.5)
    assert tail.follows is None and "f" not in later.authority_end and later.waiting_for["f"] == ("lead",)
    assert state.authority["f"] == first
