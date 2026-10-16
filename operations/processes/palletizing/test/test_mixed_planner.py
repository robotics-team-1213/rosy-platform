"""Mixed planner (D-781 §3-5): every Step obeys the rules, checked by an independent checker.

The checker below rebuilds each box from the Step output (pose, sku, pallet) and the recipe
only. It does not call the planner's rule module, so a bug there cannot hide itself.
"""

from __future__ import annotations

import math

import pytest
import yaml

from rosy.processes.palletizing.mixed_cell import (
    CellPose,
    Finger,
    WorkcellError,
    annulus_reach,
    workcell_from_dict,
)
from rosy.processes.palletizing.mixed_plan import PlanError
from rosy.processes.palletizing.mixed_planner import PLANNER_VERSION, plan_mixed
from rosy.processes.palletizing.mixed_recipe import load_mixed_recipe

TOL = 1e-7


def foam(sku, length, width, height, mass, depth, qty, orientation="yaw_only", top_kg=0.10):
    return {"sku": sku, "length": length, "width": width, "height": height, "mass_kg": mass,
            "grasp_depth": depth, "quantity": qty, "orientation": orientation, "max_load_on_top_kg": top_kg}


def recipe_text(items, length=0.20, width=0.15, max_height=0.07, max_load=0.5, yaws=(0, 90)):
    return yaml.safe_dump({
        "schema": "rosy_cell.recipe/3", "name": "mixed", "mode": "palletize", "items": items,
        "pallets": [{"id": "A", "frame": "pallet_a", "length": length, "width": width,
                     "max_stack_height": max_height, "max_load_kg": max_load}],
        "pick_stations": ["infeed_left", "infeed_right"], "gap": 0.008,
        "stability": {"rule": "support_ratio_v1", "max_height_to_base_ratio": 1.5},
        "planner": {"candidates": "extreme_points", "yaw_deg": list(yaws), "allow_push": False},
    })


MIXED = [foam("foam_40x30x30", 0.040, 0.030, 0.030, 0.020, 0.015, 4),
         foam("foam_30x20x20", 0.030, 0.020, 0.020, 0.010, 0.010, 4, top_kg=0.05),
         foam("foam_60x40x20", 0.060, 0.040, 0.020, 0.030, 0.010, 2, orientation="upright_fixed")]
# A small single-arm pallet that forces a second and third level.
STACKED = [foam("foam_40x30x30", 0.040, 0.030, 0.030, 0.020, 0.015, 6),
           foam("foam_30x20x20", 0.030, 0.020, 0.020, 0.010, 0.010, 2, top_kg=0.05),
           foam("foam_60x40x20", 0.060, 0.040, 0.020, 0.030, 0.010, 2, orientation="upright_fixed")]

TWO_ARMS = {
    "arms": [{"role": "left", "base_in_cell": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "zone_id": "left_half"},
             {"role": "right", "base_in_cell": {"x": 0.33, "y": 0.0, "yaw": math.pi}, "zone_id": "right_half"}],
    "zones": [{"zone_id": "left_half", "x_min": 0.0, "y_min": -0.2, "x_max": 0.145, "y_max": 0.2},
              {"zone_id": "shared_band", "x_min": 0.145, "y_min": -0.2, "x_max": 0.185, "y_max": 0.2},
              {"zone_id": "right_half", "x_min": 0.185, "y_min": -0.2, "x_max": 0.33, "y_max": 0.2}],
    "pallet_origins": {"A": [0.065, -0.075, 0.0]},
    "stations": {"infeed_left": [0.0, 0.16, 0.0], "infeed_right": [0.33, 0.16, 0.0]},
}
ONE_ARM = {
    "arms": [{"role": "solo", "base_in_cell": {"x": 0.0, "y": 0.0}}],
    "pallet_origins": {"A": [0.10, -0.05, 0.0]},
    "stations": {"infeed_left": [0.0, 0.16, 0.0], "infeed_right": [0.0, -0.16, 0.0]},
}


