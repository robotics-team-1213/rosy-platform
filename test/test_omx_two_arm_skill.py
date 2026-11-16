"""Two-arm sub-skills: the errors a seed draws, the language each step gets, and the pass bar. MuJoCo only where fresh() applies a seed."""
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_policy as policy  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_skill as skills  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402


def test_calibration_error_is_per_seed_bounded_and_spares_the_gripper():
    """The IK baseline misses by this error; the exact arm (seed 0, or 0 deg) has none."""
    assert skills.draw_zero_error(0, 4.) == {} and skills.draw_zero_error(5, 0.) == {}
    error = skills.draw_zero_error(1003, 4.)
    assert set(error) == set(sites.ARMS)
    for arm, e in error.items():
        assert e.shape == (6,) and e[5] == 0 and (np.abs(e[:5]) <= np.radians(4.)).all() and np.abs(e[:5]).max() > 0
        assert (e == skills.draw_zero_error(1003, 4.)[arm]).all()
    assert not (skills.draw_zero_error(1004, 4.)["arm_a"] == error["arm_a"]).all()


def test_servo_lag_stays_in_the_measured_range():
    """Lag ~ 0.16 s x 40 / gain in the sim; the real joints took 0.10-0.34 s (twin 2026-11-09)."""
    assert skills.draw_servo_gain(0, True) == {} and skills.draw_servo_gain(7, False) == {}
    for gain in skills.draw_servo_gain(1003, True).values():
        lag = .16 * skills.teaching.SERVO_GAIN / gain
        assert gain.shape == (5,) and (lag >= skills.LAG_S[0]).all() and (lag <= skills.LAG_S[1]).all()


def test_each_step_names_its_arm_and_site_to_the_language_model():
    layout = sites.Layout()
    steps = [step for name in policy.TASKS for step in tasks.get_task(layout, name)["steps"]]
    for skill in skills.SKILLS:
        prompts = {skills.prompt(step, skill) for step in steps}
        assert all(p.startswith(("arm_a:", "arm_b:")) for p in prompts) and len(prompts) > 1
    assert skills.prompt(steps[0], "grasp") != skills.prompt(steps[0], "release")


def test_sub_skills_are_consecutive_waypoint_phases():
    """The hand-off waits for the first phase and ends after the last: a gap would hand the model a step it never saw."""
    layout = sites.Layout()
    step = tasks.get_task(layout, policy.TASKS[0])["steps"][0]
    names = [w[0] for w in tasks.waypoints(layout, step, {})]
    for spec in skills.SKILLS.values():
        k = names.index(spec["phases"][0])
        assert tuple(names[k:k + len(spec["phases"])]) == spec["phases"]


def test_a_sub_skill_round_passes_at_eighteen_of_twenty():
    """No whole tasks in a sub-skill round: the bar is the sim acceptance rate, not 'finished every task'."""
    assert policy.outcome(dict(n=20, passed=18, whole=[]), "grasp") == dict(status="passed")
    assert policy.outcome(dict(n=20, passed=17, whole=[]), "release")["status"] == "failed"
    assert policy.outcome(dict(n=0, passed=0, whole=[]), "grasp")["status"] == "failed"


def test_physics_ranges_draw_measured_constants_only_and_the_fitted_zero_offset_by_its_sign():
    ranges = skills.physics_ranges()
    assert skills.draw_physics(0, ranges) == ({}, {}) and skills.draw_physics(5, None) == ({}, {})
    servo, zero = skills.draw_physics(1003, ranges)
    for arm, values in servo.items():
        rows = [ranges["arms"][arm][f"joint{i}"] for i in range(1, 6)]
        for k, v in values.items():
            for x, r in zip(v, rows):
                assert np.isnan(x) if not r[k]["measured"] else r[k]["low"] <= x <= r[k]["high"]
        fraction = [(values[k][0] - rows[0][k]["low"]) / (rows[0][k]["high"] - rows[0][k]["low"]) for k in ("kp", "kv", "force")]
        assert fraction == pytest.approx([fraction[0]] * 3)  # one servo, stiff or soft as a whole
    assert "arm_a" not in zero  # no fit: the +-deg draw stays
    offsets = [ranges["arms"]["arm_b"][f"joint{i}"]["zero_offset_deg"]["high"] for i in range(1, 6)]
    assert zero["arm_b"][5] == 0 and all(0 <= e <= np.radians(o) for e, o in zip(zero["arm_b"][:5], offsets))


def _require_mujoco():
    try:
        import mujoco  # noqa: F401
    except Exception as exc:
        pytest.skip(str(exc))


