"""D-485/D-486 7 (a)(b)(c)(e): the lane-state A* planner on the D-484 site map."""

from __future__ import annotations

import ast
import heapq
import math
import random
import time
from pathlib import Path

import pytest

from fleet.routing.cost import RoutingConfig, classify, transition_cost
from fleet.routing.graph import build_graph
from fleet.routing.planner import Goal, search
from fleet.routing.snap import PlanError
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.site_map import SiteMap, from_lane_graph

ROOT = Path(__file__).resolve().parents[3]
LANE_GRAPH = ROOT / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"
ROUTING = Path(__file__).resolve().parents[1] / "fleet" / "routing"
CFG = RoutingConfig()
W = 0.2


def _map(places: dict, edges: list, bans=()) -> SiteMap:
    """``places`` {id: (x, y[, kind])}; ``edges`` (id, from, to[, two_way, extra fields])."""
    return SiteMap(
        places=[{"id": pid, "name": pid, "x": v[0], "y": v[1], "kind": v[2] if len(v) > 2 else "junction"}
                for pid, v in places.items()],
        edges=[{"id": e[0], "from": e[1], "to": e[2],
                "polyline": [places[e[1]][:2], places[e[2]][:2]],
                "direction": "two_way" if len(e) > 3 and e[3] else "one_way",
                "width_m": W, "speed_cap_mps": 1.0, **(e[4] if len(e) > 4 else {})} for e in edges],
        turn_bans=[{"at": b[0], "from_edge": b[1], "to_edge": b[2]} for b in bans])


def _plan(site_map, start, goal, **kw):
    graph = build_graph(site_map, version=1)
    return plan_trip(graph, PlanRequest(map_version=1, start_pose=start, goal=goal, **kw), CFG)


def _edges(plan):
    return [e if f else e + "~" for e, f, _a, _b in plan.segments]


# A plus-shaped junction C with arms W, E, N, S and a ring E -> N.
CROSS = {"W": (-1, 0), "C": (0, 0), "E": (1, 0), "N": (0, 1), "S": (0, -1), "K": (1, 1)}
CROSS_EDGES = [("w_c", "W", "C"), ("c_e", "C", "E"), ("c_n", "C", "N"), ("s_c", "S", "C"),
               ("e_k", "E", "K"), ("k_n", "K", "N"), ("c_w", "C", "W")]
ON_W_C = (-0.8, 0.0, 0.0)  # on w_c heading east


# ---- (b) rules ----------------------------------------------------------------------

def test_one_way_lane_is_not_driven_backwards():
    site = _map({"A": (0, 0), "B": (1, 0), "C": (2, 0)}, [("ab", "A", "B"), ("bc", "B", "C")])
    assert _edges(_plan(site, (0.1, 0, 0), "C")) == ["ab", "bc"]
    with pytest.raises(PlanError) as err:
        _plan(site, (1.9, 0, math.pi), "A")
    assert err.value.code == "TRIP_HEADING_CONFLICT"


def test_uturn_is_refused_at_a_junction_and_allowed_at_a_turnaround():
    places = {"A": (0, 0), "B": (1, 0)}
    with pytest.raises(PlanError) as err:
        _plan(_map(places, [("ab", "A", "B", True)]), (0.2, 0, 0), "A")
    assert err.value.code == "TRIP_NO_ROUTE"
    plan = _plan(_map({**places, "B": (1, 0, "turnaround")}, [("ab", "A", "B", True)]), (0.2, 0, 0), "A")
    assert _edges(plan) == ["ab", "ab~"]
    assert plan.actions[0][:2] == ("B", "uturn") and plan.actions[-1] == ("A", "stop", 0.0)
    assert plan.eta_s == pytest.approx(0.8 + CFG.uturn_cost_s + CFG.place_pass_cost_s + 1.0)


def test_turn_ban_sends_the_route_round_the_ring():
    site = _map(CROSS, CROSS_EDGES)
    assert _edges(_plan(site, ON_W_C, "N")) == ["w_c", "c_n"]
    banned = _map(CROSS, CROSS_EDGES, bans=[("C", "w_c", "c_n")])
    assert _edges(_plan(banned, ON_W_C, "N")) == ["w_c", "c_e", "e_k", "k_n"]