def two_arm_plan():
    cell = workcell_from_dict(TWO_ARMS)
    reach = annulus_reach(cell, 0.05, 0.25)
    recipe = load_mixed_recipe(recipe_text(MIXED))
    return recipe, cell, reach, plan_mixed(recipe, cell, reach)


def stacked_plan():
    recipe = load_mixed_recipe(recipe_text(STACKED, length=0.12, width=0.10))
    cell = workcell_from_dict(ONE_ARM)
    reach = annulus_reach(cell, 0.05, 0.30)
    return recipe, cell, reach, plan_mixed(recipe, cell, reach)


# ---- independent checker -------------------------------------------------------------------

def _boxes(recipe, cell, plan):
    items = {i.sku: i for i in recipe.items}
    out = []
    for s in plan.steps:
        it = items[s.sku]
        ox, oy, oz = cell.pallet_origins[s.pallet_id]
        yaw = round(math.degrees(s.pose_cell.yaw))
        assert yaw in recipe.planner.yaw_deg and yaw in ((0,) if it.orientation == "upright_fixed" else (0, 90))
        lx, ly = (it.length, it.width) if yaw == 0 else (it.width, it.length)
        cx, cy = s.pose_cell.x - ox, s.pose_cell.y - oy
        top = s.pose_cell.z - oz + it.grasp_depth
        out.append({"i": s.index, "pallet": s.pallet_id, "x0": cx - lx / 2, "x1": cx + lx / 2, "y0": cy - ly / 2,
                    "y1": cy + ly / 2, "z0": top - it.height, "z1": top, "yaw": yaw, "item": it})
    return out


def _area(a, b):
    dx = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    dy = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
    return dx * dy if dx > TOL and dy > TOL else 0.0


def _strips(b, finger):
    out, half = finger.opening_margin_m + finger.thickness_m, finger.breadth_m / 2
    cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
    if b["yaw"] == 0:  # grasped width along y
        return [{"x0": cx - half, "x1": cx + half, "y0": b["y0"] - out, "y1": b["y0"]},
                {"x0": cx - half, "x1": cx + half, "y0": b["y1"], "y1": b["y1"] + out}]
    return [{"x0": b["x0"] - out, "x1": b["x0"], "y0": cy - half, "y1": cy + half},
            {"x0": b["x1"], "x1": b["x1"] + out, "y0": cy - half, "y1": cy + half}]


def _ancestors(steps):
    anc = {}
    for s in steps:
        anc[s.index] = set(s.depends_on).union(*(anc[d] for d in s.depends_on))
    return anc


