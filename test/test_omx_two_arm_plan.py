"""Arm assignment and schedule for Harbor's moves: one-arm and two-arm modes on the same input. No MuJoCo, no IK (a fixed reach table;
the validator-backed `validator_can` is exercised by the MuJoCo replay)."""
import json
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
    """A fixed reach table: ship hold 1 and belt by both, plate a by arm_a, plate b lanes 1-2 by arm_b (and their second tier, the place the stern bay used to add)."""
    table = {s: set(BOTH) for s in plan.planning_sites(layout) if layout.sites[s]["kind"] in ("ship", "belt")}
    table.update({f"tmp-a-{i}": {"arm_a"} for i in (1, 2, 3)})
    table.update({"tmp-b-1": {"arm_b"}, "tmp-b-2": {"arm_b"}, "tmp-b-3": set(), "tmp-b-1-l1": {"arm_b"}, "tmp-b-2-l1": {"arm_b"}})
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
    assert moves[0]["destination"] == "tmp-b-1"  # row 2 is arm_b's side: its own plate first
    assert moves[2]["destination"].startswith("tmp-a")  # the outbound place is a lane: arm_b's plate is used up, so arm_a's
    assert [m["destination"] for m in moves[3:]] == ["ship-h1r2-l0", "ship-h1r2-l1"]  # down into the freed level, old order kept


def test_order_source_and_harbor_permutation(layout, reach):
    state = {c: s for c, s, _ in layout.plan_order()}
    request = {"cargo_id": "bar-3"}
    rule, why = plan.resolve_order({}, layout, state, request, reach)
    assert why is None and rule["order_source"] == "rosy_r"
    requested = rule["moves"]
    supplied = list(requested)
    chosen, why = plan.resolve_order({"requested_moves": requested, "harbor_order": supplied},
                                     layout, state, request, reach)
    assert why is None and chosen == {"moves": supplied, "order_source": "harbor"}
    with pytest.raises(ValueError, match="exactly"):
        plan.resolve_order({"requested_moves": requested, "harbor_order": supplied[:-1]},
                           layout, state, request, reach)
    with pytest.raises(ValueError, match="not executable"):
        plan.resolve_order({"requested_moves": requested, "harbor_order": list(reversed(supplied))},
                           layout, state, request, reach)


def test_shadow_order_never_changes_execution(layout, reach, caplog):
    state = {c: s for c, s, _ in layout.plan_order()}
    expected, _ = plan.resolve_order({}, layout, state, {"cargo_id": "bar-3"}, reach)
    with caplog.at_level("INFO"):
        actual, _ = plan.resolve_order({}, layout, state, {"cargo_id": "bar-3"}, reach,
                                       suggester=lambda _request, _state: [])
    assert actual == expected
    assert "agreement=False" in caplog.text
    moves, holds = plan.plan_outbound(layout, BOTH, reach)
    assert not holds and {move["order_source"] for move in moves} == {"rosy_r"}
    rows, _ = plan.schedule(layout, moves, ("arm_a", "arm_b"))
    assert {row["order_source"] for row in rows} == {"rosy_r"}


def test_one_arm_without_a_temporary_place_in_reach_holds(layout, reach):
    """arm_b alone has one free lane of its plate and its second tier: no request finds a lane left for its target once its blockers are
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


def test_two_arms_rearrange_both_outer_rows_at_once_each_reversed(layout, reach):
    """재배치: each outer row goes out top first and comes back with its bottom in place and the two above swapped; the two rows run on
    their own sides at the same time."""
    full = {c: s for c, s, _ in layout.plan_order()}
    moves, holds = plan.plan_outbound(layout, ("arm_a", "arm_b"), reach, reorder=True)
    assert not holds and len(moves) == 12 and {m["phase_label"] for m in moves} == {"재취급", "복귀"}
    end = dict(full, **{m["cargo_id"]: m["destination"] for m in moves})
    for row in (0, 2):
        old = sorted((c for c, s in full.items() if layout.sites[s]["row"] == row), key=lambda c: layout.sites[full[c]]["layer"])
        assert sorted(old, key=lambda c: layout.sites[end[c]]["layer"]) == old[:1] + old[:0:-1]
    rows, extra = plan.schedule(layout, moves, ("arm_a", "arm_b"))
    assert not extra
    zones_never_double_held(rows)
    assert plan.metrics(rows, extra, ("arm_a", "arm_b"))["overlap_s"] > 0 and {r["arm"] for r in rows} == BOTH


def test_a_move_no_arm_of_the_mode_reaches_is_counted_not_moved(layout, reach):
    moves = [dict(cargo_id="bar-1", source="ship-h1r1-l0", destination="tmp-a-1", primary_arm="A", alternate_arms=[], phase_label="재취급", arms=["arm_a"])]
    rows, extra = plan.schedule(layout, moves, ("arm_b",))
    assert not rows and extra[0]["cargo_id"] == "bar-1"


def test_the_stern_bay_is_not_a_place(layout):
    """Site map decision 2026-11-17: the stern bay is berth geometry only; outbound is the separate stand (r05 chute), not simulated yet."""
    assert "ship-stern-l0" not in layout.sites and not any(v.get("stack") == "stern" for v in layout.sites.values())
    assert not any(v["kind"] == "outbound" for v in layout.sites.values())


def test_the_validator_gives_the_bottom_of_an_outer_row_to_the_far_arm(layout):
    """Reach is not enough: the near arm's wrist hits the standing middle row (MuJoCo replay 2026-11-08, -1 to -5 mm), the far arm clears it."""
    full = {c: s for c, s, _ in layout.plan_order()}
    here = {c: s for c, s in full.items() if layout.sites[s]["row"] != 0}  # row 0 taken down to bar-2, the middle row standing three high
    assert plan.validator_can(layout)(full["bar-2"], "tmp-b-1", here) == {"arm_b"}


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