def test_left_and_right_actions_follow_the_sign_of_the_turn():
    assert _plan(_map(CROSS, CROSS_EDGES), ON_W_C, "N").actions[0] == ("C", "left", 90.0)
    south = _map(CROSS, [("n_c", "N", "C"), ("c_w", "C", "W")])
    assert _plan(south, (0.0, 0.8, -math.pi / 2), "W").actions[0] == ("C", "right", -90.0)
    assert classify(10.0, CFG) == "straight" and classify(170.0, CFG) == "uturn"


def test_arrive_yaw_picks_the_arriving_lane_or_is_unreachable():
    site = _map(CROSS, CROSS_EDGES + [("s_w", "S", "W", True)])
    assert _edges(_plan(site, ON_W_C, "C")) == ["w_c"]
    with pytest.raises(PlanError) as err:
        _plan(site, ON_W_C, "C", arrive_yaw=math.pi)  # nothing arrives at C facing west
    assert err.value.code == "TRIP_ARRIVE_YAW_UNREACHABLE"


def test_arrive_yaw_takes_a_longer_lane_when_one_arrives_facing_it():
    places = {"Z": (-2, 0), "W": (-1, 0), "C": (0, 0), "S": (0, -1)}
    site = _map(places, [("z_w", "Z", "W"), ("w_c", "W", "C"), ("w_s", "W", "S"), ("s_c", "S", "C")])
    assert _edges(_plan(site, (-1.5, 0, 0), "C")) == ["z_w", "w_c"]
    assert _edges(_plan(site, (-1.5, 0, 0), "C", arrive_yaw=math.pi / 2)) == ["z_w", "w_s", "s_c"]


def test_via_place_is_never_a_uturn():
    line = {"A": (0, 0), "B": (1, 0), "C": (2, 0)}
    edges = [("ab", "A", "B", True), ("bc", "B", "C", True)]
    with pytest.raises(PlanError) as err:
        _plan(_map(line, edges), (0.2, 0, 0), "A", via=("B",))
    assert err.value.code == "TRIP_NO_ROUTE" and err.value.detail["segment"] == 1
    plan = _plan(_map({**line, "C": (2, 0, "turnaround")}, edges), (0.2, 0, 0), "A", via=("C",))
    assert _edges(plan) == ["ab", "bc", "bc~", "ab~"]
    assert [a[1] for a in plan.actions] == ["straight", "uturn", "straight", "stop"]


def test_coordinate_target_snaps_within_twice_the_width():
    site = _map({"A": (0, 0), "B": (2, 0)}, [("ab", "A", "B")])
    plan = _plan(site, (0.1, 0, 0), (1.5, 1.9 * W, None))
    assert plan.segments == (("ab", True, 0.1, 1.5),) and plan.actions == ((None, "stop", 0.0),)
    with pytest.raises(PlanError) as err:
        _plan(site, (0.1, 0, 0), (1.5, 2.1 * W, None))
    assert err.value.code == "TRIP_OFF_MAP"


def test_start_off_the_map_and_unknown_place_and_stale_version():
    site = _map({"A": (0, 0), "B": (2, 0)}, [("ab", "A", "B")])
    with pytest.raises(PlanError) as err:
        _plan(site, (1.0, 1.0, 0), "B")
    assert err.value.code == "TRIP_START_OFF_MAP"
    with pytest.raises(PlanError) as err:
        _plan(site, (0.1, 0, 0), "nowhere")
    assert err.value.code == "TRIP_UNKNOWN_PLACE" and err.value.detail == {"place": "nowhere"}
    with pytest.raises(PlanError) as err:
        plan_trip(build_graph(site, version=2), PlanRequest(1, (0.1, 0, 0), "B"), CFG)
    assert err.value.code == "TRIP_NO_ACTIVE_MAP"


