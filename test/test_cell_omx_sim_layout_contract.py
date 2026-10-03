"""C3 demo layout: every compiled Rosy Cell transfer plans on the OMX-F analytic planner (D-402).

Cross-package contract (rosy_cell -> Job, omx_adapter -> plan); neither package imports the
other, so the check lives here. Kinematic only: no collision scene, no Gazebo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src/products/omx/adapter", ROOT / "operations/processes/cell"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# The palletizing process ships as the `rosy-palletizing` wheel (PEP 420 `rosy`
# namespace — ROSY_Platform_Architecture_Design_v0.2). Hosts without the wheel
# skip the contract instead of erroring at collection (importorskip precedent,
# docs/logs.md 2026-09-24).
pytest.importorskip("rosy.processes.palletizing")

from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose  # noqa: E402
from omx_adapter.manipulation_plan import ExecutionStateSnapshot  # noqa: E402
from omx_adapter.pose_plan import (  # noqa: E402
    GRASP_DEPTH_BELOW_FINGERTIPS,
    GRIPPER_WIDTH_INVALID,
    AnalyticCellTransferPlanner,
    CellTransferPlanRejected,
    CellPlanningProfile,
    CellTransferRequest,
)
from rosy_cell.cell import load_cell  # noqa: E402
from rosy_cell.compiler import compile_job  # noqa: E402
from rosy_cell.recipe import load_recipe  # noqa: E402

EXAMPLE = ROOT / "operations/processes/cell/examples/omx_sim"
PROFILE = ROOT / "deploy/robot/omx/sim/cell_profile.yaml"


@pytest.fixture(scope="module")
def demo():
    cell = load_cell((EXAMPLE / "cell.yaml").read_text(encoding="utf-8"))
    recipe = load_recipe((EXAMPLE / "recipe.yaml").read_text(encoding="utf-8"))
    return cell, recipe, compile_job(recipe, cell, tol_m=0.001)


@pytest.fixture(scope="module")
def kin():
    return OmxKinematics.load()


@pytest.fixture(scope="module")
def profile():
    return CellPlanningProfile.load(PROFILE)


def _transfers(job):
    moves = [step for step in job.steps if step.kind != "pallet_done"]
    pairs = list(zip(moves[0::2], moves[1::2]))
    assert all(pick.kind == "pick" and place.kind == "place" and pick.item == place.item
               for pick, place in pairs)
    return pairs


def test_demo_cell_cites_the_profile_geometry(demo, kin, profile):
    cell, _, _ = demo
    assert cell.kinematics_revision == profile.kinematics_revision == kin.revision
    # The cell's tool fingertip overhang is the profile's (pinned URDF + finger mesh).
    assert cell.fingertip_overhang_m == profile.fingertip_overhang_m


def test_demo_is_two_pallets_two_layers_with_slip_sheets(demo):
    _, recipe, job = demo
    pairs = _transfers(job)
    assert [slot.id for slot in recipe.pallets] == ["A", "B"] and len(recipe.layers) == 2
    assert sum(pick.item == "box" for pick, _ in pairs) == 16
    assert sum(pick.item == "slip_sheet" for pick, _ in pairs) == 2
    assert recipe.box.mass_kg <= 0.05


def _world_models(name):
    import xml.etree.ElementTree as ET

    world = ET.parse(ROOT / "src/sim/gz_sim/worlds" / name).getroot().find("world")
    models = {}
    for model in world.findall("model"):
        pose = [float(v) for v in model.findtext("pose").split()]
        size = [float(v) for v in model.find(".//collision/geometry/box/size").text.split()] \
            if model.find(".//collision/geometry/box/size") is not None else None
        models[model.get("name")] = (pose, size)
    return models


@pytest.mark.parametrize("world", ["omx_cell_workcell.sdf", "omx_cell_workcell_sim_aid.sdf"])
def test_gazebo_world_matches_the_demo_cell(demo, world):
    """World == robot base (vendor spawn at the origin), so poses compare directly."""
    cell, recipe, _ = demo
    models = _world_models(world)
    for slot, name in ((recipe.pallets[0], "pallet_a"), (recipe.pallets[1], "pallet_b")):
        (cx, cy, cz, *_), (sx, sy, sz) = models[name]
        frame = cell.frames[slot.frame]
        # Taught origin = near-left corner of the plate's top face; frame axes = base axes.
        assert frame.to_base((0.0, 0.0, 0.0)) == pytest.approx((cx - sx / 2, cy - sy / 2, cz + sz / 2))
        assert frame.to_base((slot.pallet.length, slot.pallet.width, 0.0)) == pytest.approx(
            (cx + sx / 2, cy + sy / 2, cz + sz / 2))
    (bx, by, bz, _, _, byaw), size = models["infeed_block"]
    assert size == pytest.approx([recipe.box.length, recipe.box.width, recipe.box.height])
    assert cell.station_pose(recipe.pick_station) == pytest.approx((bx, by, bz + size[2] / 2, byaw))
    (sx, sy, sz, *_), (_, _, thickness) = models["slip_sheet_0"]
    assert thickness == pytest.approx(recipe.slip_sheet_thickness)
    assert cell.station_pose(recipe.slip_sheet_station) == pytest.approx((sx, sy, sz + thickness / 2, 0.0))


def test_every_box_transfer_plans_and_slip_sheets_are_refused_by_width(demo, kin, profile):
    cell, recipe, job = demo
    assert recipe.box.grasp_depth > 0  # Step z of a box is already the TCP grasp height (C3b B1)
    home = TopDownPose(cell.home.x, cell.home.y, cell.home.z, cell.home.yaw)
    joints = kin.solve_top_down(home, profile.ik_limits()).joints
    positions = dict(zip(ARM_JOINTS, joints))
    positions[profile.gripper_joint] = profile.gripper_open
    state = ExecutionStateSnapshot(
        sequence=1, joint_positions=positions, calibration_revision="omx-f-gazebo-only-v1",
        transform_revision="tf-sim-1", planning_scene_revision=kin.planning_scene_revision,
        observed_at_monotonic_s=0.5,
    )
    # The device's accepted recipe defines each item's grasp geometry (review minor 5).
    items = {"box": {"grasp_width_m": recipe.box.width, "grasp_depth_m": recipe.box.grasp_depth,
                     "height_m": recipe.box.height},
             "slip_sheet": {"grasp_width_m": recipe.slip_sheet_thickness, "grasp_depth_m": 0.0,
                            "height_m": recipe.slip_sheet_thickness}}
    planner = AnalyticCellTransferPlanner(kin, accepted_cell_sha256=lambda: job.cell_hash,
                                          accepted_item_geometry=lambda sha, item: (
                                              items.get(item) if sha == job.recipe_hash else None),
                                          monotonic=lambda: 1.0)
    for index, (pick, place) in enumerate(_transfers(job)):
        # Sheets are taken at their top face.
        depth = recipe.box.grasp_depth if pick.item == "box" else 0.0
        request = CellTransferRequest(
            job_id="omx-sim-demo", recipe_sha256=job.recipe_hash, cell_sha256=job.cell_hash,
            step_index=index, item=pick.item, home=home,
            pick=TopDownPose(pick.target.x, pick.target.y, pick.target.z, pick.target.yaw),
            place=TopDownPose(place.target.x, place.target.y, place.target.z, place.target.yaw),
            pick_approach_z=pick.approach_z, place_approach_z=place.approach_z, carry_z=job.carry_z,
            grasp_depth_m=depth,
            # A box is squeezed across its width (yaw = its length axis). A 2 mm slip sheet
            # has no width the OMX-F fingers can close on (C3 problem 7; C6 decides how).
            grasp_width_m=recipe.box.width if pick.item == "box" else recipe.slip_sheet_thickness,
        )
        if pick.item == "slip_sheet":
            with pytest.raises(CellTransferPlanRejected) as rejected:
                planner.plan_transfer(request, profile, state)
            # The 2 mm sheet is also thinner than the 2.57 mm fingertip overhang, which the
            # device checks first (re-review minor 4); either way it is refused.
            assert rejected.value.reason in (GRASP_DEPTH_BELOW_FINGERTIPS, GRIPPER_WIDTH_INVALID)
            continue
        plan = planner.plan_transfer(request, profile, state)  # raises on any HOLD reason
        assert [phase.phase_id for phase in plan.phases] == ["approach", "grasp", "transfer", "release"]
