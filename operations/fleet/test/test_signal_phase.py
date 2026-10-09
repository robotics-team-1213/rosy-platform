"""D-525 S0: a virtual signal gates D-517 zone grants — never a grant on red, next green only when free."""

import random

import pytest

from fleet.routing.graph import build_graph
from fleet.traffic.blocks import Layout, Robot, Span, TableState, Unit, build_layout, loop_capacity, step, wait_cycle
from fleet.traffic.signal_phase import SignalPlan, SignalState, advance, alert, check, command, green

from fleet.site_map import SiteMap, from_lane_graph
from fleet.traffic.signal_phase import entering_arcs
from test_blocks import BODY, DEMO, LANE_GRAPH, U_DEMO, _demo_map

RING = ("ring_n", "ring_s", "ring_e", "ring_w")
PLAN = SignalPlan("sig", "zone", (("in_a", 8.0), ("in_b", 8.0)), yellow_s=2.0, all_red_s=1.0)


def _demo(capacity=1):
    graph = build_graph(_demo_map())
    return graph, build_layout(graph, DEMO, {"roundabout": (RING, capacity)})


def test_demo_roundabout_entrances_and_check():
    graph, layout = _demo()
    ok = SignalPlan("sig_ring", "roundabout", (("east:fwd", 8.0), ("west:fwd", 8.0)))
    assert check(ok, graph, layout) == []
    assert [s.entry for s in layout.route(graph, ["east:fwd", "ring_n:fwd", "west:fwd", "ring_s:fwd"])
            if s.unit == "roundabout"] == ["east:fwd", "west:fwd"]
    assert any("capacity 2" in e for e in check(ok, *_demo(capacity=2)))
    assert any("without a phase: west:fwd" in e for e in check(SignalPlan("s", "roundabout", (("east:fwd", 8.0),)),
                                                                graph, layout))
    assert any("two phases" in e for e in check(
        SignalPlan("s", "roundabout", (("east:fwd", 8.0), ("west:fwd", 8.0), ("east:fwd", 8.0))), graph, layout))
    assert any("not an approach" in e for e in check(
        SignalPlan("s", "roundabout", (("east:fwd", 8.0), ("west:fwd", 8.0), ("ring_n:fwd", 8.0))), graph, layout))
    assert check(SignalPlan("s", "east#0", ()), graph, layout) == ["s: east#0 is not a zone"]


def test_the_live_two_way_map_has_four_roundabout_entrances():
    """The site's active map (2026-10-09, version 2) keeps east/west two-way as in lane_graph.yaml: four
    entrances, so a demo two-entrance plan is refused there until the lanes are made one-way (D-517)."""
    graph = build_graph(SiteMap.model_validate(from_lane_graph(LANE_GRAPH, map_id="map_v2_fleet").body()))
    layout = build_layout(graph, DEMO, {"roundabout": (RING, 1)})
    entries = sorted(entering_arcs(graph, layout, "roundabout"))
    assert entries == ["east:fwd", "east:rev", "west:fwd", "west:rev"]
    two = SignalPlan("sig", "roundabout", (("east:fwd", 8.0), ("west:fwd", 8.0)))
    assert check(two, graph, layout) == ["sig: approaches without a phase: east:rev, west:rev"]
    assert check(SignalPlan("sig", "roundabout", tuple((a, 8.0) for a in entries)), graph, layout) == []


def _drive(state, plan, times, busy=lambda t: False):
    seen = []
    for t in times:
        advance(plan, state, t, busy(t))
        seen.append((t, state.aspect, sorted(green(plan, state))))
    return seen


def test_a_fresh_signal_is_all_red_until_an_operator_cycles_it():
    state = SignalState()
    assert {a for _t, a, _g in _drive(state, PLAN, range(30))} == {"all_red"}
    command(PLAN, state, "cycle", 30.0)
    seen = dict((t, (a, g)) for t, a, g in _drive(state, PLAN, [30.0 + i * 0.5 for i in range(80)]))
    assert seen[30.0] == ("green", ["in_a"])      # all red already ran its 1 s
    assert seen[37.5] == ("green", ["in_a"]) and seen[38.0] == ("yellow", [])   # 8 s green
    assert seen[39.5] == ("yellow", []) and seen[40.0] == ("all_red", [])      # 2 s yellow
    assert seen[40.5] == ("all_red", []) and seen[41.0] == ("green", ["in_b"])  # 1 s all red