def check_plan(recipe, cell, reach, plan):
    """Assert D-781 §3 rules 1-5 and the §4 ordering for every Step. Returns the boxes."""
    boxes = _boxes(recipe, cell, plan)
    slot = {s.id: s.pallet for s in recipe.pallets}
    finger = cell.finger
    mass = {}
    counts = {}
    for s in plan.steps:
        counts[s.sku] = counts.get(s.sku, 0) + 1
    assert counts == {i.sku: i.quantity for i in recipe.items}
    for s in plan.steps:
        assert all(d < s.index for d in s.depends_on), "dependency on a later step (cycle risk)"
    anc = _ancestors(plan.steps)
    for j, b in enumerate(boxes):
        p, it, step = slot[b["pallet"]], b["item"], plan.steps[j]
        earlier = [a for a in boxes[:j] if a["pallet"] == b["pallet"]]
        # rule 1: geometry
        assert b["x0"] >= -TOL and b["y0"] >= -TOL and b["x1"] <= p.length + TOL and b["y1"] <= p.width + TOL
        assert b["z1"] <= p.max_stack_height + TOL
        mass[b["pallet"]] = mass.get(b["pallet"], 0.0) + it.mass_kg
        assert mass[b["pallet"]] <= p.max_load_kg + 1e-12
        for a in earlier:
            if a["z0"] < b["z1"] - TOL and a["z1"] > b["z0"] + TOL:
                sep = max(a["x0"] - b["x1"], b["x0"] - a["x1"], a["y0"] - b["y1"], b["y0"] - a["y1"])
                assert sep >= recipe.gap - TOL, f"step {j} closer than gap to step {a['i']}"
        # rule 2: support_ratio_v1 and height/base ratio
        assert it.height <= recipe.stability.max_height_to_base_ratio * min(it.length, it.width) + TOL
        sup = [a for a in earlier if abs(a["z1"] - b["z0"]) <= TOL and _area(a, b) > 0]
        if b["z0"] > TOL:
            assert sup, f"step {j} floats"
            ratio = sum(_area(a, b) for a in sup) / ((b["x1"] - b["x0"]) * (b["y1"] - b["y0"]))
            corners = sum(any(a["x0"] - TOL <= cx <= a["x1"] + TOL and a["y0"] - TOL <= cy <= a["y1"] + TOL
                              for a in sup)
                          for cx in (b["x0"], b["x1"]) for cy in (b["y0"], b["y1"]))
            assert (ratio > 0.60 and corners == 4) or (ratio > 0.80 and corners >= 3) or ratio > 0.95
        else:
            assert abs(b["z0"]) <= TOL
        # rule 3: finger strips and the column above are free of earlier boxes when this one goes down
        low = b["z1"] - it.grasp_depth - finger.overhang_m
        assert low >= b["z0"] - TOL
        for a in earlier:
            assert not (_area(a, b) > 0 and a["z1"] > b["z0"] + TOL), f"step {j} lowered into step {a['i']}"
            assert not any(_area(a, r) > 0 and a["z1"] > low + TOL for r in _strips(b, finger)), \
                f"finger of step {j} hits step {a['i']}"
        # §4: support and finger relations are kept by depends_on
        for a in sup:
            assert a["i"] in anc[j], f"step {j} does not wait for its support {a['i']}"
        for a in earlier:
            a_low = a["z1"] - a["item"].grasp_depth - finger.overhang_m
            if any(_area(b, r) > 0 and b["z1"] > a_low + TOL for r in _strips(a, finger)):
                assert a["i"] in anc[j], f"step {j} sits in finger room of {a['i']} without waiting"
        # rule 4: reach, zone, alternates, station
        assert reach(step.arm, step.pose_cell)
        for role in step.alternates:
            assert reach(role, step.pose_cell)
        others = {a.role for a in cell.arms} - {step.arm} - set(step.alternates)
        stations_of = {r: [n for n in recipe.pick_stations if reach(r, CellPose(*cell.stations[n], 0.0))]
                       for r in {a.role for a in cell.arms}}
        assert not any(reach(r, step.pose_cell) and stations_of[r] for r in others)
        assert step.station in stations_of[step.arm]
        if cell.zones:
            zone = next(z for z in cell.zones if z.zone_id == step.zone)
            ox, oy, _ = cell.pallet_origins[b["pallet"]]
            for r in [b, *_strips(b, finger)]:
                assert zone.x_min - TOL <= r["x0"] + ox and r["x1"] + ox <= zone.x_max + TOL
                assert zone.y_min - TOL <= r["y0"] + oy and r["y1"] + oy <= zone.y_max + TOL
            if step.zone != "shared_band":
                assert cell.arm(step.arm).zone_id == step.zone
        assert step.role == "place" and step.coupling == "independent"
        # rule 5: carry height clears everything placed so far plus the held item
        oz = cell.pallet_origins[b["pallet"]][2]
        tops = [cell.pallet_origins[a["pallet"]][2] + a["z1"] for a in boxes[:j]] + [oz]
        hang = max(it.height - it.grasp_depth, finger.overhang_m)
        assert step.carry_z >= max(tops) + hang + cell.approach_clearance_m - TOL
    # load on top: every box carries no more than its limit (area-proportional share downwards)
    carried = {b["i"]: 0.0 for b in boxes}
    for b in sorted(boxes, key=lambda b: (-b["z0"], b["i"])):
        sup = [a for a in boxes if a is not b and a["pallet"] == b["pallet"] and abs(a["z1"] - b["z0"]) <= TOL
               and _area(a, b) > 0 and b["z0"] > TOL]
        total = sum(_area(a, b) for a in sup)
        for a in sup:
            carried[a["i"]] += (b["item"].mass_kg + carried[b["i"]]) * _area(a, b) / total
    for b in boxes:
        assert carried[b["i"]] <= b["item"].max_load_on_top_kg + 1e-12
    # feed order lists each Step once, under its station, in Step order
    listed = [(i, sku, st) for st, entries in plan.feed_order.items() for i, sku in entries]
    assert sorted(listed) == sorted((s.index, s.sku, s.station) for s in plan.steps)
    for entries in plan.feed_order.values():
        assert [i for i, _ in entries] == sorted(i for i, _ in entries)
    return boxes