def test_fresh_applies_a_seeds_servo_and_gives_the_next_teacher_the_candidates_own():
    _require_mujoco()
    import omx_two_arm_world as tw
    world = tw.World(sites.Layout())
    a = skills.teaching.Teacher(world, seed=1003)
    skills.disturb(a, 1003, 4., True, physics=True)
    a.fresh({})
    ids = world.act["arm_b"][:5]
    assert world.model.actuator_gainprm[ids, 0] == pytest.approx(np.where(np.isnan(a.servo["arm_b"]["kp"]), 40., a.servo["arm_b"]["kp"]))
    skills.teaching.Teacher(world, seed=0).fresh({})
    assert (world.model.actuator_gainprm[ids, 0] == 40.).all() and (world.model.actuator_forcerange[ids, 1] == 2.).all()


def test_collects_per_step_errors_never_reuse_an_evaluation_seed():
    """Evaluation draws EVAL_SEED_BASE + 1000k + step; collection's per-step draws start far above any of them."""
    highest_eval = policy.EVAL_SEED_BASE + 1000 * 100 + 100
    lowest_collect = policy.STEP_ERROR_SEED_BASE + 100 * policy.TRAIN_SEED_BASE
    assert lowest_collect > highest_eval
    assert skills.draw_errors(lowest_collect, 4.)["arm_a"].tolist() != skills.draw_errors(lowest_collect + 1, 4.)["arm_a"].tolist()


def test_skill_argv_forwards_cam_jitter_and_compensate_zero():
    import argparse
    ap = argparse.ArgumentParser()
    skills.options(ap)
    args = ap.parse_args(["--skill", "grasp", "--zero-error-deg", "4", "--cam-jitter", "--compensate-zero"])
    forwarded = skills.argv(args)
    assert "--cam-jitter" in forwarded and "--compensate-zero" in forwarded
    _require_mujoco()
    import omx_two_arm_world as tw
    world = tw.World(sites.Layout())
    t = skills.teaching.Teacher(world, seed=3, belt_skew=True)
    skew = t.skew_for()
    assert "jitter" in skew and len(skew["jitter"]) == 3