def test_a_full_bottom_tier_sends_blockers_up_a_lane_before_onto_the_ship(layout):
    """Harbor's temporary places: free bottom tiers, then a tier on an occupied lane, then the ship; the outbound place is a bottom tier."""
    bottoms = {s for s in plan.planning_sites(layout) if layout.sites[s]["kind"] == "temp" and layout.sites[s]["layer"] == 0}
    spots = plan.temp_spots(layout, bottoms)
    assert layout.sites[spots[0]]["kind"] == "temp" and layout.sites[spots[0]]["layer"] == 1
    assert all(layout.sites[s]["kind"] == "ship" for s in spots[spots.index(next(s for s in spots if layout.sites[s]["kind"] == "ship")):])


def test_tier_by_tier_stack_and_cell_stack_schedule_and_replay(layout):
    """1단 (t1), 2단 (t2), and 3단 (t3) each plan 3 moves on top of the lower tiers, from the belt or from the cell's plates."""
    can = plan.validator_can(layout)
    for scenario in ("stack", "cell-stack"):
        for tier in (1, 2, 3):
            res = plan.compare(layout, scenario, can, tier=tier)
            key = f"{scenario}-t{tier}"
            assert res["two-arm"][key]["moves"] == 3 and res["two-arm"][key]["extra_transports"] == 0
            replays = plan.replay_tasks(layout, res)
            task = replays[f"{key}-two-arm"]
            assert len(task["steps"]) == 3 and all(layout.sites[s["to"]]["layer"] == tier - 1 for s in task["steps"])
            assert sum(1 for s in task["start"].values() if layout.sites[s]["kind"] == "ship") == 3 * (tier - 1)


def test_outbound_and_rearrange_replay_json_carry_after_zones_and_disjoint_overlap(tmp_path, layout):
    """compare --scenario all --replay-dir writes two-arm replay JSON with after, zones, both arms, and swept-clear concurrent pairs."""
    assert plan.main(["compare", "--scenario", "all", "--replay-dir", str(tmp_path)]) == 0
    for scenario in ("outbound", "rearrange"):
        data = json.loads((tmp_path / f"{scenario}-two-arm.json").read_text(encoding="utf-8"))
        steps = data["steps"]
        assert steps and {s["arm"] for s in steps} == BOTH
        assert all(isinstance(s["after"], list) and len(s["zones"]) == 2 and s["zones"][0] and s["zones"][1] for s in steps)
        anc, here, poses = {}, dict(data["start"]), {}
        for s in sorted(steps, key=lambda st: int(st["id"][1:])):
            anc[s["id"]] = set(s["after"]).union(*(anc.get(p, set()) for p in s["after"]))
            here_step = {k: v for k, v in here.items() if k != s["container"]}
            poses[s["id"]] = plan.step_swept_poses(layout, s["arm"], s["from"], s["to"], here_step)
            here[s["container"]] = s["to"]
        windows, held = [], []
        for s in steps:
            t_pick, t_carry, t_place = plan.duration(layout, s["from"], s["to"])
            t0 = s["planned_start_s"]
            windows.append((s["id"], s["arm"], t0, t0 + t_pick + t_carry + t_place))
            held.extend((s["id"], z, t0, t0 + t_pick + t_carry) for z in s["zones"][0])
            held.extend((s["id"], z, t0 + t_pick, t0 + t_pick + t_carry + t_place) for z in s["zones"][1])
        overlaps = [(m1, m2) for i, (m1, a1, s1, e1) in enumerate(windows) for m2, a2, s2, e2 in windows[i + 1:]
                    if a1 != a2 and m1 not in anc[m2] and m2 not in anc[m1] and s1 < e2 - 0.01 and s2 < e1 - 0.01]
        if scenario == "rearrange":
            assert overlaps
        for m1, m2 in overlaps:
            assert plan.sweeps_clear(poses[m1], poses[m2], ta=dict((w[0], w[2]) for w in windows)[m1],
                                     tb=dict((w[0], w[2]) for w in windows)[m2], slack_s=plan.SWEEP_SLACK_S), (scenario, m1, m2)
        for i, (m1, z1, s1, e1) in enumerate(held):
            for m2, z2, s2, e2 in held[i + 1:]:
                if m1 != m2 and m1 not in anc[m2] and m2 not in anc[m1]:
                    assert not (z1 == z2 and s1 < e2 - 0.01 and s2 < e1 - 0.01), (scenario, m1, m2, z1, s1, e1, s2, e2)