def test_exclusions_and_unblock_would_help():
    places = {"A": (0, 0), "B": (1, 0), "C": (2, 0)}
    edges = [("ab", "A", "B"), ("bc", "B", "C")]
    with pytest.raises(PlanError) as err:
        _plan(_map(places, edges), (0.1, 0, 0), "C", blocked_edges=frozenset({"bc"}))
    assert err.value.detail == {"segment": 0, "unblock_would_help": True}
    kinds = [("ab", "A", "B"), ("bc", "B", "C", False, {"robot_kinds": ["omx"]})]
    with pytest.raises(PlanError) as err:
        _plan(_map(places, kinds), (0.1, 0, 0), "C", robot_kind="pinky")
    assert err.value.detail == {"segment": 0, "unblock_would_help": False}
    assert _edges(_plan(_map(places, kinds), (0.1, 0, 0), "C", robot_kind="omx")) == ["ab", "bc"]
    free = [("ab", "A", "B"), ("bc", "B", "C", False, {"drive_mode": "free"})]
    with pytest.raises(PlanError):
        _plan(_map(places, free), (0.1, 0, 0), "C", drive_modes=frozenset({"lane"}))


def test_equal_routes_tie_break_the_same_way_every_time():
    diamond = {"Z": (-1, 0), "A": (0, 0), "U": (1, 1), "D": (1, -1), "B": (2, 0)}
    site = _map(diamond, [("z_a", "Z", "A"), ("a_u", "A", "U"), ("a_d", "A", "D"),
                          ("u_b", "U", "B"), ("d_b", "D", "B")])
    plans = {tuple(_edges(_plan(site, (-0.5, 0, 0), "B"))) for _ in range(100)}
    # equal f and g: the smaller arc id ("a_d:fwd" < "a_u:fwd") is expanded and kept first
    assert plans == {("z_a", "a_d", "d_b")}


def test_routing_config_rejects_out_of_range_and_unknown_keys():
    assert RoutingConfig.from_mapping(None) == RoutingConfig()
    for bad in ({"turn_cost_s": -1}, {"straight_max_deg": 140}, {"heading_tol_deg": 0},
                {"snap_width_factor": 0}, {"turn_cost": 1}, {"uturn_cost_s": True}):
        with pytest.raises(ValueError):
            RoutingConfig.from_mapping(bad)
    assert transition_cost(180.0, "junction", CFG) is None


# ---- review cases (2026-10-07) -------------------------------------------------------

def test_zero_length_lanes_and_stacked_places_are_refused_by_the_schema():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="same point"):
        _map({"A": (0, 0), "B": (0, 0.03), "C": (1, 0)}, [("ab", "A", "B"), ("bc", "B", "C")])
    with pytest.raises(ValidationError, match="shorter than"):
        SiteMap(places=[{"id": "A", "name": "A", "x": 0, "y": 0}, {"id": "C", "name": "C", "x": 1, "y": 0}],
                edges=[{"id": "aa", "from": "A", "to": "A", "polyline": [(0, 0), (0.04, 0)],
                        "width_m": W, "speed_cap_mps": 1.0}])


def test_a_via_is_planned_with_the_whole_trip_not_greedily():
    """Reviewer probe: the cheapest way into V turns into a banned exit; the trip goes round."""
    places = {"Y": (-2, -1), "X": (-1, -1), "W": (-1, 0), "S": (0, -2), "V": (0, 0), "N": (0, 1)}
    edges = [("y_x", "Y", "X"), ("x_w", "X", "W"), ("x_s", "X", "S"), ("w_v", "W", "V"),
             ("s_v", "S", "V"), ("v_n", "V", "N")]
    site = _map(places, edges, bans=[("V", "w_v", "v_n")])
    plan = _plan(site, (-1.5, -1, 0), "N", via=("V",))
    assert _edges(plan) == ["y_x", "x_s", "s_v", "v_n"]
    assert plan.places == ("X", "S", "V", "N") and plan.eta_s == _plan(site, (-1.5, -1, 0), "N").eta_s


