"""C3 demo layout: every compiled Rosy Cell transfer plans on the OMX-F analytic planner (D-402).

Cross-package contract (rosy_cell -> Job, omx_adapter -> plan); neither package imports the
other, so the check lives here. Kinematic only: no collision scene, no Gazebo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src/products/omx/adapter", ROOT / "src/site/cell"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose  # noqa: E402
from omx_adapter.manipulation_plan import ExecutionStateSnapshot  # noqa: E402
from omx_adapter.pose_plan import (  # noqa: E402
    AnalyticCellTransferPlanner,
    CellPlanningProfile,
    CellTransferRequest,
)
from rosy_cell.cell import load_cell  # noqa: E402
from rosy_cell.compiler import compile_job  # noqa: E402
from rosy_cell.recipe import load_recipe  # noqa: E402

EXAMPLE = ROOT / "src/site/cell/examples/omx_sim"
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


def test_demo_is_two_pallets_two_layers_with_slip_sheets(demo):
    _, recipe, job = demo
    pairs = _transfers(job)
    assert [slot.id for slot in recipe.pallets] == ["A", "B"] and len(recipe.layers) == 2
    assert sum(pick.item == "box" for pick, _ in pairs) == 16
    assert sum(pick.item == "slip_sheet" for pick, _ in pairs) == 2
    assert recipe.box.mass_kg <= 0.05


@pytest.mark.parametrize("grasp_depth", [0.0, 0.015], ids=["step-z", "grasp-depth-15mm"])
def test_every_transfer_plans_without_rejection(demo, kin, profile, grasp_depth):
    cell, _, job = demo
    home = TopDownPose(cell.home.x, cell.home.y, cell.home.z, cell.home.yaw)
    joints = kin.solve_top_down(home, profile.ik_limits()).joints
    positions = dict(zip(ARM_JOINTS, joints))
    positions[profile.gripper_joint] = profile.gripper_open
    state = ExecutionStateSnapshot(
        sequence=1, joint_positions=positions, calibration_revision="omx-f-gazebo-only-v1",
        transform_revision="tf-sim-1", planning_scene_revision=kin.planning_scene_revision,
        observed_at_monotonic_s=0.5,
    )
    planner = AnalyticCellTransferPlanner(kin, accepted_cell_sha256=lambda: job.cell_hash,
                                          monotonic=lambda: 1.0)
    for index, (pick, place) in enumerate(_transfers(job)):
        # The probe lowers a box grasp below the top face; sheets are taken at their top.
        depth = grasp_depth if pick.item == "box" else 0.0
        request = CellTransferRequest(
            job_id="omx-sim-demo", recipe_sha256=job.recipe_hash, cell_sha256=job.cell_hash,
            step_index=index, item=pick.item, home=home,
            pick=TopDownPose(pick.target.x, pick.target.y, pick.target.z - depth, pick.target.yaw),
            place=TopDownPose(place.target.x, place.target.y, place.target.z - depth, place.target.yaw),
            pick_approach_z=pick.approach_z, place_approach_z=place.approach_z, carry_z=job.carry_z,
        )
        plan = planner.plan_transfer(request, profile, state)  # raises on any HOLD reason
        assert [phase.phase_id for phase in plan.phases] == ["approach", "grasp", "transfer", "release"]
