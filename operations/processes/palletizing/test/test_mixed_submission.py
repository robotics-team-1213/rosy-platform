"""recipe/3 -> per-arm pallet.transfer inputs (D-781 §5, D-779 §4) and the cell/3 loader (D-778 §1)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import yaml

from rosy.processes.palletizing.cell import CellError
from rosy.processes.palletizing.mixed_cell import ArmBase, CellPose
from rosy.processes.palletizing.mixed_cell_doc import load_mixed_cell
from rosy.processes.palletizing.mixed_plan import pick_pose
from rosy.processes.palletizing.mixed_planner import PLANNER_VERSION, plan_mixed
from rosy.processes.palletizing.mixed_recipe import load_mixed_recipe
from rosy.processes.palletizing.mixed_submission import (
    SUBMISSION_VERSION,
    compile_mixed_cell_job,
    pose_in_base,
    yaw_in_base,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mixed_two_arm"
LEFT = ArmBase("left", 0.0, 0.0, 0.0, "left_half")
RIGHT = ArmBase("right", 0.33, 0.0, math.pi, "right_half")  # faces the left arm


def documents():
    return tuple(yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8")) for name in ("recipe.yaml", "cell.yaml"))


def loaded(cell_doc=None):
    recipe_doc, default_cell = documents()
    return load_mixed_recipe(json.dumps(recipe_doc)), load_mixed_cell(json.dumps(cell_doc or default_cell))


def to_cell(base, pose):
    """Inverse of pose_in_base, written out independently."""
    c, s = math.cos(base.yaw), math.sin(base.yaw)
    x, y = pose["x_m"], pose["y_m"]
    return (base.x + c * x - s * y, base.y + s * x + c * y, pose["z_m"], pose["yaw_rad"] + base.yaw)


# ---- frame transform -------------------------------------------------------------------------

@pytest.mark.parametrize("cell_yaw, base_yaw, expected", [
    (0.0, math.pi, math.pi),  # -pi maps to +pi: the interval is (-pi, pi]
    (math.pi / 2, math.pi, -math.pi / 2),
    (-math.pi, 0.0, math.pi),
    (3 * math.pi, 0.0, math.pi),
    (0.25, 0.0, 0.25),
])
def test_yaw_is_cell_minus_base_in_minus_pi_to_pi(cell_yaw, base_yaw, expected):
    assert yaw_in_base(cell_yaw, base_yaw) == pytest.approx(expected)
    assert -math.pi < yaw_in_base(cell_yaw, base_yaw) <= math.pi


def test_arms_facing_each_other_see_mirrored_coordinates():
    # A point 0.20 m along the cell x axis, 0.05 m to the left: 0.13 m in front of the right arm
    # (whose x axis points back at the left arm) and 0.05 m to ITS right.
    pose = CellPose(0.20, 0.05, 0.03, 0.0)
    assert pose_in_base(LEFT, pose) == {"x_m": 0.2, "y_m": 0.05, "z_m": 0.03, "yaw_rad": 0.0}
    assert pose_in_base(RIGHT, pose) == pytest.approx({"x_m": 0.13, "y_m": -0.05, "z_m": 0.03, "yaw_rad": math.pi},
                                                      abs=1e-9)
    turned = pose_in_base(RIGHT, CellPose(0.20, 0.05, 0.03, math.pi / 2))
    assert turned["yaw_rad"] == pytest.approx(-math.pi / 2)
    for base in (LEFT, RIGHT):
        back = to_cell(base, pose_in_base(base, pose))
        assert back[:3] == pytest.approx((0.20, 0.05, 0.03), abs=1e-9)
        assert math.remainder(back[3] - pose.yaw, math.tau) == pytest.approx(0.0, abs=1e-9)


def test_rotated_base_quarter_turn():
    base = ArmBase("a", 0.1, 0.2, math.pi / 2)
    # cell (0.1, 0.3) is 0.1 m along the base's x axis (cell +y); float noise rounds away
    assert pose_in_base(base, CellPose(0.1, 0.3, 0.0, math.pi / 2)) == {
        "x_m": 0.1, "y_m": 0.0, "z_m": 0.0, "yaw_rad": 0.0}


# ---- full recipe/3 compile -------------------------------------------------------------------

def test_two_arm_fixture_compiles_every_arm_in_its_own_frame():
    recipe, cell = loaded()
    compiled = compile_mixed_cell_job(recipe, cell)
    workcell = cell.workcell(recipe)
    plan = plan_mixed(recipe, workcell, cell.reach(workcell))
    bases = {"left": LEFT, "right": RIGHT}
    assert compiled.arms == ({"role": "left", "instance_id": "omx_01_control", "workcell_id": "omx_01"},
                             {"role": "right", "instance_id": "omx_02_control", "workcell_id": "omx_02"})
    assert len(compiled.steps) == len(plan.steps) == 12
    assert compiled.ledger_markers == ({"after_step_ordinal": 12, "pallet_id": "A"},)
    assert compiled.pallet_ids == ("A",)
    items = {i.sku: i for i in recipe.items}
    shared = 0
    for step, out in zip(plan.steps, compiled.steps):
        placement = out["placement"]
        assert (out["skill_id"], out["version"]) == ("pallet.transfer", "1.0.0")
        assert (placement["arm"], placement["alternates"], placement["zone"], placement["coupling"],
                placement["depends_on"]) == (step.arm, list(step.alternates), step.zone, "independent",
                                             list(step.depends_on))
        assert set(placement["actions"]) == {step.arm, *step.alternates}
        stations = dict(((step.arm, step.station), *zip(step.alternates, step.alternate_stations)))
        shared += bool(step.alternates)
        item = items[step.sku]
        for role, inputs in placement["actions"].items():
            base = bases[role]
            assert inputs["item"] == "box" and inputs["pallet_id"] == "A"
            assert inputs["home_pose_base"] == {"x_m": 0.12, "y_m": 0.0, "z_m": 0.12, "yaw_rad": 0.0}
            place = to_cell(base, inputs["destination_pose_base"])
            assert place[:3] == pytest.approx((step.pose_cell.x, step.pose_cell.y, step.pose_cell.z), abs=1e-8)
            pick = pick_pose(workcell, stations[role], item.height, item.grasp_depth, step.pose_cell.yaw)
            assert to_cell(base, inputs["source_pose_base"])[:3] == pytest.approx((pick.x, pick.y, pick.z), abs=1e-8)
            carry = inputs["carry_z_base_m"]
            assert carry == pytest.approx(step.carry_z, abs=1e-9)
            for target, approach in (("source_pose_base", "source_approach_z_base_m"),
                                     ("destination_pose_base", "destination_approach_z_base_m")):
                expected = min(inputs[target]["z_m"] + item.grasp_depth + 0.02, step.carry_z)
                assert inputs[approach] == pytest.approx(expected, abs=2e-9)
                assert inputs[target]["z_m"] <= inputs[approach] <= carry
    assert shared, "the fixture should have shared-band Steps with an alternate arm"
    # the right arm's own station is straight to its right: (0.33, 0.16) -> (0, -0.16) in its frame
    right_pick = next(out["placement"]["actions"]["right"]["source_pose_base"] for out in compiled.steps
                      if out["placement"]["arm"] == "right")
    assert (right_pick["x_m"], right_pick["y_m"]) == (0.0, -0.16)


def test_layer_index_is_the_support_level():
    recipe, cell = loaded()
    compiled = compile_mixed_cell_job(recipe, cell)
    workcell = cell.workcell(recipe)
    plan = plan_mixed(recipe, workcell, cell.reach(workcell))
    levels = [{inputs["layer_index"] for inputs in out["placement"]["actions"].values()} for out in compiled.steps]
    assert all(len(level) == 1 for level in levels)
    on_pallet = [p.z == pytest.approx(0.0) for p in plan.placements]
    assert [level == {0} for level in levels] == on_pallet
    assert {1} in levels, "the fixture should stack a second level"


def test_job_document_names_planner_and_plan_and_is_deterministic():
    recipe, cell = loaded()
    first, second = compile_mixed_cell_job(recipe, cell), compile_mixed_cell_job(*loaded())
    assert json.dumps(first.job, sort_keys=True) == json.dumps(second.job, sort_keys=True)
    assert first.steps == second.steps
    workcell = cell.workcell(recipe)
    plan = plan_mixed(recipe, workcell, cell.reach(workcell))
    assert first.job["planner_version"] == PLANNER_VERSION
    assert first.job["submission_version"] == SUBMISSION_VERSION
    assert first.job["plan_digest"] == plan.digest and first.job["plan"] == plan.to_dict()
    assert (first.job["recipe_hash"], first.job["cell_hash"]) == (recipe.content_hash, cell.content_hash)
    assert (first.recipe_digest, first.cell_digest) == (recipe.content_hash, cell.content_hash)


# ---- cell/3 loader -------------------------------------------------------------------------

def _changed(change):
    _, cell_doc = documents()
    change(cell_doc)
    return json.dumps(cell_doc)


@pytest.mark.parametrize("change, message", [
    (lambda c: c.update(schema="rosy_cell.cell/2"), "schema must be rosy_cell.cell/3"),
    (lambda c: c.update(cell_frame="world"), "cell_frame must be cell"),
    (lambda c: c["arms"][0]["base_in_cell"].pop("calibration_revision"), "calibration_revision is missing"),
    (lambda c: c["arms"][1].update(instance_id="omx_01_control"), "instance_ids must be distinct"),
    (lambda c: c["arms"][1].update(workcell_id="omx_01"), "workcell_ids must be distinct"),
    (lambda c: c["arms"][1].update(zone_id="shared_band"), "cannot own shared_band"),
    (lambda c: c["reach"].update(model="ik"), "reach.model must be annulus"),
    (lambda c: c["reach"].update(r_min_m=0.4), "r_min_m must be below"),
    (lambda c: c.update(fixtures=[]), "fixtures is not a known field"),
    (lambda c: c["arms"][0]["home"].pop("yaw"), "home.yaw is missing"),
])
def test_cell_loader_refuses(change, message):
    with pytest.raises(CellError, match=message):
        load_mixed_cell(_changed(change))


def test_recipe_pallet_needs_a_cell_frame():
    recipe_doc, cell_doc = documents()
    cell_doc["pallet_frames"] = {"pallet_b": cell_doc["pallet_frames"]["pallet_a"]}
    recipe = load_mixed_recipe(json.dumps(recipe_doc))
    with pytest.raises(CellError, match="unknown frame 'pallet_a'"):
        load_mixed_cell(json.dumps(cell_doc)).workcell(recipe)