def test_extra_cost_is_counted_once_and_steers_the_route():
    diamond = {"Z": (-1, 0), "A": (0, 0), "U": (1, 1), "D": (1, -1), "B": (2, 0)}
    site = _map(diamond, [("z_a", "Z", "A"), ("a_u", "A", "U"), ("a_d", "A", "D"),
                          ("u_b", "U", "B"), ("d_b", "D", "B")])
    base = _plan(site, (-0.5, 0, 0), "B")
    plan = _plan(site, (-0.5, 0, 0), "B", extra_cost={"a_d": 1.0})
    assert _edges(plan) == ["z_a", "a_u", "u_b"] and plan.eta_s == pytest.approx(base.eta_s)
    via = _plan(site, (-0.5, 0, 0), "B", via=("A",), extra_cost={"z_a": 3.0})
    assert via.eta_s == pytest.approx(base.eta_s + 3.0)
    for bad in ({"extra_cost": {"a_d": -1.0}}, {"extra_cost": {"a_d": math.inf}}, {"max_speed_mps": 0.0}):
        with pytest.raises(ValueError):
            _plan(site, (-0.5, 0, 0), "B", **bad)


def test_a_robot_already_on_the_goal_place_gets_an_empty_plan():
    ring = {"A": (0, 0), "B": (1, 0), "C": (1, 1), "D": (0, 1)}
    site = _map(ring, [("ab", "A", "B"), ("bc", "B", "C"), ("cd", "C", "D"), ("da", "D", "A")])
    plan = _plan(site, (1.0, 0.0, 0.0), "B")
    assert plan.segments == () and plan.actions == (("B", "stop", 0.0),) and plan.eta_s == 0.0
    turned = _plan(site, (1.0, 0.0, math.pi / 2), "B", arrive_yaw=0.0)  # facing north: once round
    assert _edges(turned) == ["bc", "cd", "da", "ab"]


def test_parallel_lanes_a_coordinate_yaw_picks_the_lane_facing_it():
    box = {"A": (0, 0), "B": (2, 0), "C": (2, 0.3), "D": (0, 0.3)}
    site = _map(box, [("ab", "A", "B"), ("bc", "B", "C"), ("cd", "C", "D"), ("da", "D", "A")])
    west = _plan(site, (0.5, 0, 0), (1.0, 0.02, math.pi))
    assert _edges(west)[-1] == "cd" and west.segments[-1][3] == pytest.approx(1.0)
    east = _plan(site, (0.5, 0, 0), (1.0, 0.28, 0.0))
    assert _edges(east) == ["ab"]
    with pytest.raises(PlanError) as err:
        _plan(site, (0.5, 0, 0), (1.0, 0.02, math.pi / 2))
    assert err.value.code == "TRIP_ARRIVE_YAW_UNREACHABLE"


def test_start_snaps_within_half_the_lane_width():
    site = _map({"A": (0, 0), "B": (2, 0)}, [("ab", "A", "B")])
    assert _edges(_plan(site, (0.5, 0.45 * W, 0), "B")) == ["ab"]
    with pytest.raises(PlanError) as err:
        _plan(site, (0.5, 0.55 * W, 0), "B")
    assert err.value.code == "TRIP_START_OFF_MAP"


def test_a_pinned_end_a_few_cm_off_is_not_read_as_a_turn():
    places = {"A": (0, 0), "B": (1, 0), "C": (2, 0)}
    site = SiteMap(places=[{"id": k, "name": k, "x": v[0], "y": v[1]} for k, v in places.items()],
                   edges=[{"id": "ab", "from": "A", "to": "B", "polyline": [(0, 0), (1, 0)], "width_m": W,
                           "speed_cap_mps": 1.0},
                          {"id": "bc", "from": "B", "to": "C", "polyline": [(1.0, 0.049), (1.02, 0.049), (2, 0)],
                           "width_m": W, "speed_cap_mps": 1.0}])
    plan = _plan(site, (0.5, 0, 0), "C")
    assert plan.actions[0][:2] == ("B", "straight")


def test_unblock_hint_is_checked_against_the_arrive_yaw_goal():
    box = {"A": (0, 0), "B": (1, 0), "C": (1, 1), "Z": (-1, 0)}
    site = _map(box, [("za", "Z", "A"), ("ab", "A", "B"), ("ac", "A", "C"), ("cb", "C", "B")])
    with pytest.raises(PlanError) as err:  # only cb arrives facing south, and it is blocked
        _plan(site, (-0.5, 0, 0), "B", arrive_yaw=-math.pi / 2, blocked_edges=frozenset({"cb"}))
    assert err.value.code == "TRIP_NO_ROUTE" and err.value.detail["unblock_would_help"] is True
    with pytest.raises(PlanError) as err:  # blocking ab does not matter for that yaw
        _plan(site, (-0.5, 0, 0), "B", arrive_yaw=math.pi / 2, blocked_edges=frozenset({"ab"}))
    assert err.value.code == "TRIP_ARRIVE_YAW_UNREACHABLE"


