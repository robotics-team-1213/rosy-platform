"""D-517 M0: fixed-block traffic arithmetic — overlap never, no circular wait under the loop limit."""

import math
import random
from pathlib import Path

import pytest

from fleet.routing.blocks import (
    BlockRules, Layout, Robot, Span, TableState, Unit, build_layout, loop_capacity, release_robot, step,
    wait_cycle)
from fleet.routing.graph import build_graph
from fleet.site_map import SiteMap, from_lane_graph

from core_common.robot_body import PINKY_PRO

ROOT = Path(__file__).resolve().parents[3]
LANE_GRAPH = ROOT / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"
HYSTERESIS = PINKY_PRO.hysteresis_m
BODY = PINKY_PRO.front_x_m - PINKY_PRO.rear_x_m
U_DEMO = 0.12 + 0.05 * 1.5          # sighting floor + 1.5 m bridged drift at 5 % (D-517 3)
DEMO = BlockRules(BODY, U_DEMO, lambda v: PINKY_PRO.stop_gap_m(v) + HYSTERESIS)


def _demo_map():
    body = from_lane_graph(LANE_GRAPH, map_id="map_v2_fleet").body()
    for edge in body["edges"]:
        if edge["id"] in ("east", "west"):  # the demo loop runs these one way, against the file
            edge["from"], edge["to"] = edge["to"], edge["from"]
            edge["polyline"] = edge["polyline"][::-1]
            edge["direction"] = "one_way"
    return SiteMap.model_validate(body)


def test_demo_block_length_and_loop_limit():
    """The demo numbers in D-517 3: ℓ about 0.65 m, the 7.6 m loop takes 3 robots."""
    assert 0.6 < DEMO.block_length(0.2) < 0.7
    graph = build_graph(_demo_map())
    layout = build_layout(graph, DEMO, {"roundabout": (("ring_n", "ring_s", "ring_e", "ring_w"), 1)})
    loop = layout.route(graph, ["east:fwd", "ring_n:fwd", "west:fwd", "ring_s:fwd"])
    assert [s.unit for s in loop].count("roundabout") == 2      # entered twice per lap
    assert sum(1 for s in loop if s.unit.startswith("east#")) == 6
    assert sum(1 for s in loop if s.unit.startswith("west#")) == 4
    assert loop_capacity(loop, layout, held_per_robot=3) == 3


def test_a_two_way_lane_outside_zones_is_one_direction_locked_unit():
    body = from_lane_graph(LANE_GRAPH).body()  # east/west two-way in the file
    layout = build_layout(build_graph(SiteMap.model_validate(body)), DEMO)
    assert layout.units["lane:east"].two_way and layout.units["lane:east"].zone


# ---- synthetic loops ------------------------------------------------------------------

def _loop(blocks: int, length: float, zone_at=None, zone_cap=1):
    """A one-way cycle of plain blocks; ``zone_at`` replaces that many blocks with one zone."""
    units, cycle = {}, []
    index = 0
    while index < blocks:
        if zone_at is not None and index == zone_at[0]:
            units["zone"] = Unit("zone", zone_cap, zone=True)
            cycle.append(("zone", length * zone_at[1]))
            index += zone_at[1]
            continue
        units[f"b{index}"] = Unit(f"b{index}")
        cycle.append((f"b{index}", length))
        index += 1
    return Layout(units, {}), cycle


def _spans(cycle, start_unit_index, laps):
    spans, d = [], 0.0
    order = cycle[start_unit_index:] + cycle[:start_unit_index]
    for _ in range(laps):
        for unit, length in order:
            spans.append(Span(unit, d, d + length))
            d += length
    return tuple(spans)


def _true_units(spans, front, body):
    """Units the real body covers (no estimate padding)."""
    return {s.unit for s in spans if s.d1 > front - body and s.d0 < front}


