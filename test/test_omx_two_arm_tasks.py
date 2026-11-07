"""Two-arm task plans: the validator refuses what the geometry or the order forbids, and names why. No MuJoCo needed."""
import copy
import math
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402
import omx_two_arm_teacher as teacher  # noqa: E402


@pytest.fixture(scope="module")
def layout():
    return sites.Layout()


@pytest.fixture(scope="module")
def data():
    return tasks.load()


def refused(layout, task):
    with pytest.raises(tasks.PlanRefused) as caught:
        tasks.validate(layout, task)
    return " | ".join(caught.value.reasons)


def test_both_tasks_validate_with_all_steps(layout, data):
    assert len(tasks.validate(layout, tasks.get_task(layout, "stack", data))) == 9
    assert len(tasks.validate(layout, tasks.get_task(layout, "rehandle", data))) == 12


def test_stack_follows_the_fixture_plan_order_and_arms(layout, data):
    steps = data["tasks"]["stack"]["steps"]
    assert [(s["container"], s["to"], s["arm"]) for s in steps] == layout.plan_order()
    assert {s["from"] for s in steps} == {"belt"} and len({s["to"] for s in steps}) == 9


def test_rehandle_uses_both_arms_and_temp_space_within_capacity(layout, data):
    steps = data["tasks"]["rehandle"]["steps"]
    assert {s["arm"] for s in steps} == {"arm_a", "arm_b"}
    for s in steps:  # an outer column is rehandled by the arm on the other side (the near arm's wrist hits the middle column)
        row = (s["from"] if s["from"].startswith("ship") else s["to"])[6]
        assert s["arm"] == ("arm_b" if row == "0" else "arm_a")
    held = {}
    for s in steps:
        held[s["container"]] = s["to"]
        per_plate = [sum(1 for v in held.values() if v.startswith(f"tmp-{p}")) for p in "ab"]
        assert max(per_plate) <= tasks.CAPACITY
    assert all(v.startswith("ship-") for v in held.values())  # everything is back on the ship at the end


def test_a_container_is_never_taken_from_under_another(layout, data):
    task = copy.deepcopy(tasks.get_task(layout, "rehandle", data))
    task["steps"] = [dict(id="x", container="bar-2", **{"from": "ship-r0-l0"}, to="tmp-b-1", arm="arm_b")]  # bar-5 and bar-8 still lie on it
    reason = refused(layout, task)
    assert "taken from under" in reason and "ship-r0-l1" in reason


def bad_near_arm_plan(layout, data):
    """The first rehandle plan: arm_a takes bar-2 (bottom of the near column r0) while the middle column stands. MuJoCo: link4 hit bar-7."""
    task = copy.deepcopy(tasks.get_task(layout, "rehandle", data))
    task["steps"] = [dict(id="a1", container="bar-8", **{"from": "ship-r0-l2"}, to="tmp-a-1", arm="arm_a"),
                     dict(id="a2", container="bar-5", **{"from": "ship-r0-l1"}, to="tmp-a-2", arm="arm_a"),
                     dict(id="a3", container="bar-2", **{"from": "ship-r0-l0"}, to="tmp-a-3", arm="arm_a")]
    return task


def test_a_wrist_that_would_hit_a_standing_column_is_refused(layout, data):
    reason = refused(layout, bad_near_arm_plan(layout, data))
    assert "a3:" in reason and "wrist" in reason and "neighbouring column" in reason
    assert "a1:" not in reason and "a2:" not in reason  # the layer 1 and 2 steps of the same plan are fine


def test_the_same_container_taken_by_the_far_arm_is_accepted(layout, data):
    task = bad_near_arm_plan(layout, data)
    task["steps"] = [dict(s, arm="arm_b", to=s["to"].replace("tmp-a", "tmp-b")) for s in task["steps"]]
    records = tasks.validate(layout, task)
    assert records[2]["min_wrist_gap_mm"] >= tasks.LINK_MARGIN * 1000  # bar-2 by arm_b: MuJoCo isolated run passed


def test_wrist_clearance_matches_the_mujoco_matrix_at_layer_0(layout, data):
    """arm_a/bar-2, arm_b/bar-3 and the middle bottom bar-1 collided in MuJoCo (link4 -3 to -6 mm); the others cleared by 8 mm or more."""
    cases = {("bar-2", "arm_a"): False, ("bar-2", "arm_b"): True, ("bar-3", "arm_b"): False, ("bar-3", "arm_a"): True, ("bar-1", "arm_a"): False, ("bar-1", "arm_b"): False}
    full = {c: s for c, s, _ in layout.plan_order()}
    for (c, arm), clear in cases.items():
        row = full[c].split("-")[1]
        above = {n for n, s in full.items() if s.startswith(f"ship-{row}-l") and int(s[-1]) > 0}
        task = dict(name="m", start={k: v for k, v in full.items() if k not in above},
                    steps=[dict(id="x", container=c, **{"from": full[c]}, to=f"tmp-{arm[-1]}-2", arm=arm)])
        try:
            gap = tasks.validate(layout, task)[0]["min_wrist_gap_mm"]
            assert clear, f"{c} by {arm} should be refused (MuJoCo collided), gap {gap}"
        except tasks.PlanRefused as e:
            assert not clear and "wrist" in str(e)


def test_a_target_needs_a_support_and_must_be_free(layout, data):
    task = dict(supply=["bar-1"], start={}, steps=[dict(id="x", container="bar-1", **{"from": "belt"}, to="ship-r1-l1", arm="arm_b")], name="t")
    assert "nothing under it" in refused(layout, task)
    full = copy.deepcopy(tasks.get_task(layout, "rehandle", data))
    full["steps"] = [dict(id="y", container="bar-2", **{"from": "ship-r0-l0"}, to="tmp-a-1", arm="arm_a")]
    assert "taken from under" in refused(layout, full)