# ---- (a) admissible heuristic: A* cost == an independent textbook Dijkstra -----------

def _random_map(rng: random.Random) -> SiteMap:
    """Places on a jittered 1 m grid (never closer than 0.6 m), lanes bent through a midpoint."""
    n = rng.randint(4, 12)
    cells = rng.sample([(cx, cy) for cx in range(5) for cy in range(5)], n)
    places = {f"p{i}": (cx + rng.uniform(-0.2, 0.2), cy + rng.uniform(-0.2, 0.2),
                        "turnaround" if rng.random() < 0.2 else "junction") for i, (cx, cy) in enumerate(cells)}
    ids = sorted(places)
    edges = []
    for k in range(rng.randint(n, 3 * n)):
        a, b = rng.sample(ids, 2)
        (ax, ay, _), (bx, by, _) = places[a], places[b]
        bend = (ax + bx) / 2 + rng.uniform(-0.4, 0.4), (ay + by) / 2 + rng.uniform(-0.4, 0.4)
        edges.append({"id": f"e{k}", "from": a, "to": b, "polyline": [(ax, ay), bend, (bx, by)],
                      "direction": rng.choice(["one_way", "two_way"]), "width_m": 0.3,
                      "speed_cap_mps": rng.choice([0.1, 0.2, 0.5])})
    return SiteMap(places=[{"id": p, "name": p, "x": v[0], "y": v[1], "kind": v[2]} for p, v in places.items()],
                   edges=edges)


def _textbook(graph, start, s0, place=None, on_arcs=None, via=(), extra=None):
    """Plain Dijkstra over (layer, arc) written from D-485 3 alone (no planner code)."""
    extra = extra or {}

    def turn(a, b):
        theta = math.degrees((b.start_tangent - a.end_tangent + math.pi) % (2 * math.pi) - math.pi)
        kind = graph.places[a.end_place].kind
        if abs(theta) > CFG.uturn_min_deg:
            return None if kind != "turnaround" else CFG.uturn_cost_s + CFG.place_pass_cost_s
        return (CFG.turn_cost_s if abs(theta) > CFG.straight_max_deg else 0.0) + CFG.place_pass_cost_s

    def cost(arc, a, b):
        return (b - a) / arc.speed_cap_mps + extra.get(arc.edge_id, 0.0)

    arcs, best = graph.arcs, math.inf
    first = arcs[start]
    dist = {(0, "^"): cost(first, s0, first.length_m)}
    if not via and on_arcs and on_arcs.get(start, -1) >= s0:
        best = cost(first, s0, on_arcs[start])
    heap = [(dist[(0, "^")], 0, "^")]
    while heap:
        g, k, name = heapq.heappop(heap)
        if g > dist.get((k, name), math.inf) or g >= best:
            continue
        arc = first if name == "^" else arcs[name]
        if k < len(via) and arc.end_place == via[k]:
            if g < dist.get((k + 1, name), math.inf):
                dist[(k + 1, name)] = g
                heapq.heappush(heap, (g, k + 1, name))
            continue
        if k == len(via) and arc.end_place == place:
            best = min(best, g)
        for nxt_id in graph.out_of[arc.end_place]:
            nxt = arcs[nxt_id]
            step = None if (arc.end_place, arc.edge_id, nxt.edge_id) in graph.bans else turn(arc, nxt)
            if step is None:
                continue
            if k == len(via) and on_arcs and nxt_id in on_arcs:
                best = min(best, g + step + cost(nxt, 0.0, on_arcs[nxt_id]))
            g2 = g + step + cost(nxt, 0.0, nxt.length_m)
            if g2 < dist.get((k, nxt_id), math.inf):
                dist[(k, nxt_id)] = g2
                heapq.heappush(heap, (g2, k, nxt_id))
    return None if best == math.inf else best