def test_recover_skips_pass_and_records_only_valid_recoveries(monkeypatch):
    import types
    layout = sites.Layout()
    plan = {"id": "s1", "arm": "arm_b", "container": "c1", "from": "belt", "to": "tmp-b-1"}

    class FakeDs:
        def __init__(self):
            self.saved = self.cleared = 0

        def save_episode(self):
            self.saved += 1

        def clear_episode_buffer(self):
            self.cleared += 1

    class FakeRec:
        def __init__(self, ds):
            self.world = types.SimpleNamespace(layout=layout, pose=lambda d, c: (np.array([0.0, 0.0, 0.1]), 0.0, 0.0))
            self.layout, self.seed, self.pick_vision, self.belt_skew, self.cam_jitter = layout, 7, False, False, False
            self.zero_error, self.servo, self.compensate_zero, self.no_goal = {}, {}, False, True
            self.contacts = {"arm_arm": set(), "arm_other": set(), "pad_neighbour": set()}
            self.carried, self.goal, self.phase, self.privileged, self.count = None, None, "approach", True, 0
            self.dataset, self.longest, self.prompt = ds, {"s1": 10}, ""
            self.goal_during_frames = []

        def fresh(self, here):
            return object()

        def step_gen(self, data, step, others, ctx):
            yield np.zeros(6)
            ctx.phase = "grasp"
            yield np.zeros(6)

        def frame(self, data, targets, label):
            if not self.privileged:
                self.goal_during_frames.append(("prefix", self.goal))
            elif self.goal is not None:
                self.count += 1
                self.goal_during_frames.append(("recover", self.goal))

    driver = types.SimpleNamespace(longest={"s1": 10}, has_goal=False, policy=types.SimpleNamespace(reset=lambda: None),
                                   act=lambda *a: np.zeros(12, np.float32))
    monkeypatch.setattr(policy, "observe", lambda *a: (np.zeros(12, np.float32), {}))
    monkeypatch.setattr(policy, "goal_vector", lambda *a: np.ones(policy.GOAL_SIZE, np.float32))
    monkeypatch.setattr(skills, "recovery_gen", lambda *a: iter([np.ones(6), np.ones(6)]))
    monkeypatch.setattr(skills.teaching.Teacher, "fresh", lambda self, h: object())

    # Case 1: passing step skips recovery completely
    ds = FakeDs()
    monkeypatch.setattr(skills, "step", lambda *a, **kw: {"result": "pass"})
    assert skills.recover(driver, FakeRec(ds), plan, {"c1": "belt"}, "grasp")["dagger_status"] == "passed_skip"
    assert ds.saved == 0 and ds.cleared == 0

    # Case 2: failing step saves only recovery frames (prefix frames had goal=None)
    rec = FakeRec(ds)
    monkeypatch.setattr(skills, "step", lambda *a, **kw: {"result": "fail"})
    monkeypatch.setattr(skills, "_judge_step", lambda *a, **kw: {"result": "pass"})
    out = skills.recover(driver, rec, plan, {"c1": "belt"}, "grasp", prefix_frames=3)
    assert out["dagger_status"] == "recovered" and ds.saved == 1 and ds.cleared == 0
    assert rec.goal_during_frames[:3] == [("prefix", None)] * 3 and rec.goal_during_frames[3:] == [("recover", True)] * 2

    # Case 3: failed recovery clears buffer
    monkeypatch.setattr(skills, "_judge_step", lambda *a, **kw: {"result": "fail"})
    out_fail = skills.recover(driver, rec, plan, {"c1": "belt"}, "grasp", prefix_frames=2)
    assert out_fail["dagger_status"] == "recovery_failed" and ds.saved == 1 and ds.cleared == 1

    # Case 4: adaptive pre-contact backoff (`first_bad_subframe`), seed diversification & retry fallback
    assert skills._candidate_prefixes("auto", {"first_bad_subframe": 14}, 30) == [9, 4]
    assert skills._candidate_prefixes("20", {"first_bad_subframe": 12}, 30) == [7]
    assert skills._candidate_prefixes("auto", {}, 36) == [24, 15]
    assert skills._candidate_prefixes("auto", {}, 40, seed=1)[0] == 24
    assert skills._candidate_prefixes("auto", {}, 40, seed=2)[0] == 30
    rec_auto = FakeRec(ds)
    attempts = []

    def judge_second_pass(r, *a):
        attempts.append(len([x for x in r.goal_during_frames if x[0] == "prefix"]))
        return {"result": "pass" if len(attempts) == 2 else "fail"}

    monkeypatch.setattr(skills, "step", lambda *a, **kw: {"result": "fail", "first_bad_subframe": 12})
    monkeypatch.setattr(skills, "_judge_step", judge_second_pass)
    monkeypatch.setattr(skills, "recovery_gen", lambda *a: iter([np.ones(6), np.ones(6)]))
    out_auto = skills.recover(driver, rec_auto, plan, {"c1": "belt"}, "grasp", prefix_frames="auto")
    assert out_auto["dagger_status"] == "recovered" and out_auto["dagger_prefix_frames"] == 0 and ds.saved == 2


def test_mujoco_recovery_gen_grasp_recovers_after_drifted_prefix():
    _require_mujoco()
    import omx_two_arm_tasks as tasks
    import omx_two_arm_world as tw

    layout = sites.Layout()
    world = tw.World(layout)
    task = tasks.get_task(layout, "stack")
    plan = task["steps"][0]
    here = dict(task["start"])
    others = {k: v for k, v in here.items() if k != plan["container"]}
    idle = {o: layout.sim_arms[o].wait for o in layout.arms if o != plan["arm"]}
    t = skills.teaching.Teacher(world, seed=1003)
    skills.disturb(t, 1003, 4., True)
    data = t.fresh(here)
    before = {o: world.pose(data, o) for o in others}
    gen = t.step_gen(data, plan, others, t)
    t.privileged = True
    target = next(gen)
    while t.phase not in skills.SKILLS["grasp"]["phases"]:
        t.frame(data, {plan["arm"]: target, **idle}, plan["id"])
        target = next(gen)
    start_z = world.pose(data, plan["container"])[0][2]
    t.privileged = False
    drifted = target.copy()
    drifted[0] += 0.20
    drifted[1] += 0.10
    for _ in range(15):
        t.frame(data, {plan["arm"]: drifted, **idle}, plan["id"])
    t.privileged = True
    for rec_target in skills.recovery_gen(t, data, plan, others, "grasp"):
        t.frame(data, {plan["arm"]: rec_target, **idle}, plan["id"])
    verdict = skills._judge_step(t, data, plan, {"step": plan["id"]}, before, start_z, "grasp")
    assert verdict["result"] == "pass", verdict