# ---- tests ---------------------------------------------------------------------------------

def test_two_arm_plan_obeys_every_rule():
    recipe, cell, reach, plan = two_arm_plan()
    assert plan.planner_version == PLANNER_VERSION and plan.recipe_hash == recipe.content_hash
    check_plan(recipe, cell, reach, plan)


def test_stacked_single_arm_plan_obeys_every_rule_and_stacks():
    recipe, cell, reach, plan = stacked_plan()
    boxes = check_plan(recipe, cell, reach, plan)
    assert max(b["z0"] for b in boxes) > 0.04, "the fixture should force a third level"
    assert any(s.depends_on for s in plan.steps)


def test_same_input_gives_identical_plan():
    first = two_arm_plan()[3]
    second = two_arm_plan()[3]
    assert first.to_dict() == second.to_dict()
    assert first.digest == second.digest
    assert stacked_plan()[3].digest == stacked_plan()[3].digest


def test_plan_digest_follows_recipe_content():
    _, cell, reach, plan = two_arm_plan()
    items = [dict(MIXED[0], quantity=3), *MIXED[1:]]
    other = plan_mixed(load_mixed_recipe(recipe_text(items)), cell, reach)
    assert other.digest != plan.digest and other.recipe_hash != plan.recipe_hash


def test_two_arm_plan_has_concurrent_steps_in_different_zones():
    _, cell, _, plan = two_arm_plan()
    anc = _ancestors(plan.steps)
    fixed = [s for s in plan.steps if s.zone in ("left_half", "right_half")]
    pairs = [(a.index, b.index) for a in fixed for b in fixed
             if a.index < b.index and a.zone != b.zone and a.index not in anc[b.index]]
    assert pairs, "expected at least one left/right pair with no dependency"
    assert {s.arm for s in plan.steps} == {"left", "right"}
    for s in plan.steps:
        if s.zone == "left_half":
            assert s.arm == "left"
        if s.zone == "right_half":
            assert s.arm == "right"


def test_same_arm_steps_keep_reference_order():
    _, _, _, plan = two_arm_plan()
    for role in ("left", "right"):
        mine = [s for s in plan.steps if s.arm == role]
        for prev, cur in zip(mine, mine[1:]):
            assert prev.index in cur.depends_on


def test_single_arm_plan_is_serial_without_alternates():
    _, _, _, plan = stacked_plan()
    assert all(s.arm == "solo" and s.alternates == () and s.zone is None for s in plan.steps)
    for s in plan.steps[1:]:
        assert s.index - 1 in s.depends_on
    assert plan.steps[0].depends_on == ()


def test_reach_predicate_limits_arms_and_alternates():
    recipe = load_mixed_recipe(recipe_text(MIXED))
    cell = workcell_from_dict(TWO_ARMS)
    ring = annulus_reach(cell, 0.05, 0.25)

    def left_only(role, pose):
        return role == "left" and ring(role, pose)

    plan = plan_mixed(recipe, cell, left_only)
    check_plan(recipe, cell, left_only, plan)
    assert all(s.arm == "left" and s.alternates == () for s in plan.steps)
    assert plan.feed_order["infeed_right"] == ()


def test_yaw_subset_is_honoured():
    recipe = load_mixed_recipe(recipe_text(MIXED, yaws=(0,)))
    _, cell, reach, _ = two_arm_plan()
    plan = plan_mixed(recipe, cell, reach)
    assert all(s.pose_cell.yaw == 0.0 for s in plan.steps)
    check_plan(recipe, cell, reach, plan)


