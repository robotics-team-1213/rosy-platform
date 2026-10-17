"""D-778 §2 / D-781 G1 SIM layout: two facing OMX bases, a 0.20 x 0.15 m pallet, IK reach of every
compiled pose, conservative swept separation of concurrent Steps, and the schedule against one arm.

Pure Python (no ROS, no Gazebo). The numbers are recorded in
docs/validation/bimanual-g1-sim-2026-10-17/README.md; ``python test/g1_layout.py`` reprints them.
"""

import math

import pytest

import g1_layout as g1
from g1_layout import G1_FIXTURE, MIXED_FIXTURE

from rosy.integrations.robots.omx.mixed_reach import IkReach, ik_reach_from_profile, pose_in_base
from rosy.processes.palletizing.mixed_cell import CellPose
from rosy.processes.palletizing.mixed_plan import PlanError
from rosy.processes.palletizing.mixed_planner import plan_mixed
from rosy.processes.palletizing.mixed_submission import compile_mixed_cell_job

RECIPES = {"2sku": MIXED_FIXTURE / "recipe.yaml", "4sku": G1_FIXTURE / "recipe_4sku.yaml"}
G1_CELL = G1_FIXTURE / "cell_g1.yaml"
# Recorded baselines (README "Stack"): volume fill of pallet area x max_stack_height, planner rules only.
FILL_BASELINE = {"2sku": 0.16, "4sku": 0.139}
SHARED = "shared_band"


@pytest.fixture(scope="module")
def kin_profile():
    return g1.kinematics_and_profile()


@pytest.fixture(scope="module", params=sorted(RECIPES))
def g1_report(request):
    recipe_doc, cell_doc = g1.read_documents(RECIPES[request.param], G1_CELL)
    return request.param, g1.report(recipe_doc, cell_doc)


def test_g1_cell_is_the_compile_fixture_with_only_the_home_moved():
    _, fixture = g1.read_documents(RECIPES["2sku"], MIXED_FIXTURE / "cell.yaml")
    _, cell = g1.read_documents(RECIPES["2sku"], G1_CELL)
    assert [arm["home"] for arm in cell["arms"]] == [{"x": 0.08, "y": 0.0, "z": 0.12, "yaw": 0.0}] * 2
    for arm in cell["arms"]:
        arm["home"]["x"] = 0.12
    assert cell == fixture


def test_layout_matches_d778_section_2():
    facts = g1.layout_facts(g1.load_layout(RECIPES["4sku"], G1_CELL))
    assert facts["facing"] is True and facts["pallet_m"] == [0.20, 0.15]
    assert 0.30 <= facts["base_separation_m"] <= 0.35
    assert facts["pallet_centre_cell"] == [round(facts["base_separation_m"] / 2, 4), 0.0]
    assert all(0.15 <= distance <= 0.18 for distance in facts["centre_from_base_m"].values())


def test_ik_reach_uses_each_arms_base_frame(kin_profile):
    kin, profile = kin_profile
    reach = IkReach({"left": (0.0, 0.0, 0.0), "right": (0.33, 0.0, math.pi)}, kin, profile.ik_limits())
    centre = CellPose(0.165, 0.0, 0.05, 0.0)
    assert reach("left", centre) and reach("right", centre)
    mirrored = pose_in_base((0.33, 0.0, math.pi), CellPose(0.18, 0.02, 0.05, 0.3))
    assert (round(mirrored.x, 9), round(mirrored.y, 9), mirrored.z) == (0.15, -0.02, 0.05)
    assert math.isclose(math.remainder(mirrored.yaw - (0.3 - math.pi), math.tau), 0.0, abs_tol=1e-12)
    assert not reach("left", CellPose(0.33, 0.0, 0.05, 0.0))  # the far base: 0.33 m is out of reach
    assert reach.solve("left", CellPose(0.0, 0.16, 0.0, 0.0)).reason == "OUTSIDE_WORKSPACE"  # z below 0.005 m
    assert ik_reach_from_profile({"left": (0.0, 0.0, 0.0)}, g1.PROFILE_PATH)("left", centre)


@pytest.mark.parametrize("recipe,cell", [("2sku", MIXED_FIXTURE / "cell.yaml"), ("2sku", G1_CELL),
                                         ("4sku", G1_CELL)])
def test_every_compiled_pose_of_both_arms_is_ik_reachable(kin_profile, recipe, cell):
    kin, profile = kin_profile
    layout = g1.load_layout(RECIPES[recipe], cell)
    job = compile_mixed_cell_job(layout.recipe, layout.cell)
    checked, failures = g1.reach_audit(job.steps, kin, profile)
    # every Step x (primary + alternates) x 7 poses (pick/approach/carry, place/approach/carry, home)
    assert checked == 7 * sum(len(step["placement"]["actions"]) for step in job.steps)
    assert failures == []


def test_planner_with_ik_reach_plans_or_is_refused_only_by_its_station_probe(kin_profile):
    """Known gap (README): plan_mixed probes reach with the TCP on the station surface (z 0), below the
    profile's 5 mm workspace floor, so IK reach is refused before any item is placed. If the probe is
    fixed the IK plan must be fully reachable."""
    kin, profile = kin_profile
    layout = g1.load_layout(RECIPES["2sku"], G1_CELL)
    reach = g1.ik_reach(layout.workcell, kin, profile)
    try:
        plan = plan_mixed(layout.recipe, layout.workcell, reach)
    except PlanError as exc:
        assert list(exc.problems) == ["no arm reaches any pick station"]
        return
    assert all(reach(step.arm, step.pose_cell) for step in plan.steps)


def test_concurrent_steps_have_separated_swept_volumes(g1_report):
    _, report = g1_report
    pairs = report["swept_separation"]["pairs"]
    concurrent = [item for item in pairs if item["pair"][1] != "home"]
    assert concurrent and any(SHARED in item["zones"] for item in concurrent)  # the band is exercised
    assert all(item["zones"][0] != item["zones"][1] for item in concurrent)
    assert min(item["clearance_m"] for item in pairs) > g1.MIN_CLEARANCE_M


def test_the_separation_check_rejects_the_pilot_home_layout():
    """Mutation proof: the same cell with the pilot home x 0.12 m overlaps (README: about -3 cm)."""
    recipe_doc, cell_doc = g1.read_documents(RECIPES["2sku"], G1_CELL)
    result = g1.separation_only(recipe_doc, g1.variant_cell(cell_doc, separation_m=0.33, home_x_m=0.12))
    assert result["reach_failures"] == 0 and result["min_clearance_m"] < 0


def test_two_arms_finish_sooner_than_one_and_keep_the_stack_rules(g1_report):
    name, report = g1_report
    assert report["reach"]["failures"] == [] and report["one_arm"]["reach_failures"] == []
    assert report["two_arm"]["makespan_s"] < report["two_arm"]["serial_s"]
    assert report["speedup_vs_one_arm"] > 1.3
    for stack in (report["stack_two_arm"], report["stack_one_arm"]):
        assert stack["support_violations"] == [] and stack["load_violations"] == []
        assert stack["items"] == report["one_arm"]["steps"] and stack["fill_rate_volume"] >= FILL_BASELINE[name]
    if name == "4sku":
        assert len(report["stack_two_arm"]["skus"]) == 4  # D-781 G1: 3-4 skus


def test_barrier_arrival_skew_of_two_arm_steps_is_far_below_the_proposed_max_wait(g1_report):
    _, report = g1_report
    skews = report["barrier_skews"]
    assert skews and max(item["skew_after_grasp_s"] for item in skews) < 45.0
    assert max(item["skew_after_transfer_s"] for item in skews) < 85.0
