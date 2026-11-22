"""Unit and MuJoCo verification for outbound stand geometry and standalone episode generation."""
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_stand_episodes as eps  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402


def test_seed_and_source_parsing_and_features():
    assert eps.parse_seeds("6001..6003,6005") == [6001, 6002, 6003, 6005]
    layout = sites.Layout(preset="v24-20261114")
    srcs = eps.expand_sources("belt,tmp-a,belt", layout)
    assert srcs[0] == "belt" and len(srcs) == 10 and "tmp-a-2-l2" in srcs
    feats = eps.dataset_features()
    assert sorted(k for k in feats if k.startswith("observation.images.")) == [
        "observation.images.side", "observation.images.top", "observation.images.wrist"
    ]
    assert feats["observation.state"]["shape"] == (6,) and feats["action"]["shape"] == (6,)


def test_build_episode_plan_produces_valid_stand_steps_and_supports():
    layout = sites.Layout(preset="v24-20261114")
    rng = np.random.default_rng(42)
    for src in ("belt", "ship-h1r0-l0", "ship-h1r0-l2", "ship-h2r0-l0", "tmp-a-2-l1"):
        task = eps.build_episode_plan(layout, src, rng)
        assert task is not None, src
        records = tasks.validate(layout, task)
        assert len(records) == 1 and records[0]["joints_ok"]
        if src != "belt" and layout.sites[src].get("layer", 0) > 0:
            s = layout.sites[src]
            for low in range(s["layer"]):
                assert layout.stack_at[(s["stack"], low)] in task["start"].values()


def test_dart_scale_zero_during_settle_and_contact_phases():
    assert eps.dart_scale("approach", False) == pytest.approx(1.0)
    assert eps.dart_scale("carry", False) == pytest.approx(1.0)
    assert eps.dart_scale("lower", False) == pytest.approx(0.15)
    assert eps.dart_scale("approach", True) == 0.0
    for phase in ("grasp", "close", "lift", "release"):
        assert eps.dart_scale(phase, False) == 0.0


def test_mujoco_outbound_stand_geoms_and_teacher_execution():
    mujoco = pytest.importorskip("mujoco")
    import omx_two_arm_teacher as teaching
    import omx_two_arm_world as world_mod

    layout = sites.Layout(preset="v24-20261114")
    world = world_mod.World(layout)
    names = {mujoco.mj_id2name(world.model, mujoco.mjtObj.mjOBJ_GEOM, i) for i in range(world.model.ngeom)}
    expected = {"stand_chute", "stand_chute_gate", "stand_plate_top_deck", "stand_plate_top_rim",
                "stand_plate_bot_deck", "stand_plate_bot_rim", "stand_udock", "stand_ramp",
                "stand_gate_stop", "stand_wall_l", "stand_wall_r", "stand_back_l", "stand_back_r"}
    assert expected <= names
    assert "stand_riser" not in names

    teacher = teaching.Teacher(world, seed=0)
    data = teacher.fresh({})
    assert not world.contact_report(data)["arm_other"]

    res = teacher.run_task(tasks.get_task(layout, "outbound-stand"))
    assert res["completed"] is True and res["steps_pass"] == 4, res
    for row in res["rows"]:
        assert not row["arm_link_contacts"], row
        assert not row["neighbours_disturbed"], row
        assert 18.0 <= row["pose"]["dx_mm"] <= 44.0, row
        assert row["pose"]["tilt_deg"] == pytest.approx(24.0, abs=4.5), row