def test_items_that_do_not_fit_raise():
    recipe = load_mixed_recipe(recipe_text(STACKED, length=0.12, width=0.10, max_height=0.035))
    cell = workcell_from_dict(ONE_ARM)
    with pytest.raises(PlanError, match="no placement satisfies the rules"):
        plan_mixed(recipe, cell, annulus_reach(cell, 0.05, 0.30))


def test_load_limit_blocks_stacking_on_fragile_items():
    items = [foam("fragile", 0.040, 0.030, 0.030, 0.020, 0.015, 4, top_kg=0.0)]
    recipe = load_mixed_recipe(recipe_text(items, length=0.10, width=0.04))
    cell = workcell_from_dict(dict(ONE_ARM, pallet_origins={"A": [0.10, -0.02, 0.0]}))
    with pytest.raises(PlanError):
        plan_mixed(recipe, cell, annulus_reach(cell, 0.05, 0.30))
    sturdy = load_mixed_recipe(recipe_text([dict(items[0], max_load_on_top_kg=0.1)], length=0.10, width=0.04))
    plan = plan_mixed(sturdy, cell, annulus_reach(cell, 0.05, 0.30))
    check_plan(sturdy, cell, annulus_reach(cell, 0.05, 0.30), plan)


def test_input_problems_are_reported():
    recipe = load_mixed_recipe(recipe_text(MIXED))
    bad = workcell_from_dict(dict(ONE_ARM, pallet_origins={"B": [0, 0, 0]}, stations={"infeed_left": [0, 0, 0]}))
    with pytest.raises(PlanError) as err:
        plan_mixed(recipe, bad, annulus_reach(bad, 0.05, 0.3))
    text = str(err.value)
    assert "pallet A has no origin" in text and "infeed_right is not a workcell station" in text
    deep = workcell_from_dict(dict(ONE_ARM, finger={"overhang_m": 0.02}))
    with pytest.raises(PlanError, match="reaches below the item bottom"):
        plan_mixed(recipe, deep, annulus_reach(deep, 0.05, 0.3))
    with pytest.raises(PlanError, match="no arm reaches any pick station"):
        plan_mixed(recipe, workcell_from_dict(ONE_ARM), lambda role, pose: False)


def test_workcell_validation():
    with pytest.raises(WorkcellError, match="needs zones"):
        workcell_from_dict(dict(TWO_ARMS, zones=[]))
    overlapping = [dict(z) for z in TWO_ARMS["zones"]]
    overlapping[0]["x_max"] = 0.16
    with pytest.raises(WorkcellError, match="overlap"):
        workcell_from_dict(dict(TWO_ARMS, zones=overlapping))
    arms = [dict(a) for a in TWO_ARMS["arms"]]
    arms[1]["zone_id"] = "shared_band"
    with pytest.raises(WorkcellError, match="cannot own shared_band"):
        workcell_from_dict(dict(TWO_ARMS, arms=arms))
    with pytest.raises(WorkcellError, match="malformed"):
        workcell_from_dict({"arms": [{"role": "x"}]})
    with pytest.raises(WorkcellError):
        annulus_reach(workcell_from_dict(ONE_ARM), 0.3, 0.1)


def test_annulus_reach_and_finger_defaults():
    cell = workcell_from_dict(ONE_ARM)
    reach = annulus_reach(cell, 0.05, 0.25)
    assert reach("solo", CellPose(0.10, 0.0, 0.0, 0.0))
    assert not reach("solo", CellPose(0.01, 0.0, 0.0, 0.0))
    assert not reach("solo", CellPose(0.30, 0.0, 0.0, 0.0))
    assert cell.finger == Finger() and Finger().reach_out_m == pytest.approx(0.014)


def test_step_dict_shape():
    _, _, _, plan = two_arm_plan()
    d = plan.to_dict()
    assert set(d) == {"recipe_hash", "planner_version", "steps", "feed_order"}
    assert set(d["steps"][0]) == {"index", "role", "sku", "pallet_id", "pose_cell", "arm", "alternates", "zone",
                                  "coupling", "depends_on", "carry_z", "station"}
    assert set(d["steps"][0]["pose_cell"]) == {"x", "y", "z", "yaw"}
