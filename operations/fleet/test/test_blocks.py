"""D-517 M0: fixed-block traffic arithmetic — overlap never, no circular wait under the loop limit."""

import json
import math
import random
from pathlib import Path

import pytest

from fleet.routing.blocks import (
    BlockRules, Layout, Robot, Span, TableState, Unit, build_layout, loop_capacity, step, wait_cycle)
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


def _run(layout, cycle, n, *, ticks, seed, lookahead, unknown_rate=0.0, stall_rate=0.0):
    rng = random.Random(seed)
    h_unit = cycle[0][1]
    starts = [round(i * len(cycle) / n) for i in range(n)]
    robots = []
    for i, start in enumerate(starts):
        spans = _spans(cycle, start, laps=ticks // 5 + 3)
        robots.append(Robot(f"r{i:02d}", spans, spans[0].d1 - 0.02, lookahead, 0.05, min(0.12, h_unit / 4)))
    true_d = {r.id: r.d for r in robots}
    state = TableState()
    worst_conflicts, progress = [], {r.id: 0.0 for r in robots}
    for tick in range(ticks):
        for r in robots:
            r.d = None if rng.random() < unknown_rate else true_d[r.id]
        result = step(layout, robots, state, now=tick * 0.5)
        worst_conflicts.extend(result.conflicts)
        assert wait_cycle(result.waiting_for) is None, f"tick {tick}: circular wait"
        for r in robots:
            end = result.authority_end.get(r.id)
            if end is None or rng.random() < stall_rate:
                continue
            move = min(rng.uniform(0.0, 0.1), max(0.0, end - true_d[r.id]))
            true_d[r.id] += move
            progress[r.id] += move
    return worst_conflicts, progress


@pytest.mark.parametrize("n,blocks,seed", [(2, 12, 1), (3, 12, 2), (10, 40, 3), (30, 120, 4), (50, 200, 5)])
def test_robots_up_to_the_loop_limit_never_share_a_block_and_keep_moving(n, blocks, seed):
    layout, cycle = _loop(blocks, 0.65, zone_at=(blocks // 3, 2))
    h = 3
    spans = _spans(cycle, 0, 1)
    assert n <= loop_capacity(spans, layout, h)
    conflicts, progress = _run(layout, cycle, n, ticks=400, seed=seed, lookahead=0.3)
    assert conflicts == []
    assert min(progress.values()) > 2 * 0.65, "a robot starved under the loop limit"


def test_unknown_poses_and_stalls_freeze_neighbours_but_never_overlap():
    layout, cycle = _loop(30, 0.65, zone_at=(10, 3))
    conflicts, progress = _run(layout, cycle, 8, ticks=600, seed=9, lookahead=0.3,
                               unknown_rate=0.15, stall_rate=0.2)
    assert conflicts == []
    assert min(progress.values()) > 0.65


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
    assert state.held["a"], "units held while UNKNOWN are not released (D-426 3)"


def test_authority_never_shrinks_while_the_robot_is_short_of_it():
    layout, cycle = _loop(8, 0.65)
    a = Robot("a", _spans(cycle, 0, 3), 0.6, 0.6, 0.05, 0.12)
    b = Robot("b", _spans(cycle, 4, 3), 0.6, 0.6, 0.05, 0.12)
    state = TableState()
    ends = [step(layout, [a, b], state, now=t * 0.5).authority_end["a"] for t in range(5)]
    assert ends == sorted(ends)


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
    assert result.waiting_for[other] == granted[0]


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
        state.held = {"enter": state.held.get("enter", {})}
        result = step(layout, [leaving, entering], state, now=now, merge_max_wait_s=20.0)
        if result.authority_end["enter"] > 0.65:
            admitted_at = now
            break
        assert result.authority_end[leaving.id] > 0.65, "inside-zone robot goes first before the bound"
    assert admitted_at is not None and 19.5 <= admitted_at <= 20.5


def test_wait_cycle_is_found():
    assert wait_cycle({"a": "b", "b": "c", "c": "a"}) == ("a", "b", "c")
    assert wait_cycle({"a": "b", "b": None}) is None