def test_omx_arm_joint1_aligns_with_base_plate_pedestal_and_hides_duplicate_plate():
    _require_mujoco()
    import mujoco
    import omx_two_arm_world as tw

    w = tw.World()
    data = w.reset()
    mujoco.mj_forward(w.model, data)
    for arm, p in tw.PREFIX.items():
        base_xy = np.asarray(w.layout.arms[arm].base[:2], float)
        j1_xyz, _, _ = w.layout.arms[arm].frames(w.layout.arms[arm].home)
        assert np.allclose(j1_xyz[0][:2], base_xy, atol=1e-6)
        b1_id = w.model.body(f"{p}link1").id
        assert np.allclose(data.xpos[b1_id, :2], base_xy, atol=1e-6)
        for gname in (f"{p}plate", f"{p}bridge"):
            gid = w.model.geom(gname).id
            origin_xy = w.model.geom_pos[gid, :2] - w.model.mesh_pos[w.model.geom_dataid[gid], :2]
            assert np.allclose(origin_xy, base_xy, atol=1e-5)
        b0_id = w.model.body(f"{p}link0").id
        m11_id = w.model.geom(f"{p}m11").id
        assert w.model.geom_rgba[m11_id, 3] == pytest.approx(1.0)
        for gid in range(w.model.ngeom):
            if w.model.geom_bodyid[gid] == b0_id and gid != m11_id:
                assert w.model.geom_rgba[gid, 3] == pytest.approx(0.0)
                assert w.model.geom_contype[gid] == 0 and w.model.geom_conaffinity[gid] == 0


def test_servo_compensator_skips_zero_est_when_privileged_and_release_settles(monkeypatch):
    import types
    import omx_real2sim_comp as r2s_comp

    layout = sites.Layout()
    park_frames = []
    plan = {"id": "s1", "arm": "arm_b", "container": "bar-1", "from": "belt", "to": "ship-h1r1-l0"}
    fake_t = types.SimpleNamespace(
        privileged=True, phase="approach", carried="bar-1",
        zero_error={"arm_a": np.append(np.full(5, 0.02), 0.0), "arm_b": np.append(np.full(5, 0.04), 0.0)},
        zero_center=skills.zero_error_center(physics=True), compensate_zero=True,
        servo_comp=types.SimpleNamespace(zero_est={"arm_a": np.full(5, 0.02), "arm_b": np.full(5, 0.04)}),
        contacts={"arm_arm": set(), "arm_other": set(), "pad_neighbour": set()},
        disturbed=lambda *a: [],
        step_gen=lambda *a: iter([np.zeros(6), np.ones(6)]),
    )
    ze_obs, ze_bias = skills._policy_zero(fake_t)
    assert np.allclose(ze_obs["arm_a"], 0.0)
    assert np.allclose(ze_obs["arm_b"], ze_bias["arm_b"]) and ze_bias["arm_b"][0] > 0.0

    def fake_frame(_d, targets, _lbl):
        if fake_t.phase == "approach":
            fake_t.phase = "lower"
        elif fake_t.phase == "park":
            park_frames.append((fake_t.carried, targets["arm_b"].copy()))

    fake_t.frame = fake_frame
    fake_w = types.SimpleNamespace(pose=lambda *a: (np.zeros(3), 0.0, 0.0))
    drv = types.SimpleNamespace(
        kind="act", world=fake_w, layout=layout, longest={"s1": 2}, has_goal=False,
        policy=types.SimpleNamespace(reset=lambda: None), act=lambda *a: np.full(12, 0.25, np.float32),
    )
    monkeypatch.setattr(policy, "observe", lambda *a: (np.zeros(12, np.float32), {}))
    monkeypatch.setattr(skills, "_judge_step", lambda *a: {"result": "pass"})
    res = skills.step(drv, fake_t, object(), plan, {}, "release")
    assert res["result"] == "pass" and len(park_frames) == round(0.7 * skills.teaching.FPS)
    assert all(c is None and np.allclose(cmd, 0.25 + ze_bias["arm_b"]) for c, cmd in park_frames)

    _require_mujoco()
    import omx_two_arm_world as tw

    w = tw.World()
    data = w.reset()
    comp = r2s_comp.ServoCompensator(w, skills.teaching.FPS)
    comp.zero_est["arm_b"] = np.full(5, 0.05)
    t_in = {"arm_b": np.zeros(6)}
    out_priv = comp.apply(data, t_in, privileged=True)["arm_b"]
    comp.reset_arm("arm_b")
    out_unpriv = comp.apply(data, t_in, privileged=False)["arm_b"]
    assert np.allclose(out_priv[:5] - out_unpriv[:5], 0.05, atol=1e-4)