def test_temporary_plate_capacity_is_enforced(layout, data):
    task = copy.deepcopy(tasks.get_task(layout, "rehandle", data))
    task["steps"][1]["to"] = "tmp-a-1"  # two containers on one lane
    reason = refused(layout, task)
    assert "already holds" in reason


def test_an_unreachable_site_is_refused_not_moved(layout, data):
    far = sites.Layout(temp_radius_m=.45)  # plate centre 450 mm from the arm: beyond any reach
    reason = refused(far, tasks.get_task(far, "rehandle", data))
    assert "cannot reach" in reason and "cannot reach" in reason


def test_unknown_names_are_refused(layout):
    task = dict(supply=["bar-1"], start={}, name="t", steps=[dict(id="x", container="bar-99", **{"from": "belt"}, to="nowhere", arm="arm_c")])
    reason = refused(layout, task)
    assert "unknown container" in reason and "unknown site" in reason and "unknown arm" in reason


def test_the_belt_is_a_source_only_and_must_supply_the_container(layout):
    task = dict(supply=[], start={"bar-1": "ship-r1-l0"}, name="t", steps=[dict(id="x", container="bar-1", **{"from": "ship-r1-l0"}, to="belt", arm="arm_b")])
    assert "source, not a target" in refused(layout, task)
    task = dict(supply=[], start={}, name="t", steps=[dict(id="x", container="bar-1", **{"from": "belt"}, to="ship-r1-l0", arm="arm_b")])
    assert "not on the belt supply" in refused(layout, task)


def test_arm_clearance_catches_two_arms_in_the_same_place(layout):
    arm = layout.arms["arm_a"]
    assert tasks.clearance(arm, arm.home, [arm.home], arm) < 2 * tasks.ARM_RADIUS  # an arm on top of itself
    home_gap = tasks.clearance(layout.arms["arm_a"], layout.arms["arm_b"].home, [layout.arms["arm_a"].home], layout.arms["arm_b"])
    assert home_gap > 2 * tasks.ARM_RADIUS + tasks.ARM_MARGIN  # the two parked arms are apart


def test_temp_lanes_follow_the_scad_fan_and_point_at_the_arm(layout):
    width, length, flare, fan, angles = sites.lane_geometry(.214)
    assert width == pytest.approx(.0308) and math.degrees(fan) == pytest.approx(15.6, abs=.3) and angles[1] == 0
    for tag, arm in (("a", "arm_a"), ("b", "arm_b")):
        base = layout.arms[arm].base[:2]
        for i in (1, 2, 3):
            s = layout.sites[f"tmp-{tag}-{i}"]
            assert np.linalg.norm(np.array(s["xy"]) - base) == pytest.approx(.214, abs=1e-6)
            toward = np.array(base) - np.array(s["xy"])
            assert abs(math.cos(s["yaw"]) * toward[1] - math.sin(s["yaw"]) * toward[0]) < 1e-6  # long axis through the arm centre
        assert layout.sites[f"tmp-{tag}-1"]["z"] == layout.sites["ship-r0-l0"]["z"]  # deck as high as the ship plate


def test_named_choices_change_the_layout_and_are_reported(layout):
    cad = sites.Layout(fixture_case="nominal-palletizing-v21-ship", base_z="cad")
    assert not np.allclose(cad.arms["arm_b"].base, layout.arms["arm_b"].base)
    assert layout.arms["arm_b"].base[2] - cad.arms["arm_b"].base[2] == pytest.approx(.012)
    assert layout.choices["tcp_x_arm_b"] == .0740 and layout.arms["arm_b"].tcp[0] == pytest.approx(.0740)
    assert sites.Layout(tcp_x_arm_b=.0885).arms["arm_b"].tcp[0] == pytest.approx(.0885)


def test_roll_below_the_usable_floor_is_flagged(layout, data):
    records = tasks.validate(layout, tasks.get_task(layout, "stack", data))
    flagged = {r["step"] for r in records if r["roll_below_floor"]}
    assert flagged and all(r["min_roll_rad"] < layout.roll_floor for r in records if r["step"] in flagged)
    assert layout.roll_floor == pytest.approx(-.566, abs=.001)  # -18 in the norm unit


def test_strict_pose_judge_names_each_limit(layout, data):
    limits = data["judge"]
    site = layout.sites["ship-r1-l0"]

    class Fake:
        def __init__(self, layout, pos, yaw, tilt):
            self.layout, self._p = layout, (np.array(pos), yaw, tilt)

        def pose(self, _data, _cid):
            return self._p

    at = lambda dx=0., dz=0., yaw=0., tilt=0.: teacher.judge_pose(Fake(layout, [site["xy"][0] + dx, site["xy"][1], site["z"] + dz], yaw, tilt), None, "c", "ship-r1-l0", limits)  # noqa: E731
    assert at()["ok"] and at(dx=.002)["ok"]
    assert not at(dx=.005)["ok"] and not at(dz=.004)["ok"] and not at(yaw=math.radians(8))["ok"] and not at(tilt=6)["ok"]
    assert at(yaw=math.pi)["ok"]  # a container turned 180 deg sits the same


def test_a_run_records_the_cell_s_four_cameras():
    assert teacher.RECORDED == ("top", "side", "a_wrist", "b_wrist")  # D-960; the overview is not a camera the cell has
    assert sites.CHOICES["wrist_camera"] == "stock", "a run without wrist cameras would not match the cell"
