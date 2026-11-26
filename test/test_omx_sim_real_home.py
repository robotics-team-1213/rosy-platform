"""Regression checks for sim-real 6-axis home alignment (`home_gripper='real'`, `v24-20261126-real-home`)."""
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))

import cell_act_inputs as inputs  # noqa: E402
import omx_two_arm_kin as kin  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402

REAL_CELL_HOME = [0.8, -62.2, 53.1, 51.6, 45.2, 48.8]


def test_home_gripper_rad_matches_cell_conversion_and_rejects_unknown():
    assert kin.home_gripper_rad("open") == 1.0
    real_rad = kin.home_gripper_rad("real")
    assert real_rad == pytest.approx(0.136758, abs=1e-4)
    for arm in inputs.ARMS:
        rule = inputs.grip_rule({}, arm)
        assert real_rad == pytest.approx(inputs.sim_gripper(REAL_CELL_HOME[5], rule), abs=1e-6)
    with pytest.raises(ValueError, match="home_gripper"):
        kin.home_gripper_rad("bad")


def test_plan_values_cache_separates_open_and_real():
    h_open, _ = kin.plan_values(home_gripper="open")
    h_real, _ = kin.plan_values(home_gripper="real")
    h_open2, _ = kin.plan_values(home_gripper="open")
    assert h_open[5] == 1.0 and h_open2[5] == 1.0
    assert h_real[5] == pytest.approx(kin.home_gripper_rad("real"), abs=1e-6)
    assert np.allclose(h_open[:5], h_real[:5], atol=1e-9)


def test_real_home_preset_matches_real_six_axis_home_and_preserves_defaults():
    default = sites.Layout()
    assert default.choices["wait_pose"] == "side" and default.choices["home_gripper"] == "open"
    v24 = sites.Layout(preset="v24-20261124")
    assert v24.choices["wait_pose"] == "side" and v24.choices["home_gripper"] == "open"

    real_lay = sites.Layout(preset="v24-20261126-real-home")
    assert real_lay.choices["wait_pose"] == "home"
    assert real_lay.choices["home_gripper"] == "real"

    for arm_name in inputs.ARMS:
        body = inputs.to_radians(REAL_CELL_HOME)
        expected = np.array([body[j] for j in inputs.JOINTS[:5]] + [inputs.sim_gripper(REAL_CELL_HOME[5], inputs.grip_rule({}, arm_name))])
        arm = real_lay.sim_arms[arm_name]
        assert np.allclose(arm.wait, arm.home, atol=1e-9)
        assert np.allclose(arm.wait, expected, atol=1e-4)


def test_mujoco_real_home_smooth_approach_and_park_and_cell_sim(tmp_path):
    pytest.importorskip("mujoco")
    import json
    import time
    import omx_cell_sim as cell_sim
    import omx_sim_real_mirror as mirror_mod
    import omx_two_arm_teacher as teacher_mod
    import omx_two_arm_world as world_mod

    cell = cell_sim.Cell(kin.CELL_EXAMPLE, home_gripper="real")
    assert cell.home[5] == pytest.approx(kin.home_gripper_rad("real"), abs=1e-6)

    lay = sites.Layout(preset="v24-20261126-real-home")
    world = world_mod.World(lay)
    now = time.time()
    lives = {}
    for arm_name, st in (("arm_a", [0.76, -62.25, 53.06, 51.65, 44.66, 49.18]),
                         ("arm_b", [0.71, -62.25, 52.97, 51.6, 44.71, 49.01])):
        p = tmp_path / f"{arm_name}.json"
        p.write_text(json.dumps({"t": now, "state": st, "target": st, "chunk": "home"}), encoding="utf-8")
        lives[arm_name] = str(p)
    rules = {a: inputs.grip_rule({}, a) for a in inputs.ARMS}
    _, mrep = mirror_mod.mirror(world, lives, rules, now=now)
    real_grip = kin.home_gripper_rad("real")
    for arm_name in sites.ARMS:
        entry = mrep["arms"][arm_name]
        assert entry["q_rad"][5] == pytest.approx(real_grip, abs=1e-4)
        assert np.allclose(entry["q_rad"], lay.sim_arms[arm_name].wait, atol=0.02)
        assert np.linalg.norm(entry["fk_minus_sim_mm"]) < 5.0

    teacher = teacher_mod.Teacher(world, seed=0)
    data = teacher.fresh({})
    for arm_name in sites.ARMS:
        assert data.qpos[world.q[arm_name]][5] == pytest.approx(real_grip, abs=1e-3)
    for c in data.contact[:data.ncon]:
        b1 = world.body_name[world.model.geom_bodyid[c.geom1]]
        b2 = world.body_name[world.model.geom_bodyid[c.geom2]]
        assert not ({b1, b2} in ({"a_link1", "a_link3"}, {"b_link1", "b_link3"}))

    task = tasks.get_task(lay, "stack")
    approach_cmds = []
    orig_frame = teacher.frame
    active_arm = [None]

    def spy_frame(d, targets, label, ctxs=None):
        if active_arm[0] == "arm_b" and teacher.phase == "approach":
            approach_cmds.append(float(targets["arm_b"][5]))
        return orig_frame(d, targets, label, ctxs)

    teacher.frame = spy_frame
    here = {}
    for step in task["steps"][:3]:
        active_arm[0] = step["arm"] if step["id"] == "s1" else None
        row = teacher.run_step(data, step, here)
        here[step["container"]] = step["to"]
        assert row["result"] == "pass", row
        assert not row["arm_arm_contacts"] and not row["arm_link_contacts"]
        assert data.qpos[world.q[step["arm"]]][5] == pytest.approx(real_grip, abs=0.02)
    assert approach_cmds[0] == pytest.approx(real_grip, abs=1e-3)
    assert max(abs(b - a) for a, b in zip(approach_cmds, approach_cmds[1:])) < 0.05
