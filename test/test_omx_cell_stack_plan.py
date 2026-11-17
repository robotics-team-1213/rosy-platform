"""Goal-driven stacking plan on the real two-arm layout with a fixed reach (no MuJoCo, no IK)."""
from pathlib import Path
import random
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import omx_two_arm_sites as sites  # noqa: E402
from cell_move_order import planning_sites, stack_key  # noqa: E402
from cell_stack_plan import plan_to_goal  # noqa: E402

BOTH = {"arm_a", "arm_b"}
GOAL = {"h1r1": ["A", "B", "C"]}
GOAL_SITES = {"A": "ship-h1r1-l0", "B": "ship-h1r1-l1", "C": "ship-h1r1-l2"}


@pytest.fixture(scope="module")
def layout():
    return sites.Layout()


def can_all(src, dst, here):
    return set(BOTH)


def apply_plan(layout, state, moves, can=can_all):
    """Replay serially; every move must lift a free top, land on a free supported site, and have an arm."""
    cur = dict(state)
    for m in moves:
        c, src, dst = m["cargo_id"], m["source"], m["destination"]
        assert cur[c] == src and m["arms"]
        assert not any(stack_key(layout, s) == stack_key(layout, src) and layout.sites[s].get("layer", 0) > layout.sites[src].get("layer", 0)
                       for s in cur.values() if stack_key(layout, src) != "belt"), "something sits on the source"
        assert dst not in cur.values()
        lay = layout.sites[dst].get("layer", 0)
        assert lay == 0 or layout.stack_at[(layout.sites[dst]["stack"], lay - 1)] in cur.values(), "no support"
        assert set(m["arms"]) <= can(src, dst, {k: v for k, v in cur.items() if k != c})
        cur[c] = dst
    return cur


def reaches(cur, goal_sites=GOAL_SITES):
    return all(cur[c] == s for c, s in goal_sites.items())


def test_at_goal_needs_no_moves(layout):
    assert plan_to_goal(layout, dict(GOAL_SITES), GOAL, can_all) == ([], None)


def test_free_cargo_goes_straight_in_order(layout):
    state = {"A": "tmp-a-1", "B": "tmp-b-1", "D": "tmp-a-2", "C": "tmp-a-2-l1"}
    moves, why = plan_to_goal(layout, state, GOAL, can_all)
    assert why is None and [(m["cargo_id"], m["destination"]) for m in moves] == list(GOAL_SITES.items())
    assert reaches(apply_plan(layout, state, moves))


def test_blocker_parks_then_returns_above_its_support(layout):
    state = {"B": "ship-h1r1-l0", "A": "tmp-a-1", "C": "tmp-a-2"}
    moves, why = plan_to_goal(layout, state, GOAL, can_all)
    assert why is None
    assert [m["cargo_id"] for m in moves] == ["B", "A", "B", "C"]
    assert layout.sites[moves[0]["destination"]]["kind"] == "temp" and stack_key(layout, moves[0]["destination"]) != "h1r1"
    assert moves[1]["destination"] == "ship-h1r1-l0" and moves[2]["destination"] == "ship-h1r1-l1"
    assert reaches(apply_plan(layout, state, moves))


def test_no_temp_space_holds(layout):
    state = {"B": "ship-h1r1-l0", "A": "tmp-a-1", "C": "tmp-a-2"}
    spots = {s for s in planning_sites(layout) if stack_key(layout, s) != "h1r1"}
    assert plan_to_goal(layout, state, GOAL, can_all, avoid=spots) == (None, "NO_BUFFER")


def test_no_arm_holds(layout):
    assert plan_to_goal(layout, {"A": "tmp-a-1", "B": "tmp-b-1", "C": "tmp-a-2"}, GOAL, lambda *a: set()) == (None, "UNREACHABLE")


def test_unknown_site_is_refused(layout):
    assert plan_to_goal(layout, {"A": "nowhere", "B": "tmp-b-1", "C": "tmp-a-2"}, GOAL, can_all) == (None, "UNKNOWN_SITE")
    assert plan_to_goal(layout, {"A": "tmp-a-1", "B": "tmp-b-1", "C": "tmp-a-2"}, {"nope": ["A"]}, can_all) == (None, "UNKNOWN_SITE")


def random_state(layout, rng, cargos):
    names, cur = planning_sites(layout), {}
    for c in cargos:
        free = [s for s in names if s not in cur.values() and (layout.sites[s].get("layer", 0) == 0
                or layout.stack_at[(layout.sites[s]["stack"], layout.sites[s]["layer"] - 1)] in cur.values())]
        cur[c] = rng.choice(free)
    return cur


@pytest.mark.parametrize("seed", range(60))
def test_random_starts_reach_the_goal_and_replan_converges(layout, seed):
    rng = random.Random(seed)
    cargos = ["A", "B", "C", "D", "E"][:rng.randint(3, 5)]
    state = random_state(layout, rng, cargos)
    order = rng.sample(["A", "B", "C"], 3)
    goal = {"h1r1": order}
    want = {c: layout.stack_at[("h1r1", t)] for t, c in enumerate(order)}
    moves, why = plan_to_goal(layout, state, goal, can_all)
    assert why is None, (state, goal)
    assert reaches(apply_plan(layout, state, moves), want)
    k = rng.randint(0, len(moves))
    mid = apply_plan(layout, state, moves[:k])
    again, why = plan_to_goal(layout, mid, goal, can_all)
    assert why is None and reaches(apply_plan(layout, mid, again), want)