@pytest.mark.parametrize("seed", [485, 7])
def test_astar_matches_an_independent_dijkstra_on_seeded_random_graphs(seed):
    """200 graphs per seed: place goals, coordinate goals, vias and extra lane costs."""
    rng = random.Random(seed)
    compared = 0
    for case in range(200):
        site = _random_map(rng)
        graph = build_graph(site, version=1)
        start = rng.choice(list(graph.arcs))
        s0 = graph.arcs[start].length_m * rng.random()
        extra = {e.id: rng.choice([0.0, 0.0, 3.0]) for e in site.edges}
        via = tuple(rng.sample(sorted(graph.places), rng.randint(0, 2)))
        if case % 2:
            target = rng.choice(sorted(graph.places))
            goal, oracle = Goal(graph.place_xy(target), place=target), dict(place=target)
        else:
            arc = graph.arcs[rng.choice(list(graph.arcs))]
            s_goal = rng.uniform(0.0, arc.length_m)
            goal = Goal(arc.point_at(s_goal)[:2], on_arcs={arc.id: s_goal})
            oracle = dict(on_arcs={arc.id: s_goal})
        found = search(graph, (start, s0), goal, CFG, allowed=lambda a: True, speed=lambda a: a.speed_cap_mps,
                       extra_cost=extra, via=via)
        expect = _textbook(graph, start, s0, via=via, extra=extra, **oracle)
        assert (found is None) == (expect is None), (seed, case)
        if found is not None:
            compared += 1
            assert found[0] == pytest.approx(expect, abs=1e-9), (seed, case)
    assert compared > 80


# ---- (c) golden routes on the imported map_v2_fleet map -----------------------------

@pytest.mark.parametrize(("start_arc", "goal", "edges"), [
    ("ring_s:fwd", "NW", ["ring_s", "ring_e", "ring_n"]),
    ("east:fwd", "SW", ["east", "ring_e", "ring_n", "ring_w"]),
    ("west:rev", "NE", ["west~", "ring_s", "ring_e"]),
    ("ring_n:fwd", "SE", ["ring_n", "ring_w", "ring_s"]),
    ("east:fwd", "SE", ["east"]),
])
def test_golden_routes_on_map_v2_fleet(start_arc, goal, edges):
    graph = build_graph(from_lane_graph(LANE_GRAPH), version=1)
    x, y, tangent = graph.arcs[start_arc].point_at(0.1)
    plan = plan_trip(graph, PlanRequest(1, (x, y, tangent), goal), CFG)
    assert _edges(plan) == edges
    assert plan.places[-1] == goal and plan.actions[-1] == (goal, "stop", 0.0)


# ---- (e) performance ----------------------------------------------------------------

def test_plan_on_a_500_arc_grid_is_within_20_ms_p95():
    size = 12
    places = {f"g{r}_{c}": (float(c), float(r)) for r in range(size) for c in range(size)}
    edges = []
    for r in range(size):
        for c in range(size):
            if c + 1 < size:
                edges.append((f"h{r}_{c}", f"g{r}_{c}", f"g{r}_{c + 1}", True))
            if r + 1 < size:
                edges.append((f"v{r}_{c}", f"g{r}_{c}", f"g{r + 1}_{c}", True))
    graph = build_graph(_map(places, edges), version=1)
    assert len(graph.arcs) >= 500
    request = PlanRequest(1, (0.3, 0.0, 0.0), f"g{size - 1}_{size - 1}")
    plan_trip(graph, request, CFG)  # warm the per-version caches, as the server does on activation
    p95s = []
    for _attempt in range(3):  # a busy host gets two more tries; the budget itself does not move
        times = []
        for _ in range(40):
            began = time.perf_counter()
            plan_trip(graph, request, CFG)
            times.append(time.perf_counter() - began)
        times.sort()
        p95s.append(times[int(0.95 * len(times)) - 1])
        if p95s[-1] <= 0.020:
            break
    assert min(p95s) <= 0.020, p95s


def test_routing_modules_import_only_the_standard_library_and_themselves():
    allowed = {"__future__", "dataclasses", "functools", "heapq", "math", "typing"}
    for path in ROUTING.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert name in allowed or name.startswith("fleet.routing"), f"{path.name} imports {name}"