def test_disjoint_zones_with_crossing_sweeps_are_not_scheduled_or_started_together(layout):
    """m5/m7-like pair (zones [['a'],['a']] and [['b'],['b']], crossing sweeps) must be serialised by both planner and teacher."""
    import math
    import numpy as np
    import omx_two_arm_teacher_stages as stages

    here = {
        "bar-1": "ship-h1r1-l0", "bar-2": "ship-h1r0-l0", "bar-3": "ship-h1r2-l0",
        "bar-4": "ship-h1r1-l1", "bar-5": "tmp-a-2", "bar-6": "ship-h1r2-l1",
        "bar-7": "ship-h1r1-l2", "bar-8": "ship-h1r0-l1", "bar-9": "tmp-b-2",
    }
    moves = [
        dict(cargo_id="bar-8", source="ship-h1r0-l1", destination="tmp-a-2", primary_arm="A", alternate_arms=[], phase_label="재취급", arms=["arm_a"]),
        dict(cargo_id="bar-6", source="ship-h1r2-l1", destination="tmp-b-3", primary_arm="B", alternate_arms=[], phase_label="재취급", arms=["arm_b"]),
    ]
    rows, extra = plan.schedule(layout, moves, ("arm_a", "arm_b"), start=here)
    assert not extra and len(rows) == 2
    pa = plan.step_swept_poses(layout, "arm_a", "ship-h1r0-l1", "tmp-a-2", here)
    assert pa[0][0] == 0.0 and pa[6][0] == 2.5 and pa[-1][0] > sum(plan.duration(layout, "ship-h1r0-l1", "tmp-a-2"))
    assert len(pa[35][1]) == 4 and pa[35][1][3][2] == pytest.approx(math.hypot(*layout.box[:2]) / 2)
    assert rows[1]["start"] > 0.0 and not plan.sweeps_clear(
        pa,
        plan.step_swept_poses(layout, "arm_b", "ship-h1r2-l1", "tmp-b-3", here),
        ta=0.0, tb=0.0, slack_s=plan.SWEEP_SLACK_S,
    )

    class FakeTeacher:
        def __init__(self, L):
            self.layout = L
            for a in L.sim_arms.values():
                a.wait = a.home.copy()

        def step_gen(self, data, step, here_step, ctx):
            for _ in range(3):
                yield np.zeros(6)
            return dict(step=step["id"], result="pass")

        def frame(self, data, targets, label, ctxs=None):
            pass

        def off_stand(self, data, step, here_now):
            pass

    task = {"steps": [
        {"id": "m5", "container": "bar-5", "from": "tmp-a-2", "to": "ship-h1r0-l2", "arm": "arm_a", "after": [], "after_pick": [], "zones": [["a"], ["a"]]},
        {"id": "m7", "container": "bar-6", "from": "ship-h1r2-l1", "to": "tmp-b-3", "arm": "arm_b", "after": [], "after_pick": [], "zones": [["b"], ["b"]]},
    ]}
    _, timing, stop_reason, _ = stages.run_concurrent_steps(FakeTeacher(layout), None, task, dict(here))
    assert stop_reason is None
    assert timing["m7"]["start_s"] >= timing["m5"]["end_s"]
