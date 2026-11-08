"""Arm assignment and schedule for Harbor's moves: one-arm and two-arm modes on the same input. No MuJoCo, no IK (a fixed reach table;
the validator-backed `validator_can` is exercised by the MuJoCo replay)."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_plan as plan  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402

BOTH = {"arm_a", "arm_b"}


@pytest.fixture(scope="module")
def layout():
    return sites.Layout()


@pytest.fixture(scope="module")
def reach(layout):
    """A fixed reach table: ship hold 1, belt and stern bay by both, plate a by arm_a, plate b lanes 1-2 by arm_b (lane 1 is left out
    anyway: plate v11 on its bridge puts it under the estimated hull)."""
    table = {s: set(BOTH) for s in plan.planning_sites(layout) if layout.sites[s]["kind"] in ("ship", "belt")}
    table.update({f"tmp-a-{i}": {"arm_a"} for i in (1, 2, 3)})
    table.update({"tmp-b-1": {"arm_b"}, "tmp-b-2": {"arm_b"}, "tmp-b-3": set()})
    return plan.table_can(table)


def zones_never_double_held(rows):
    """No zone is held by two moves at once: source zones through the carry, target zones from the lift."""
    held = [(r["move"], z, r["start"], r["carry_end"]) for r in rows for z in r["zones"][0]] + \
           [(r["move"], z, r["pick_end"], r["end"]) for r in rows for z in r["zones"][1]]
    for i, (m, z, s, e) in enumerate(held):
        for m2, z2, s2, e2 in held[i + 1:]:
            assert m == m2 or not (z == z2 and s < e2 and s2 < e), (m, m2, z, s, e, s2, e2)


def test_two_arms_take_turns_at_the_conveyor_and_finish_sooner(layout, reach):
    moves = plan.stack_moves(layout, reach)
    one, _ = plan.schedule(layout, moves, ("arm_b",))
    two, _ = plan.schedule(layout, moves, ("arm_a", "arm_b"))
    assert {r["arm"] for r in two} == BOTH and max(r["end"] for r in two) < max(r["end"] for r in one)
    zones_never_double_held(two)
    picks = sorted(r["pick_end"] for r in two)  # the conveyor hands over one at a time, in order
    assert [r["cargo_id"] for r in sorted(two, key=lambda r: r["pick_end"])] == [m["cargo_id"] for m in moves]
    assert all(b - a >= plan.TIMING["belt_gap_s"] - 1e-6 for a, b in zip(picks, picks[1:]))


def test_a_container_waits_for_the_one_under_it(layout, reach):
    rows, _ = plan.schedule(layout, plan.stack_moves(layout, reach), ("arm_a", "arm_b"))
    end = {r["destination"]: r["end"] for r in rows}
    for r in rows:
        s = layout.sites[r["destination"]]
        if s["layer"]:
            assert r["start"] >= end[f"ship-{s['stack']}-l{s['layer'] - 1}"]


def test_harbor_order_rehandle_outbound_restore(layout, reach):
    state = {c: s for c, s, _ in layout.plan_order()}
    moves, why = plan.harbor_moves(layout, state, dict(cargo_id="bar-3"), reach)  # bottom of row 2 under bar-6 and bar-9
    assert why is None
    assert [(m["cargo_id"], m["phase_label"]) for m in moves] == [("bar-9", "재취급"), ("bar-6", "재취급"), ("bar-3", "반출"), ("bar-6", "복귀"), ("bar-9", "복귀")]
    assert moves[0]["destination"] == "tmp-b-2"  # row 2 is arm_b's side: its own plate first (lane 1 lies under the hull)
    assert moves[2]["destination"].startswith("tmp-a")  # the outbound place is a lane: arm_b's plate is used up, so arm_a's
    assert [m["destination"] for m in moves[3:]] == ["ship-h1r2-l0", "ship-h1r2-l1"]  # down into the freed level, old order kept


def test_one_arm_without_a_temporary_place_in_reach_holds(layout, reach):
    """arm_b alone has one free lane of its plate and the stern bay: no request finds a lane left for its target once its blockers are
    out (a person or a Pinky trip)."""
    moves, holds = plan.plan_outbound(layout, ("arm_b",), reach)
    assert holds and all(h["reason"] == "NO_STAND_IN_REACH" for h in holds)
    both, none = plan.plan_outbound(layout, ("arm_a", "arm_b"), reach)
    assert not none and len(both) == 10


def test_two_requests_overlap_on_their_own_sides_and_each_target_leaves_from_a_lane(layout, reach):
    moves, _ = plan.plan_outbound(layout, ("arm_a", "arm_b"), reach)
    rows, extra = plan.schedule(layout, moves, ("arm_a", "arm_b"))
    assert not extra
    zones_never_double_held(rows)
    m = plan.metrics(rows, extra, ("arm_a", "arm_b"))
    assert m["overlap_s"] > 0 and m["moves_per_arm"]["arm_a"] and m["moves_per_arm"]["arm_b"]
    out = [r for r in rows if r["phase"] == "반출"]
    assert len(out) == 2 and all(r["destination"].startswith("tmp-") for r in out)
    steps = plan.as_steps(rows)
    assert sorted(s["id"] for s in steps if s.get("outbound")) == sorted(f"m{r['move']}" for r in out)  # Pinky clears exactly these


def test_a_move_no_arm_of_the_mode_reaches_is_counted_not_moved(layout, reach):
    moves = [dict(cargo_id="bar-1", source="ship-h1r1-l0", destination="tmp-a-1", primary_arm="A", alternate_arms=[], phase_label="재취급", arms=["arm_a"])]
    rows, extra = plan.schedule(layout, moves, ("arm_b",))
    assert not rows and extra[0]["cargo_id"] == "bar-1"


def test_the_stern_bay_is_a_low_ship_place_across_the_beam(layout):
    """The outbound place is a temporary lane (set page 23233175, 2026-11-08); the empty stern bay is one more place on the ship."""
    s = layout.sites["ship-stern-l0"]
    assert s["kind"] == "ship" and s["layer"] == 0 and s["yaw"] == pytest.approx(1.5708, abs=1e-4)
    assert "ship-stern-l0" in plan.planning_sites(layout) and not any(v["kind"] == "outbound" for v in layout.sites.values())
    assert s["xy"][0] == pytest.approx(layout.choices["ship_stern_x_m"] - .025)


def test_the_validator_gives_the_bottom_of_an_outer_row_to_the_far_arm(layout):
    """Reach is not enough: the near arm's wrist hits the standing middle row (MuJoCo replay 2026-11-08, -1 to -5 mm), the far arm clears it."""
    full = {c: s for c, s, _ in layout.plan_order()}
    here = {c: s for c, s in full.items() if layout.sites[s]["row"] != 0}  # row 0 taken down to bar-2, the middle row standing three high
    assert plan.validator_can(layout)(full["bar-2"], "ship-stern-l0", here) == {"arm_b"}


def test_a_concurrent_replay_carries_order_conveyor_and_zones(layout, reach):
    tasks = plan.replay_tasks(layout, plan.compare(layout, "stack", reach))
    steps = {s["id"]: s for s in tasks["stack-two-arm"]["steps"]}
    belt = sorted(steps.values(), key=lambda s: int(s["id"][1:]))
    assert all(b["after_pick"] == [a["id"]] for a, b in zip(belt, belt[1:]))  # the conveyor hands over one at a time
    for s in steps.values():
        layer = layout.sites[s["to"]]["layer"]
        if layer:  # waits for the container it stands on
            under = next(o for o in steps.values() if o["to"] == f"ship-{layout.sites[s['to']]['stack']}-l{layer - 1}")
            assert under["id"] in s["after"]
        assert len(s["zones"]) == 2 and s["zones"][0] and s["zones"][1]
    assert {s["arm"] for s in steps.values()} == BOTH
