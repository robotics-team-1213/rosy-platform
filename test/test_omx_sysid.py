"""OMX physics candidates (cell_physics.yaml) and the sysid promote rule: a fit enters only when held-out episodes agree."""
import json
import shutil
import sys
from pathlib import Path

import pytest

SIM = Path(__file__).parents[1] / "tools/sim"
sys.path.insert(0, str(SIM))
import omx_physics as physics  # noqa: E402
import omx_sysid as sysid  # noqa: E402

DESIGN = {"kp": 40.0, "kv": 6.3, "damping": 0.3, "armature": 0.01, "frictionloss": 0.0, "force": 2.0}


def test_design_is_the_constants_the_cells_had_written_in():
    p = physics.Physics("design")
    for arm in physics.ARMS:
        for j in physics.JOINTS[:5]:
            assert p.joint(arm, j) == DESIGN
        assert p.joint(arm, "gripper_joint_1") == dict(DESIGN, force=0.2)
        assert p.joint(arm, "gripper_joint_2") == DESIGN  # the mimic finger: passive constants only
    assert p.container() == {"mass": 0.016, "friction": [1.0, 0.005, 0.0001]}


def test_a_candidate_overrides_only_its_own_arm_and_joints():
    p = physics.Physics("twin-kp-20261109")
    assert p.chain == ["design", "twin-kp-20261109"]
    assert p.joint("arm_b", "joint1") == dict(DESIGN, kp=20.0)
    assert p.joint("arm_b", "joint2") == DESIGN
    assert p.joint("arm_a", "joint1") == DESIGN


def test_unknown_candidate_and_base_loop_are_refused():
    with pytest.raises(ValueError, match="no physics candidate"):
        physics.Physics("nope")
    doc = {"schema": "rosy.cell-physics/1", "candidates": {"a": {"base": "b"}, "b": {"base": "a"}}}
    with pytest.raises(ValueError, match="base loop"):
        physics.Physics("a", doc)


def test_ranges_span_candidates_and_widen_by_two_sd():
    r = physics.ranges()
    assert r["arms"]["arm_b"]["joint1"]["kp"] == {"low": 20.0, "high": 40.0}
    assert r["arms"]["arm_a"]["joint1"]["kp"] == {"low": 40.0, "high": 40.0}
    assert r["arms"]["arm_b"]["joint1"]["zero_offset_deg"] == {"low": 0.0, "high": 4.0}
    assert "zero_offset_deg" not in r["arms"]["arm_a"]["joint1"]
    doc = physics.load()
    doc["candidates"]["fit"] = {"base": "design", "source": "fitted", "arms": {"arm_a": {"joint2": {"damping": 0.5}}},
                                "sd": {"arm_a": {"joint2": {"damping": 0.1}}}}
    assert physics.ranges(doc)["arms"]["arm_a"]["joint2"]["damping"] == {"low": 0.3, "high": pytest.approx(0.7)}


def test_the_layout_choice_defaults_to_design():
    import omx_two_arm_sites as sites
    assert sites.CHOICES["physics"] == "design"
    assert sites.parse_choices(["physics=twin-kp-20261109"]) == {"physics": "twin-kp-20261109"}


def fit(base_hold, new_hold):
    return {"base": "design", "arm": "arm_b", "keys": ["kp", "damping"], "gravity_comp": False, "at": "2026-11-09T05:00:00+00:00",
            "episodes": {"fit": ["e1", "e2"], "hold": ["e3"]},
            "rms_deg": {"base": {"fit": base_hold, "hold": base_hold}, "fitted": {"fit": new_hold, "hold": new_hold}},
            "fitted": {j: {"kp": 25.0, "damping": 0.2} for j in physics.JOINTS[:5]},
            "sd": {j: {"kp": 2.0, "damping": 0.05} for j in physics.JOINTS[:5]}}


def test_verdict_needs_a_better_hold_out_and_no_joint_worse():
    assert sysid.verdict(fit([1, 1, 1, 1, 1], [.5, .5, .5, .5, .5]))[0]
    assert not sysid.verdict(fit([1, 1, 1, 1, 1], [1, 1, 1, 1, 1]))[0]
    ok, why = sysid.verdict(fit([1, 1, 1, 1, 1], [.2, .2, .2, .2, 1.2]))
    assert not ok and "joint5" in why  # a lower mean does not excuse one joint getting worse


def test_promote_appends_a_candidate_and_never_overwrites(tmp_path):
    path = tmp_path / "cell_physics.yaml"
    shutil.copy(physics.FILE, path)
    before = path.read_text(encoding="utf-8")
    sysid.promote(fit([1, 1, 1, 1, 1], [.5, .5, .5, .5, .5]), "servo-test", "docs/validation/x/fit.json", path)
    assert path.read_text(encoding="utf-8").startswith(before.rstrip("\n"))  # comments and old candidates kept as they were
    doc = physics.load(path)
    p = physics.Physics("servo-test", doc)
    assert p.joint("arm_b", "joint3") == dict(DESIGN, kp=25.0, damping=0.2)
    assert p.joint("arm_a", "joint3") == DESIGN
    assert physics.ranges(doc)["arms"]["arm_b"]["joint3"]["kp"] == {"low": 21.0, "high": 40.0}
    with pytest.raises(SystemExit, match="exists"):
        sysid.promote(fit([1, 1, 1, 1, 1], [.5, .5, .5, .5, .5]), "servo-test", None, path)
    with pytest.raises(SystemExit, match="not promoted"):
        sysid.promote(fit([1, 1, 1, 1, 1], [2, 2, 2, 2, 2]), "servo-worse", None, path)