def test_next_green_waits_while_the_zone_is_busy_and_then_alerts():
    state = SignalState()
    command(PLAN, state, "cycle", 0.0)
    seen = _drive(state, PLAN, [i * 0.5 for i in range(200)], busy=lambda t: t < 60.0)
    assert all(a == "all_red" for t, a, _g in seen if t < 60.0)
    assert ("green" in {a for t, a, _g in seen if t >= 60.0})
    stuck = SignalState()
    command(PLAN, stuck, "cycle", 0.0)
    _drive(stuck, PLAN, [i * 0.5 for i in range(100)], busy=lambda t: True)
    assert alert(PLAN, stuck, 49.5) == "all_red_stretched"


def test_manual_green_goes_through_yellow_and_all_red_and_only_lights_its_approach():
    state = SignalState()
    command(PLAN, state, "cycle", 0.0)
    _drive(state, PLAN, [0.0, 1.0])
    assert green(PLAN, state) == {"in_a"}
    command(PLAN, state, "set_aspect", 2.0, approach="in_b")
    seen = _drive(state, PLAN, [2.0 + i * 0.5 for i in range(20)])
    assert [a for _t, a, _g in seen][:2] == ["yellow", "yellow"]
    assert all(len(g) <= 1 for _t, _a, g in seen)
    assert seen[-1][1:] == ("green", ["in_b"])
    _drive(state, PLAN, [100.0])                   # manual stays green, no cycling
    assert green(PLAN, state) == {"in_b"}


def test_all_red_is_immediate_and_hold_alerts_when_long():
    state = SignalState()
    command(PLAN, state, "cycle", 0.0)
    _drive(state, PLAN, [1.0])
    command(PLAN, state, "all_red", 2.0)
    assert state.aspect == "all_red" and green(PLAN, state) == frozenset()
    assert _drive(state, PLAN, [10.0, 100.0])[-1][1] == "all_red"
    command(PLAN, state, "hold", 100.0)
    assert alert(PLAN, state, 219.0) is None and alert(PLAN, state, 221.0) == "hold_long"


def test_a_red_zone_is_refused_ahead_and_under_a_jumped_front():
    layout = Layout({"a0": Unit("a0"), "b0": Unit("b0"), "zone": Unit("zone", 1, zone=True), "x": Unit("x")}, {})
    from_a = (Span("a0", 0, 0.65), Span("zone", 0.65, 1.3, entry="in_a"), Span("x", 1.3, 1.95))
    from_b = (Span("b0", 0, 0.65), Span("zone", 0.65, 1.3, entry="in_b"), Span("x", 1.3, 1.95))
    a = Robot("a", from_a, 0.5, 0.6, 0.05, 0.12)
    b = Robot("b", from_b, 0.5, 0.6, 0.05, 0.12)
    state = TableState()
    result = step(layout, [a, b], state, 0.0, green={"zone": {"in_a"}})
    assert result.authority_end["a"] > 0.65 and result.authority_end["b"] <= 0.65
    assert result.waiting_for["b"] == ("signal:zone",) and result.waiting_for["signal:zone"] == ("a",)
    assert "b" not in state.waiting_since, "a red wait is not a merge wait"
    assert "zone" in result.busy
    # b's estimate lands in the zone on red (within u of a body before the line): still refused
    b.d = 1.1
    after = step(layout, [a, b], TableState(), 0.5, green={"zone": set()})
    assert after.authority_end["b"] <= 0.65 and "zone" not in after.busy


