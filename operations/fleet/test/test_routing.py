"""D-485/D-486 7 (a)(b)(c)(e): the lane-state A* planner on the D-484 site map."""

from __future__ import annotations

import ast
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
    assert len(plans) == 1


def test_routing_config_rejects_out_of_range_and_unknown_keys():
    assert RoutingConfig.from_mapping(None) == RoutingConfig()
    for bad in ({"turn_cost_s": -1}, {"straight_max_deg": 140}, {"heading_tol_deg": 0},
                {"snap_width_factor": 0}, {"turn_cost": 1}, {"uturn_cost_s": True}):
        with pytest.raises(ValueError):
            RoutingConfig.from_mapping(bad)
    assert transition_cost(180.0, "junction", CFG) is None


# ---- (a) admissible heuristic: A* cost == Dijkstra cost ------------------------------

def _random_map(rng: random.Random) -> SiteMap:
    n = rng.randint(4, 12)
    places = {f"p{i}": (rng.uniform(-5, 5), rng.uniform(-5, 5),
                        "turnaround" if rng.random() < 0.2 else "junction") for i in range(n)}
    ids = sorted(places)
    edges = []
    for k in range(rng.randint(n, 3 * n)):
        a, b = rng.sample(ids, 2)
        (ax, ay, _), (bx, by, _) = places[a], places[b]
        bend = (ax + bx) / 2 + rng.uniform(-1, 1), (ay + by) / 2 + rng.uniform(-1, 1)
        edges.append({"id": f"e{k}", "from": a, "to": b, "polyline": [(ax, ay), bend, (bx, by)],
                      "direction": rng.choice(["one_way", "two_way"]), "width_m": 0.3,
                      "speed_cap_mps": rng.choice([0.1, 0.2, 0.5])})
    return SiteMap(places=[{"id": p, "name": p, "x": v[0], "y": v[1], "kind": v[2]} for p, v in places.items()],
                   edges=edges)


def test_astar_matches_dijkstra_on_200_seeded_random_graphs():
    rng = random.Random(485)
    compared = 0
    for _ in range(200):
        site = _random_map(rng)
        graph = build_graph(site, version=1)
        start = rng.choice(list(graph.arcs))
        arc = graph.arcs[start]
        target = rng.choice(sorted(graph.places))
        goal = Goal(graph.place_xy(target), place=target)
        kw = dict(allowed=lambda a: True, speed=lambda a: a.speed_cap_mps)
        fast = search(graph, (start, arc.length_m / 3), goal, CFG, **kw)
        slow = search(graph, (start, arc.length_m / 3), goal, CFG, use_heuristic=False, **kw)
        assert (fast is None) == (slow is None)
        if fast is not None:
            compared += 1
            assert fast[0] == pytest.approx(slow[0], abs=1e-9)
    assert compared > 100


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
    times = []
    for _ in range(40):
        began = time.perf_counter()
        plan_trip(graph, PlanRequest(1, (0.3, 0.0, 0.0), f"g{size - 1}_{size - 1}"), CFG)
        times.append(time.perf_counter() - began)
    times.sort()
    assert times[int(0.95 * len(times)) - 1] <= 0.020, times[-5:]


def test_routing_modules_import_only_the_standard_library_and_themselves():
    allowed = {"__future__", "dataclasses", "functools", "heapq", "math", "typing"}
    for path in ROUTING.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert name in allowed or name.startswith("fleet.routing"), f"{path.name} imports {name}"