def test_next_puts_assumed_constants_first_with_an_experiment():
    rows = sysid.survey()
    assert rows[0][2] == "assumed"
    names = {c: (k, e) for _, c, k, e in rows}
    assert names["container.friction"][0] == "assumed" and "push test" in names["container.friction"][1]
    assert names["arm_b.joint1.kp"][0].startswith("fitted")
    assert json.dumps([list(r) for r in rows])  # the --json form serialises


def test_the_two_arm_world_builds_from_the_chosen_candidate():
    pytest.importorskip("mujoco")
    import omx_two_arm_world as tw
    for name, kp1 in (("design", 40.0), ("twin-kp-20261109", 20.0)):
        m = tw.World(physics=name).model
        a, b = m.actuator("a_joint1"), m.actuator("b_joint1")
        assert (a.gainprm[0], -a.biasprm[1], -a.biasprm[2]) == (40.0, 40.0, pytest.approx(6.3))
        assert (b.gainprm[0], -b.biasprm[1]) == (kp1, kp1)
        assert m.actuator("b_gripper_joint_1").forcerange[1] == pytest.approx(0.2)
        dof = m.jnt_dofadr[m.joint("b_joint2").id]
        assert (m.dof_damping[dof], m.dof_armature[dof], m.dof_frictionloss[dof]) == pytest.approx((0.3, 0.01, 0.0))


def sweep_rows(extra_pwm, pan_step=0.1, contact_from=0.4, noise=1.0, seed=0, ticks=150):
    """A runner trace: slide_push (the box adds extra_pwm from contact_from on), then slide_air on the same path; 5 Hz PWM
    samples repeated over 15 Hz ticks as chunk_runner writes them."""
    import random
    rnd, rows, t = random.Random(seed), [], 0.0
    for chunk in ("slide_push", "lift_push", "goto", "slide_air"):
        pwm = None
        for i in range(ticks if chunk.startswith("slide") else 5):
            s = i / (ticks - 1)
            if i % 3 == 0:
                extra = extra_pwm if chunk == "slide_push" and s >= contact_from else 0.0
                pwm = {"shoulder_pan": round(20 + 5 * s + extra + rnd.gauss(0, noise), 1), "shoulder_lift": 3}
            rows.append({"t": t, "chunk": chunk, "present": [pan_step * i, 0, 0, 0, 0, 0], "pwm": pwm})
            t += 1 / 15
    return rows


K = 1.5 * 11.7 / 12 / 885


def test_friction_reads_mu_from_the_pan_pwm_against_the_air_sweep():
    r = sysid.friction([(sweep_rows(7.0), 0.016, 0.2)])
    assert r["ok"], r["why"]
    assert r["mu"] == pytest.approx(7.0 * K / 0.2 / (0.016 * 9.81), rel=0.1)
    assert r["sd"] >= 0.25 * r["mu"] * 0.99  # the datasheet constant's share stays in the uncertainty


def test_friction_refuses_noise_and_effort_against_the_motion():
    weak = sysid.friction([(sweep_rows(1.0, noise=4.0), 0.016, 0.2)])
    assert not weak["ok"] and "tilt test" in weak["why"]
    backwards = sysid.one_sweep(sweep_rows(7.0, pan_step=-0.1), 0.016, 0.2)
    assert not backwards["ok"] and "not friction" in backwards["why"]
    with pytest.raises(SystemExit, match="slide_air"):
        sysid.one_sweep([r for r in sweep_rows(7.0) if r["chunk"] != "slide_air"], 0.016, 0.2)


def test_two_stack_heights_must_agree_like_friction_does():
    one, two = (sweep_rows(7.0, seed=1), 0.016, 0.2), (sweep_rows(14.0, seed=2), 0.032, 0.2)
    assert sysid.friction([one, two])["ok"]
    flat = sysid.friction([one, (sweep_rows(7.0, seed=2), 0.032, 0.2)])  # twice the load, same force: not friction alone
    assert not flat["ok"] and "disagree" in flat["why"]


def test_a_friction_fit_promotes_to_a_container_candidate_with_priority(tmp_path):
    path = tmp_path / "cell_physics.yaml"
    shutil.copy(physics.FILE, path)
    r = sysid.friction([(sweep_rows(7.0), 0.016, 0.2)])
    sysid.promote(r, "push-test", "docs/validation/x/friction.json", path)
    doc = physics.load(path)
    held = physics.Physics("push-test", doc).container()
    assert held == {"mass": 0.016, "friction": [r["mu"], 0.005, 0.0001], "priority": 1}
    span = physics.ranges(doc)["container"]["friction"]
    assert span["low"] == pytest.approx(max(r["mu"] - 2 * r["sd"], 0)) and span["high"] == 1.0
    assert dict((c, k) for _, c, k, _ in sysid.survey(doc))["container.friction"] == "fitted"