def _run(layout, cycle, n, *, ticks, seed, unknown_rate=0.0, stall_rate=0.0, u=0.05, body=0.12, packed=False):
    """Robots report ``estimate = true ± u``; CORE drives to ``authority - estimate`` past the
    true position (odom-anchored, D-517 4); UNKNOWN robots coast to their last authority."""
    rng = random.Random(seed)
    robots, true_d, last_auth, prev = [], {}, {}, {}
    if packed:  # queued nose to tail across one boundary, the review's startup case
        spans = _spans(cycle, 0, laps=ticks // 5 + 3)
        for i in range(n):
            robot = Robot(f"r{i:02d}", spans, None, 0.3, u, body)
            robots.append(robot)
            true_d[robot.id] = spans[0].d1 + 0.11 - i * (body + 0.02)
    else:
        for i, start in enumerate(round(i * len(cycle) / n) for i in range(n)):
            spans = _spans(cycle, start, laps=ticks // 5 + 3)
            robot = Robot(f"r{i:02d}", spans, None, 0.3, u, body)
            robots.append(robot)
            true_d[robot.id] = spans[0].d1 - 0.02
    state = TableState()
    conflicts, progress, shrinks = [], {r.id: 0.0 for r in robots}, []
    shared_at_start = None  # packed starts share blocks physically; only clearing them is allowed
    for tick in range(ticks):
        for r in robots:
            r.lookahead_m = rng.choice((0.1, 0.3, 0.6))
            # a trip starts LOCALIZED (D-494): no unknown pose on the first tick
            r.d = None if tick and rng.random() < unknown_rate else true_d[r.id] + rng.uniform(-u, u)
        result = step(layout, robots, state, now=tick * 0.5)
        conflicts.extend(result.conflicts)
        for r in robots:
            if r.id in result.authority_end:
                if result.authority_end[r.id] < prev.get(r.id, -math.inf) - 1e-9:
                    shrinks.append((tick, r.id))
                prev[r.id] = result.authority_end[r.id]
                # odom-anchored stop point: authority measured from this tick's estimate
                last_auth[r.id] = (result.authority_end[r.id], r.d, true_d[r.id])
        for r in robots:
            if r.id not in last_auth or rng.random() < stall_rate:
                continue
            authority, est, true_then = last_auth[r.id]
            stop_at = true_then + (authority - est)
            move = min(rng.uniform(0.0, 0.1), max(0.0, stop_at - true_d[r.id]))
            true_d[r.id] += move
            progress[r.id] += move
        # the physical check: real bodies on a unit never exceed its capacity
        seen = {}
        for r in robots:
            for unit in _true_units(r.spans, true_d[r.id], body):
                seen.setdefault(unit, []).append(r.id)
        over = {u for u, rs in seen.items() if len(rs) > layout.units[u].capacity}
        if shared_at_start is None:
            shared_at_start = over if packed else set()
        shared_at_start &= over
        assert over <= shared_at_start, f"tick {tick}: {[(u, seen[u]) for u in over - shared_at_start]}"
        if packed:  # same route: a follower's front never reaches the leader's rear
            order = sorted(robots, key=lambda r: -true_d[r.id])
            for ahead, behind in zip(order, order[1:]):
                assert true_d[behind.id] <= true_d[ahead.id] - body + 1e-9, f"tick {tick}: contact"
    return conflicts, progress, shrinks


@pytest.mark.parametrize("n,blocks,seed", [(2, 12, 1), (3, 12, 2), (10, 40, 3), (30, 120, 4), (50, 200, 5)])
def test_robots_up_to_the_loop_limit_never_share_a_block_and_keep_moving(n, blocks, seed):
    layout, cycle = _loop(blocks, 0.65, zone_at=(blocks // 3, 2))
    assert n <= loop_capacity(_spans(cycle, 0, 1), layout, 3)
    conflicts, progress, shrinks = _run(layout, cycle, n, ticks=400, seed=seed)
    assert conflicts == [] and shrinks == []
    assert min(progress.values()) > 2 * 0.65, "a robot starved under the loop limit"


def test_unknown_poses_and_stalls_freeze_neighbours_but_never_overlap():
    layout, cycle = _loop(30, 0.65, zone_at=(10, 3))
    conflicts, progress, shrinks = _run(layout, cycle, 8, ticks=600, seed=9, unknown_rate=0.15, stall_rate=0.2)
    assert conflicts == [] and shrinks == []
    assert min(progress.values()) > 0.65


def test_robots_queued_nose_to_tail_untangle_front_first():
    """Review trace: padding of each neighbour covers the other's unit; the front robot goes first."""
    layout, cycle = _loop(20, 0.65)
    conflicts, progress, shrinks = _run(layout, cycle, 3, ticks=300, seed=11, packed=True)
    assert conflicts == [] and shrinks == []
    assert min(progress.values()) > 0.65


def test_zone_capacity_two_holds_two_real_bodies_at_most():
    layout, cycle = _loop(30, 0.65, zone_at=(10, 4), zone_cap=2)
    conflicts, progress, shrinks = _run(layout, cycle, 6, ticks=500, seed=12, unknown_rate=0.1, stall_rate=0.2)
    assert conflicts == [] and shrinks == []


def test_a_robot_never_localized_freezes_new_grants():
    layout, cycle = _loop(8, 0.65)
    ghost = Robot("ghost", _spans(cycle, 0, 3), None, 0.3, 0.05, 0.12)
    other = Robot("other", _spans(cycle, 0, 3), 0.4, 0.6, 0.05, 0.12)
    result = step(layout, [ghost, other], TableState(), now=0.0)
    assert result.unplaced == ("ghost",) and result.authority_end == {}


def test_a_robot_missing_from_a_tick_keeps_blocking_its_units():
    layout, cycle = _loop(8, 0.65)
    a = Robot("a", _spans(cycle, 0, 3), 0.6, 0.6, 0.05, 0.12)
    b = Robot("b", _spans(cycle, 3, 3), 0.6, 0.6, 0.05, 0.12)  # b's front unit is b3
    state = TableState()
    step(layout, [a, b], state, now=0.0)
    a.lookahead_m = 5.0
    lone = step(layout, [a], state, now=0.5)  # b missing this tick
    assert lone.authority_end["a"] <= 3 * 0.65, "a was given b's unit while b was missing"


def test_a_route_change_while_unknown_keeps_the_old_body_blocking():
    layout, cycle = _loop(8, 0.65)
    a = Robot("a", _spans(cycle, 3, 3), 0.6, 0.3, 0.05, 0.12, route_id="old")
    c = Robot("c", _spans(cycle, 0, 3), 0.6, 5.0, 0.05, 0.12)
    state = TableState()
    step(layout, [a, c], state, now=0.0)
    a.d, a.route_id = None, "new"
    after = step(layout, [a, c], state, now=0.5)
    assert after.authority_end["c"] <= 3 * 0.65, "c was given units under a's unlocalized body"


def test_a_short_loop_with_lookahead_past_a_lap_keeps_its_holds_per_occurrence():
    layout, cycle = _loop(3, 0.65)
    spans = _spans(cycle, 0, 20)
    robot = Robot("a", spans, 0.3, 3.0, 0.05, 0.12)
    state = TableState()
    last = -math.inf
    for tick in range(200):
        result = step(layout, [robot], state, now=tick * 0.5)
        assert result.conflicts == ()
        assert result.authority_end["a"] >= last
        last = result.authority_end["a"]
        robot.d = min(robot.d + 0.08, last)
    assert robot.d > 10 * 0.65


def test_a_robot_without_a_localized_pose_gets_no_new_authority_and_keeps_its_units():
    layout, cycle = _loop(6, 0.65)
    spans = _spans(cycle, 0, 3)
    robot = Robot("a", spans, 0.5, 0.3, 0.05, 0.12)
    state = TableState()
    first = step(layout, [robot], state, now=0.0)
    assert first.authority_end["a"] > 0.5
    robot.d = None
    later = step(layout, [robot], state, now=0.5)
    assert "a" not in later.authority_end
    assert state.held["a"] and state.last_occupied["a"], "UNKNOWN keeps grants and body (D-426 3)"


def test_authority_never_shrinks_when_lookahead_drops_or_the_pose_jumps_back():
    """Review case: lookahead 0.6 then 0.1 at the same d, then a 0.05 m backward pose jump."""
    layout, cycle = _loop(8, 0.65)
    a = Robot("a", _spans(cycle, 0, 3), 0.6, 0.6, 0.05, 0.12)
    b = Robot("b", _spans(cycle, 4, 3), 0.6, 0.6, 0.05, 0.12)
    state = TableState()
    ends = []
    for t, (look, d) in enumerate([(0.6, 0.6), (0.1, 0.6), (0.1, 0.55), (0.6, 0.55), (0.1, 0.62)]):
        a.lookahead_m, a.d = look, d
        ends.append(step(layout, [a, b], state, now=t * 0.5).authority_end["a"])
    assert ends == sorted(ends) and ends[0] > 1.2


def test_two_way_lane_lets_one_direction_in_and_holds_the_other():
    layout = Layout({"lane": Unit("lane", 1, two_way=True, zone=True), "w": Unit("w"), "e": Unit("e")}, {})
    east = Robot("east", (Span("w", 0, 0.65), Span("lane", 0.65, 2.0, True), Span("e", 2.0, 2.65)),
                 0.6, 0.3, 0.05, 0.12)
    west = Robot("west", (Span("e", 0, 0.65), Span("lane", 0.65, 2.0, False), Span("w", 2.0, 2.65)),
                 0.6, 0.3, 0.05, 0.12)
    result = step(layout, [east, west], TableState(), now=0.0)
    granted = [r for r in ("east", "west") if result.authority_end[r] > 0.65]
    assert len(granted) == 1
    other = "west" if granted == ["east"] else "east"
    assert result.waiting_for[other] == (granted[0],)


def test_a_robot_waiting_at_a_merge_gets_in_within_the_wait_bound():
    """Robots leaving a zone go first at a merge, but not past merge_max_wait_s (D-517 3)."""
    layout = Layout({"ring": Unit("ring", 9, zone=True), "in": Unit("in"), "merge": Unit("merge")}, {})
    entering = Robot("enter", (Span("in", 0, 0.65), Span("merge", 0.65, 1.3)), 0.6, 0.3, 0.05, 0.12)
    state = TableState()
    admitted_at = None
    for tick in range(200):
        now = tick * 0.5
        # worst case: every tick a fresh robot inside the ring asks for the same merge block
        leaving = Robot(f"x{tick}", (Span("ring", 0, 0.65), Span("merge", 0.65, 1.3)), 0.6, 0.3, 0.05, 0.12)
        if tick:  # the previous competitor left the lanes; Fleet drops it on evidence
            release_robot(state, f"x{tick - 1}")
        result = step(layout, [leaving, entering], state, now=now, merge_max_wait_s=20.0)
        if result.authority_end["enter"] > 0.65:
            admitted_at = now
            break
        assert result.authority_end[leaving.id] > 0.65, "inside-zone robot goes first before the bound"
    assert admitted_at is not None and 19.5 <= admitted_at <= 20.5


def test_wait_cycle_is_found():
    assert wait_cycle({"a": ("b",), "b": ("c",), "c": ("a",)}) == ("a", "b", "c")
    assert wait_cycle({"a": ("b",), "b": ()}) is None
    assert wait_cycle({"a": ("x", "b"), "b": ("a",), "x": ()}) == ("a", "b")