def _loop_with_two_entries(plain: int, zone_blocks: int, length: float):
    """One-way loop: ``plain`` blocks, the zone from in_a, ``plain`` blocks, the zone again from in_b."""
    units, cycle = {"zone": Unit("zone", 1, zone=True)}, []
    for side in ("a", "b"):
        for i in range(plain):
            units[f"{side}{i}"] = Unit(f"{side}{i}")
            cycle.append((f"{side}{i}", length, ""))
        cycle.append(("zone", length * zone_blocks, f"in_{side}"))
    return Layout(units, {}), cycle


def _spans(cycle, start, laps):
    spans, d = [], 0.0
    for _ in range(laps):
        for unit, length, entry in cycle[start:] + cycle[:start]:
            spans.append(Span(unit, d, d + length, entry=entry))
            d += length
    return tuple(spans)


def _simulate(layout, cycle, plan, n, seed, edge_rate, unknown_rate, *, u=0.05, body=0.12, ticks=2400):
    """Robots on a one-way loop of ``cycle`` ``(unit, length, entry)`` with ``plan`` gating its zone.
    Estimates are true ± u, at the ±u edge with ``edge_rate`` (the worst case D-517 allows); CORE drives to ``authority − estimate`` past the true
    position (odom-anchored, D-517 4). Checks every tick: no zone grant on red, no real body in the
    zone without a grant, no green while busy, no circular wait; at the end every robot did a lap."""
    zone = plan.zone
    rng = random.Random(seed)
    assert n <= loop_capacity(_spans(cycle, 0, 1), layout, 3)
    robots, true_d, last_auth, granted_on = [], {}, {}, {}
    for i, start in enumerate(round(i * len(cycle) / n) for i in range(n)):
        spans = _spans(cycle, start, laps=ticks // 40 + 4)
        if spans[0].unit == zone:  # D-525 1: no route starts inside a signalled zone
            spans = spans[1:]
        robots.append(Robot(f"r{i}", spans, None, 0.3, u, body))
        true_d[f"r{i}"] = spans[0].d1 - 0.02
    state, signal, busy = TableState(), SignalState(), True
    command(plan, signal, "cycle", 0.0)
    progress = dict.fromkeys(true_d, 0.0)
    for tick in range(ticks):
        now = tick * 0.5
        was = signal.aspect
        advance(plan, signal, now, busy)
        if signal.aspect == "green" and was != "green":
            assert not busy
        lit = green(plan, signal)
        for r in robots:
            r.lookahead_m = rng.choice((0.1, 0.3, 0.6))
            # D-517 assumes every estimate is within u of the body. A jump past u breaks every block, not
            # only a signal (until_m is measured from the estimate): a forward jump across a short zone
            # skips it, a backward one overruns the authority. Fleet refuses gross jumps (lane_traffic
            # jump guard); inside that bound u itself must be true. So: noise within u, often at its edge.
            error = rng.choice((-u, u)) if rng.random() < edge_rate else rng.uniform(-u, u)
            r.d = None if tick and rng.random() < unknown_rate else true_d[r.id] + error
        before = {r.id: set(state.held.get(r.id, {})) for r in robots}
        result = step(layout, robots, state, now, green={zone: lit})
        assert result.conflicts == ()
        busy = zone in result.busy
        for r in robots:
            for i in set(state.held.get(r.id, {})) - before[r.id]:
                if r.spans[i].unit == zone:
                    assert r.spans[i].entry in lit, f"tick {tick}: {r.id} granted the zone on red"
                    granted_on[(r.id, i)] = tick
            if r.id in result.authority_end:
                last_auth[r.id] = (result.authority_end[r.id], r.d, true_d[r.id])
        for r in robots:
            if r.id in last_auth:
                authority, est, then = last_auth[r.id]
                move = min(rng.uniform(0.0, 0.1), max(0.0, then + (authority - est) - true_d[r.id]))
                true_d[r.id] += move
                progress[r.id] += move
        # the physical check: a real body in a zone occurrence always had that occurrence granted
        for r in robots:
            for i, s in enumerate(r.spans):
                if s.unit == zone and s.d1 > true_d[r.id] - body and s.d0 < true_d[r.id]:
                    assert (r.id, i) in granted_on, f"tick {tick}: {r.id} in the zone without a grant"
        assert wait_cycle(result.waiting_for) is None, f"tick {tick}: circular wait"
    loop_m = sum(length for _u, length, _e in cycle)
    assert min(progress.values()) > loop_m, f"a robot starved: {progress}"


@pytest.mark.parametrize("n,seed,edge_rate,unknown_rate", [(2, 1, 0.0, 0.0), (3, 2, 0.0, 0.0),
                                                           (3, 3, 0.3, 0.1), (2, 4, 0.5, 0.15)])
def test_random_loop_never_enters_on_red_and_never_deadlocks(n, seed, edge_rate, unknown_rate):
    layout, cycle = _loop_with_two_entries(5, 2, 0.65)
    _simulate(layout, cycle, PLAN, n, seed, edge_rate, unknown_rate)


@pytest.mark.parametrize("n,seed,edge_rate,unknown_rate", [(2, 11, 0.0, 0.0), (3, 12, 0.0, 0.0),
                                                           (3, 13, 0.3, 0.1), (2, 14, 0.5, 0.15)])
def test_real_site_loop_never_enters_on_red_and_never_deadlocks(n, seed, edge_rate, unknown_rate):
    """The live site map (map_v2_fleet, demo one-way loop east → ring_n → west → ring_s) with the real
    roundabout as the signalled zone: two 0.37 m passes per 7.6 m lap, entered from east:fwd and
    west:fwd. Real u (0.195 m) and the Pinky body (D-517 3)."""
    graph, layout = _demo()
    plan = SignalPlan("sig_ring", "roundabout", (("east:fwd", 8.0), ("west:fwd", 8.0)))
    assert check(plan, graph, layout) == []
    lap = layout.route(graph, ["east:fwd", "ring_n:fwd", "west:fwd", "ring_s:fwd"])
    cycle = [(s.unit, s.d1 - s.d0, s.entry) for s in lap]
    assert [(round(length, 2), entry) for unit, length, entry in cycle if unit == "roundabout"] == \
        [(0.37, "east:fwd"), (0.37, "west:fwd")]
    _simulate(layout, cycle, plan, n, seed, edge_rate, unknown_rate, u=U_DEMO, body=BODY, ticks=3200)


def test_forecast_counts_down_like_a_traffic_light():
    """D-525 rev 3: T-map style seconds; a future green is a lower bound (the zone must be free)."""
    from fleet.traffic.signal_phase import forecast
    state = SignalState()
    command(PLAN, state, "cycle", 0.0)
    advance(PLAN, state, 1.0, False)               # 1 s all red, then in_a green at 1 for 8 s
    f = forecast(PLAN, state, 4.0, False)
    assert f["in_a"] == {"lamp": "green", "left_s": 5.0, "green_in_s": 0.0, "exact": True}
    assert f["in_b"] == {"lamp": "red", "left_s": 8.0, "green_in_s": 8.0, "exact": False}  # 5 + 2 + 1
    _drive(state, PLAN, [9.0])                     # yellow
    f = forecast(PLAN, state, 10.0, False)
    assert f["in_a"]["lamp"] == "yellow" and f["in_a"]["left_s"] == 1.0
    assert f["in_b"]["green_in_s"] == 2.0          # 1 yellow + 1 all red
    assert f["in_a"]["green_in_s"] == 2.0 + 8 + 2 + 1  # after in_b's whole phase
    _drive(state, PLAN, [11.0])                    # all red, zone busy: everything is a lower bound
    f = forecast(PLAN, state, 11.5, True)
    assert f["in_b"]["green_in_s"] == 0.5 and not f["in_b"]["exact"]
    command(PLAN, state, "hold", 12.0)
    assert forecast(PLAN, state, 12.0, False)["in_b"]["green_in_s"] is None   # holding: no time known
    command(PLAN, state, "all_red", 13.0)
    assert all(r["left_s"] is None and r["green_in_s"] is None for r in forecast(PLAN, state, 13.0, False).values())
