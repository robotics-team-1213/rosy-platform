"""Two-arm ACT tool: what the plan tells the model, and how a round's score is counted. No MuJoCo needed."""
import json
from pathlib import Path
import sys
import types

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_policy as policy  # noqa: E402
import omx_two_arm_policy_helpers as helpers  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402


def test_every_plan_step_gets_its_own_goal():
    """Only the top camera's picture could otherwise tell the model which plan step it is on."""
    layout = sites.Layout()
    steps, goals = [], []
    for name in policy.TASKS:
        task = tasks.get_task(layout, name)
        here = dict(task.get("start", {}))
        for step in task["steps"]:
            steps.append(step)
            goals.append(policy.goal_vector(layout, step, {k: v for k, v in here.items() if k != step["container"]}))
            here[step["container"]] = step["to"]
    goals = np.array(goals)
    assert goals.shape == (len(steps), policy.GOAL_SIZE)
    assert len({goal.tobytes() for goal in goals}) == len(steps)
    assert all(goal[0] == (step["arm"] == "arm_a") and goal[11] == (step["arm"] == "arm_b") for goal, step in zip(goals, steps))


def test_both_arms_goals_share_one_vector_and_a_waiting_arm_is_zero():
    """Concurrent mode: each frame carries both arms' current steps; an arm between steps has zeros."""
    a, b = np.arange(1, 12, dtype=np.float32), -np.arange(1, 12, dtype=np.float32)
    both = policy.goal_of({"arm_b": b, "arm_a": a})
    assert both.shape == (policy.GOAL_SIZE,) and (both[:11] == a).all() and (both[11:] == b).all()
    assert (policy.goal_of({"arm_b": b})[:11] == 0).all() and (policy.goal_of({}) == 0).all()


def test_a_round_counts_steps_and_keeps_whole_runs_apart():
    rows = [dict(task="stack", step="s1", result="pass", lifted=True), dict(task="stack", step="s1", result="fail", lifted=True), dict(task="stack", step="s2", result="fail", lifted=False)]
    whole = [dict(task="stack", seed=1, total=9, passed=3, completed=False, last={})]
    score = policy.summarise(rows, whole)
    assert (score["n"], score["passed"], score["lifted"]) == (3, 1, 2)
    assert score["per_step"] == {"stack/s1": 1, "stack/s2": 0}
    assert score["whole"] == [dict(task="stack", seed=1, total=9, passed=3, completed=False)]
    assert 0 < score["wilson_low"] < 1 / 3 < score["wilson_high"]


def test_only_finished_tasks_make_a_round_pass():
    """The first real round ran to the end with 0 of 63 steps and read as passed on the screen."""
    assert policy.outcome(dict(whole=[dict(completed=True), dict(completed=True)])) == dict(status="passed")
    for whole in ([dict(completed=True), dict(completed=False)], []):
        assert policy.outcome(dict(whole=whole))["status"] == "failed"

def test_pipeline_stages_connect_mujoco_gazebo_and_isaac_roles():
    layout = sites.Layout(container_colours="multi")
    eval_rows = [
        dict(
            task="stack",
            step="s1",
            container="bar-1",
            arm="arm_b",
            source="belt",
            target="stand_t1_r1",
            result="pass",
            lifted=True,
            belt_skew=dict(dx_mm=6.0, dy_mm=5.0, dyaw_deg=8.0),
            vision_pick=dict(colour="orange", seen_xy=[0.166, 0.169], seen_yaw_deg=-82.0, xy_err_mm=1.2, yaw_err_deg=1.1),
            xy_mm=0.4,
            yaw_deg=0.0,
        )
    ]
    score = policy.summarise(eval_rows, [dict(task="stack", seed=1, total=1, passed=1, completed=True)])
    gazebo_report = dict(failures=[], shape=[240, 320], camera_hz=5.0, stop=dict(accepted=True, cancel_acknowledged=True, travel_before_rad=0.05, travel_after_rad=0.001))
    isaac_report = dict(sha="b" * 40, rows=[dict(id="mujoco-handoff-s1-bar-1", expect="completed", run_id="isaac-01", status="SUCCEEDED", result="completed", matches=True, judgement=dict(result="completed"))])
    stages = policy.pipeline_stages(score, layout, eval_rows, pick_vision=True, belt_skew=True, gazebo_report=gazebo_report, isaac_report=isaac_report)
    assert list(stages)[:2] == ["mujoco", "isaac"]
    assert stages["mujoco"]["status"] == "passed" and stages["mujoco"]["stage_order"] == 1
    assert stages["mujoco"]["role"] == "stage1_geometry_vision_and_act_policy"
    assert stages["mujoco"]["pick_vision"] is True and stages["mujoco"]["belt_skew"] is True
    assert stages["isaac"]["status"] == "passed" and stages["isaac"]["stage_order"] == 2
    assert stages["isaac"]["role"] == "stage2_physx_contact_pad_slip_and_seating"
    assert len(stages["isaac"]["handoff"]["stage_2_isaac"]["single_arm_cases"]) == 1
    assert stages["isaac"]["handoff"]["stage_1_mujoco"]["colours_seen"] == ["orange"]
    assert stages["gazebo"]["status"] == "passed" and stages["gazebo"]["stage_order"] is None
    assert stages["gazebo"]["track"] == "ros2_execution_contract" and stages["gazebo"]["role"] == "ros2_interface_conformance"


seen_overrides = []  # make_pre_post_processors keyword arguments the fake Driver deps received


def _install_fake_driver_deps(monkeypatch, tmp_path, *, input_features, n_action_steps=8, ensemble_coeff=None):
    class FakeTensor:
        device = "cpu"

        def __init__(self, arr):
            self.arr = np.asarray(arr)

        def __getitem__(self, item):
            return FakeTensor(self.arr[item])

        def permute(self, *axes):
            return FakeTensor(np.transpose(self.arr, axes))

        def float(self):
            return FakeTensor(self.arr.astype(np.float32))

        def __truediv__(self, other):
            return FakeTensor(self.arr / other)

        def to(self, _device):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.arr

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.from_numpy = lambda arr: FakeTensor(arr)

    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(json.dumps({"type": "act"}), encoding="utf-8")
    steps_file = tmp_path / "steps.json"
    steps_file.write_text(json.dumps({"longest": {}}), encoding="utf-8")
    seen_batches = []
    seen_overrides.clear()

    class FakePolicy:
        def __init__(self):
            self.config = types.SimpleNamespace(
                temporal_ensemble_coeff=ensemble_coeff, n_action_steps=n_action_steps, chunk_size=100, input_features=input_features
            )

        def to(self, _device):
            return self

        def eval(self):
            return self

        def parameters(self):
            return iter([FakeTensor(np.zeros(1))])

        def select_action(self, batch):
            seen_batches.append(batch)
            return FakeTensor(np.zeros((1, 12), dtype=np.float32))

    fake_act = types.ModuleType("lerobot.policies.act.modeling_act")
    fake_act.ACTPolicy = types.SimpleNamespace(from_pretrained=lambda *a, **k: FakePolicy())
    fake_act.ACTTemporalEnsembler = lambda coeff, chunk: ("ensembler", coeff, chunk)
    fake_factory = types.ModuleType("lerobot.policies.factory")
    fake_factory.make_pre_post_processors = lambda cfg, pretrained_path=None, **kw: seen_overrides.append(kw) or (lambda b: b, lambda y: y)
    fake_world = types.ModuleType("omx_two_arm_world")
    fake_world.World = lambda layout: types.SimpleNamespace(layout=layout)
    for name, mod in {
        "torch": fake_torch,
        "lerobot": types.ModuleType("lerobot"),
        "lerobot.policies": types.ModuleType("lerobot.policies"),
        "lerobot.policies.act": types.ModuleType("lerobot.policies.act"),
        "lerobot.policies.act.modeling_act": fake_act,
        "lerobot.policies.factory": fake_factory,
        "omx_two_arm_world": fake_world,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return model_dir, steps_file, seen_batches


def test_driver_preserves_checkpoint_ensemble_and_detects_goal_feature(monkeypatch, tmp_path):
    """D-1032: default Driver must not force temporal_ensemble_coeff=.01 and only sends GOAL when expected."""
    model_dir, steps_file, seen = _install_fake_driver_deps(monkeypatch, tmp_path, input_features={"observation.state": {}})
    d_default = policy.Driver(model_dir, steps_file)
    assert d_default.policy.config.temporal_ensemble_coeff is None
    assert d_default.policy.config.n_action_steps == 8
    assert not hasattr(d_default.policy, "temporal_ensembler")
    assert d_default.has_goal is False

    state = np.zeros(12, dtype=np.float32)
    images = {"top": np.zeros((4, 4, 3), dtype=np.uint8)}
    out = d_default.act(state, images, goal=None)
    assert out.shape == (12,) and policy.GOAL not in seen[-1]

    d_core = policy.Driver(model_dir, steps_file, n_action_steps=1)
    assert d_core.policy.config.temporal_ensemble_coeff is None and d_core.policy.config.n_action_steps == 1

    d_ens = policy.Driver(model_dir, steps_file, ensemble_coeff=0.01)
    assert d_ens.policy.config.temporal_ensemble_coeff == 0.01 and d_ens.policy.config.n_action_steps == 1
    assert d_ens.policy.temporal_ensembler == ("ensembler", 0.01, 100)


def test_driver_smolvla_honors_action_and_flow_steps_and_amp(monkeypatch, tmp_path):
    model_dir, steps_file, _ = _install_fake_driver_deps(monkeypatch, tmp_path, input_features={"observation.state": {}})
    (model_dir / "config.json").write_text(json.dumps({"type": "smolvla"}), encoding="utf-8")

    class FakeSmolPolicy:
        def __init__(self):
            self.config = types.SimpleNamespace(n_action_steps=1, num_steps=10, use_amp=True, input_features={"observation.state": {}})
        def to(self, _d):
            return self
        def eval(self):
            return self
        def parameters(self):
            return iter([types.SimpleNamespace(device="cuda")])
        def select_action(self, _b):
            class _Arr:
                def cpu(self): return self
                def numpy(self): return np.zeros((1, 12), dtype=np.float32)
            return _Arr()

    fake_smol = types.ModuleType("lerobot.policies.smolvla.modeling_smolvla")
    fake_smol.SmolVLAPolicy = types.SimpleNamespace(from_pretrained=lambda *a, **k: FakeSmolPolicy())
    monkeypatch.setitem(sys.modules, "lerobot.policies.smolvla", types.ModuleType("lerobot.policies.smolvla"))
    monkeypatch.setitem(sys.modules, "lerobot.policies.smolvla.modeling_smolvla", fake_smol)
    d = policy.Driver(model_dir, steps_file, n_action_steps=8, flow_steps=5, use_amp=True)
    assert (d.kind, d.policy.config.n_action_steps, d.policy.config.num_steps, d.use_amp) == ("smolvla", 8, 5, True)
    assert d.act(np.zeros(12, dtype=np.float32), {"top": np.zeros((4, 4, 3), dtype=np.uint8)}).shape == (12,)


def test_driver_requires_and_forwards_goal_when_model_expects_it(monkeypatch, tmp_path):
    model_dir, steps_file, seen = _install_fake_driver_deps(
        monkeypatch, tmp_path, input_features={"observation.state": {}, policy.GOAL: {}}
    )
    driver = policy.Driver(model_dir, steps_file)
    assert driver.has_goal is True
    state = np.zeros(12, dtype=np.float32)
    images = {"top": np.zeros((4, 4, 3), dtype=np.uint8)}
    with pytest.raises(ValueError, match="goal"):
        driver.act(state, images, goal=None)
    driver.act(state, images, goal=np.ones(policy.GOAL_SIZE, dtype=np.float32))
    assert policy.GOAL in seen[-1]


def test_collect_no_goal_omits_environment_state_feature(monkeypatch, tmp_path):
    """D-1032: --no-goal excludes sim-only observation.environment_state(22) from dataset schema and frames."""
    created = {}

    class FakeDataset:
        def __init__(self, features):
            created["features"] = features
            self.frames = []

        def add_frame(self, row):
            self.frames.append(row)

        def save_episode(self):
            pass

        def clear_episode_buffer(self):
            pass

        def finalize(self):
            pass

    fake_ds = types.ModuleType("lerobot.datasets.lerobot_dataset")
    fake_ds.LeRobotDataset = types.SimpleNamespace(create=lambda *a, features=None, **k: FakeDataset(features))
    fake_world = types.ModuleType("omx_two_arm_world")
    fake_world.JOINTS = ["j1", "j2", "j3", "j4", "j5", "j6"]
    fake_world.FPS = 15
    fake_world.World = lambda layout: types.SimpleNamespace(layout=layout)
    for name, mod in {
        "lerobot": types.ModuleType("lerobot"),
        "lerobot.datasets": types.ModuleType("lerobot.datasets"),
        "lerobot.datasets.lerobot_dataset": fake_ds,
        "omx_two_arm_world": fake_world,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    calls = []
    monkeypatch.setattr(policy.skills, "disturb", lambda *a, **k: None)
    monkeypatch.setattr(policy.teaching.Teacher, "run_task", lambda self, task, isolated=False, **k: calls.append(isolated))

    policy.collect([0], ["stack"], tmp_path / "ds", no_goal=True)
    assert calls == [False]
    assert policy.GOAL not in created["features"] and "observation.state" in created["features"]

    policy.collect([0], ["stack"], tmp_path / "ds_skill", skill="grasp", no_goal=True)
    assert calls == [False, True]

    ds = FakeDataset(created["features"])
    rec = policy.Recorder(types.SimpleNamespace(layout=sites.Layout()), ds, {}, no_goal=True)
    rec.goal = True
    monkeypatch.setattr(helpers, "observe", lambda *a: (np.zeros(12, dtype=np.float32), {"top": np.zeros((4, 4, 3), dtype=np.uint8)}))
    monkeypatch.setattr(policy.teaching.Teacher, "frame", lambda *a: None)
    rec.frame(None, {arm: np.zeros(6, dtype=np.float32) for arm in sites.ARMS}, "s1")
    assert len(ds.frames) == 1 and policy.GOAL not in ds.frames[0] and "observation.state" in ds.frames[0]


def test_evaluate_forwards_flow_steps_and_amp(monkeypatch, tmp_path):
    calls = []

    class FakeDriver:
        kind = "smolvla"

        def __init__(self, model, steps_file, choices, **kw):
            calls.append((model, steps_file, kw))

    fake_av = types.ModuleType("av")
    monkeypatch.setitem(sys.modules, "av", fake_av)
    monkeypatch.setattr(policy, "Driver", FakeDriver)
    monkeypatch.setattr(policy.skills, "isolated", lambda *a, **kw: calls.append(("isolated", kw)) or [])
    out = tmp_path / "eval.json"
    rc = policy.main(["evaluate", "--model", "m", "--steps-file", "s", "--tasks", "stack", "--skill", "grasp",
                      "--isolated-seeds", "1", "--flow-steps", "5", "--amp", "--n-action-steps", "8",
                      "--cam-jitter", "--compensate-zero", "--zero-est-noise-deg", "0.5",
                      "--out", str(out), "--artifacts", str(tmp_path / "art")])
    assert rc == 0 and json.loads(out.read_text(encoding="utf-8"))["policy"] == "smolvla"
    assert calls[0][2]["flow_steps"] == 5 and calls[0][2]["use_amp"] is True and calls[0][2]["n_action_steps"] == 8
    assert calls[0][2]["cam_jitter"] is True and calls[1] == ("isolated", {"compensate_zero": True, "zero_est_noise_deg": .5})
    assert helpers.resolved_choices({"arm_bases": "measured-194"}, cam_jitter=True)["arm_bases"] == "measured-194"
    assert "wrist_camera" in helpers.resolved_choices({}, cam_jitter=True)


def test_collect_and_round_forward_dagger_and_extra_dataset(monkeypatch, tmp_path):
    round_dir = tmp_path / "r0"
    ckpt = round_dir / "train/checkpoints/005000/pretrained_model"
    ckpt.mkdir(parents=True)
    (round_dir / "steps.json").write_text(json.dumps({"longest": {"s1": 42}, "spoiled": []}), encoding="utf-8")

    fake_ds = types.ModuleType("lerobot.datasets.lerobot_dataset")
    fake_ds.LeRobotDataset = types.SimpleNamespace(create=lambda *a, **kw: types.SimpleNamespace(finalize=lambda: None))
    fake_world = types.ModuleType("omx_two_arm_world")
    fake_world.JOINTS, fake_world.FPS, fake_world.World = ("j1", "j2", "j3", "j4", "j5", "jaw"), 20, lambda layout: types.SimpleNamespace(layout=layout)
    for name, mod in {
        "lerobot": types.ModuleType("lerobot"),
        "lerobot.datasets": types.ModuleType("lerobot.datasets"),
        "lerobot.datasets.lerobot_dataset": fake_ds,
        "omx_two_arm_world": fake_world,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    seen_driver, recover_calls, nominal_calls = [], [], []

    from contextlib import nullcontext

    class FakeDriver:
        torch = types.SimpleNamespace(inference_mode=nullcontext)

        def __init__(self, model, steps_file, choices, **kw):
            seen_driver.append((model, Path(steps_file), kw))
            self.world = types.SimpleNamespace(layout=sites.Layout(**helpers.resolved_choices(choices)))

    monkeypatch.setattr(helpers, "Driver", FakeDriver)
    monkeypatch.setattr(helpers.skills, "disturb", lambda *a, **kw: None)
    monkeypatch.setattr(helpers.teaching.Teacher, "run_task", lambda *a, **kw: nominal_calls.append(1))
    monkeypatch.setattr(helpers.skills, "recover", lambda drv, rec, plan, here, skill, prefix_frames="auto": recover_calls.append((plan["id"], prefix_frames, rec.compensate_zero)) or {"dagger_status": "recovered", "result": "pass"})

    (round_dir / "eval.json").write_text(json.dumps({"rows": [
        {"task": "stack", "step": "s1", "result": "pass"},
        {"task": "stack", "step": "s2", "result": "fail"},
        {"task": "stack", "step": "s3", "result": "fail"},
    ]}), encoding="utf-8")
    out = tmp_path / "dag_ds"
    rc = policy.main(["collect", "--seeds", "10", "--tasks", "stack", "--out", str(out), "--skill", "grasp",
                      "--compensate-zero", "--n-action-steps", "8", "--flow-steps", "5", "--amp",
                      "--dagger-model", str(ckpt), "--dagger-prefix-frames", "12", "--dagger-eval-file", "auto",
                      "--dagger-only", "--dagger-device", "cpu"])
    assert rc == 0 and seen_driver[0][1] == round_dir / "steps.json" and seen_driver[0][2]["device"] == "cpu"
    assert seen_driver[0][2]["n_action_steps"] == 8 and seen_driver[0][2]["flow_steps"] == 5 and seen_driver[0][2]["use_amp"] is True
    assert nominal_calls == [] and [sid for sid, _, _ in recover_calls] == ["s2", "s3"]
    assert all(pf == "12" and cz is True for _, pf, cz in recover_calls)
    steps_meta = json.loads((tmp_path / "dag_ds.steps.json").read_text(encoding="utf-8"))
    assert steps_meta["longest"]["s1"] == 42 and steps_meta["dagger"] == {"recovered": 2}

    popens, runs = [], []
    fake_gpu_yield = types.SimpleNamespace(yield_turn=lambda **kw: None)
    monkeypatch.setattr(policy, "gpu_yield", fake_gpu_yield)
    monkeypatch.setattr(policy.ladder, "require_gpu", lambda *a: None)
    monkeypatch.setattr(policy, "train", lambda cmd, *a, **kw: runs.append(("train", cmd)))

    def fake_popen(cmd, **kw):
        popens.append(cmd)
        part = Path(cmd[cmd.index("--out") + 1])
        (part.parent / f"{part.name}.steps.json").write_text(json.dumps({"longest": {"s1": 42}, "spoiled": [], "episodes": 0, "dagger": {"passed_skip": 9}}), encoding="utf-8")
        return types.SimpleNamespace(wait=lambda: 0)

    def fake_run(cmd, **kw):
        runs.append(("run", cmd))
        if len(cmd) > 2 and cmd[2] == "evaluate":
            out_eval = Path(cmd[cmd.index("--out") + 1])
            out_eval.write_text(json.dumps({"rows": [{"task": "stack", "step": "s1", "result": "pass", "lifted": True, "seed": 200000}], "whole": []}), encoding="utf-8")
        if any("aggregate_datasets" in str(c) for c in cmd):
            ds_root = Path(cmd[3])
            (ds_root / "meta").mkdir(parents=True, exist_ok=True)
            (ds_root / "meta/info.json").write_text(json.dumps({"total_episodes": 12, "total_frames": 900}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="deadbeef")

    monkeypatch.setattr(policy.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(policy.subprocess, "run", fake_run)
    monkeypatch.setattr(policy.shutil, "rmtree", lambda *a, **kw: None)
    rc_round = policy.main(["round", "--root", str(tmp_path / "rroot"), "--lerobot-train", "lerobot-train",
                            "--tasks", "stack", "--seeds", "1", "--workers", "1", "--skill", "grasp", "--zero-error-deg", "4",
                            "--n-action-steps", "8", "--flow-steps", "5", "--amp",
                            "--dagger-model", str(ckpt), "--dagger-eval-file", "auto", "--dagger-only", "--dagger-device", "cpu",
                            "--extra-dataset", str(tmp_path / "base_ds"), "--base-model", str(ckpt)])
    assert rc_round == 0
    assert "--dagger-model" in popens[0] and "--dagger-eval-file" in popens[0] and "--flow-steps" in popens[0]
    eval_cmds = [cmd for kind, cmd in runs if kind == "run" and len(cmd) > 2 and cmd[2] == "evaluate"]
    assert any("eval-comp.json" in str(c) for cmd in eval_cmds for c in cmd)
    aggr_cmd = next(cmd for kind, cmd in runs if kind == "run" and any("aggregate_datasets" in str(c) for c in cmd))
    assert str(tmp_path / "base_ds") in aggr_cmd and not any("part0" in str(c) for c in aggr_cmd)
    train_cmd = next(cmd for kind, cmd in runs if kind == "train")
    assert f"--policy.pretrained_path={ckpt}" in train_cmd


def test_train_early_stops_when_checkpoint_solves_problem(monkeypatch, tmp_path):
    out = tmp_path / "train"
    ckpt_dir = out / "checkpoints/last/pretrained_model"
    ckpt_dir.mkdir(parents=True)
    (out / "checkpoints/001500").mkdir(parents=True)
    (out / "checkpoints/003000").mkdir(parents=True)

    stopped_pids, seen_steps, steps_seq = [], [], iter([1500, 3000, 3000])
    fake_proc = types.SimpleNamespace(pid=99999, returncode=-15, poll=lambda: None if not stopped_pids else -15)
    monkeypatch.setattr(policy, "TRAIN_POLL_S", 0.0)
    monkeypatch.setattr(policy, "checkpoint_step", lambda _o: next(steps_seq, 3000))
    monkeypatch.setattr(policy.gpu_yield, "wait_vram", lambda *a, **kw: None)
    monkeypatch.setattr(policy.gpu_yield, "alone_waiting", lambda: False)
    monkeypatch.setattr(policy.subprocess, "Popen", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(policy, "stop", lambda tr: stopped_pids.append(tr.pid))

    with (tmp_path / "train.log").open("w", encoding="utf-8") as log:
        solved_step = policy.train(
            ["lerobot-train"], out, "lerobot-train", log, {},
            early_stop_fn=lambda step, p: seen_steps.append((step, p.name)) or step >= 3000,
        )
    assert solved_step == 3000 and stopped_pids == [99999]
    assert seen_steps == [(3000, "pretrained_model")]
    assert not (out / "checkpoints/001500").exists() and (out / "checkpoints/003000").exists()


def test_driver_concurrent_gates_on_sweeps_clear_and_resets_policy_on_step_change(monkeypatch):
    from contextlib import nullcontext
    import omx_two_arm_plan as plan_mod

    layout = sites.Layout()
    fake_world = types.SimpleNamespace(
        layout=layout,
        put=lambda *a, **kw: None,
        pose=lambda _d, _c: (np.array([0.0, 0.0, 0.05]), 0.0, 0.0),
    )
    resets, sweep_checks = [], []

    class FakeTeacher:
        def __init__(self, *a, **kw):
            self.belt_skew = False

        def fresh(self, _here):
            return object()

        def frame(self, _d, _targets, _lbl, _ctxs):
            pass

        def verdict(self, _d, _s, row, _before, _ctx):
            return dict(row, result="pass")

        def off_stand(self, *_a):
            pass

    drv = object.__new__(helpers.Driver)
    drv.layout, drv.world = layout, fake_world
    drv.pick_vision = drv.belt_skew = drv.cam_jitter = drv.has_goal = False
    drv.torch = types.SimpleNamespace(inference_mode=nullcontext)
    drv.longest = {"t/s1": {"frames": 2, "picked": 1}, "t/s2": {"frames": 2, "picked": 1}}
    drv.policy = types.SimpleNamespace(reset=lambda: resets.append(1))
    drv.act = lambda *a: np.zeros(12, np.float32)

    monkeypatch.setattr(helpers.teaching, "Teacher", FakeTeacher)
    monkeypatch.setattr(helpers, "observe", lambda *a: (np.zeros(12, np.float32), {}))
    monkeypatch.setattr(plan_mod, "step_swept_poses", lambda *a: [(0.0, []), (1.0, [])])
    monkeypatch.setattr(plan_mod, "sweeps_clear", lambda a, b: sweep_checks.append((len(a), len(b))) or len(sweep_checks) > 1)

    task = {
        "name": "t",
        "start": {"c1": "ship-h1r0-l0", "c2": "ship-h1r2-l0"},
        "steps": [
            {"id": "s1", "arm": "arm_a", "container": "c1", "from": "ship-h1r0-l0", "to": "tmp-a-1", "zones": [["a"], ["a"]]},
            {"id": "s2", "arm": "arm_b", "container": "c2", "from": "ship-h1r2-l0", "to": "tmp-b-1", "zones": [["b"], ["b"]]},
        ],
    }
    rows, summary = drv.concurrent(task, seed=0)
    assert summary["completed"] is True and len(rows) == 2
    assert len(sweep_checks) >= 2 and len(resets) >= 3



def test_site_goal_names_the_source_and_target_an_admitted_job_carries():
    """2026-11-17 panel: `--goal site` tells ACT which container (source site) and where (target site) without the IK joints."""
    layout = sites.Layout()
    names, size = helpers.site_names(layout), helpers.goal_size(layout, "site")
    assert size == 2 * (1 + 2 * len(names))
    task = tasks.get_task(layout, "cell-stack")
    here, seen = dict(task.get("start", {})), set()
    for step in task["steps"]:
        goal = policy.goal_vector(layout, step, here, "site")
        half = size // 2
        mine, other = (goal[:half], goal[half:]) if step["arm"] == "arm_a" else (goal[half:], goal[:half])
        assert goal.shape == (size,) and not other.any() and mine.sum() == 3 and mine[0] == 1
        assert mine[1 + names.index(step["from"])] == 1 and mine[1 + len(names) + names.index(step["to"])] == 1
        seen.add(goal.tobytes())
        here[step["container"]] = step["to"]
    assert len(seen) == len(task["steps"])  # cell-stack picks among standing containers: each step is told apart
    with pytest.raises(ValueError, match="goal mode"):
        helpers.goal_block(layout, task["steps"][0], here, "metres")


def test_driver_reads_the_goal_mode_from_the_checkpoint_width(monkeypatch, tmp_path):
    layout = sites.Layout()
    width = helpers.goal_size(layout, "site")
    feature = types.SimpleNamespace(shape=(width,))
    model_dir, steps_file, seen = _install_fake_driver_deps(monkeypatch, tmp_path, input_features={"observation.state": {}, policy.GOAL: feature})
    steps_file.write_text(json.dumps({"longest": {}, "goal_mode": "site", "goal_sites": helpers.site_names(layout)}), encoding="utf-8")
    assert policy.Driver(model_dir, steps_file).goal_mode == "site"
    steps_file.write_text(json.dumps({"longest": {}, "goal_sites": ["belt"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="sites"):
        policy.Driver(model_dir, steps_file)
    feature.shape = (policy.GOAL_SIZE,)
    steps_file.write_text(json.dumps({"longest": {}}), encoding="utf-8")
    assert policy.Driver(model_dir, steps_file).goal_mode == "joints"


def test_collect_refuses_site_goal_with_no_goal():
    with pytest.raises(ValueError, match="--goal"):
        helpers.collect([1], ["stack"], "unused", no_goal=True, goal_mode="site")


def test_driver_moves_the_checkpoint_processor_to_its_own_device(monkeypatch, tmp_path):
    """A checkpoint saved on cuda names cuda in its processor; a cpu Driver (evaluate --device cpu, --dagger-device cpu) must override it."""
    model_dir, steps_file, _ = _install_fake_driver_deps(monkeypatch, tmp_path, input_features={"observation.state": {}})
    policy.Driver(model_dir, steps_file, device="cpu")
    assert seen_overrides[-1] == {"preprocessor_overrides": {"device_processor": {"device": "cpu"}},
                                  "postprocessor_overrides": {"device_processor": {"device": "cpu"}}}


def test_an_isolated_collect_drops_only_the_failed_step_and_a_whole_run_drops_the_rest(monkeypatch):
    from types import SimpleNamespace
    for isolated, saved_n in ((True, 2), (False, 1)):
        results, saved, cleared = iter(["pass", "fail", "pass"]), [], []
        monkeypatch.setattr(helpers.teaching.Teacher, "run_step", lambda self, data, step, here: {"result": next(results)})
        rec = helpers.Recorder.__new__(helpers.Recorder)
        rec.dataset = SimpleNamespace(save_episode=lambda: saved.append(1), clear_episode_buffer=lambda: cleared.append(1))
        rec.skill, rec.no_goal, rec.longest, rec.spoiled, rec.failed, rec.isolated, rec.count = None, True, {}, False, [], isolated, 0
        for i in range(3):
            rec.run_step(None, {"id": f"s{i}"}, {})
        assert len(saved) == saved_n and len(cleared) == 3 - saved_n
        assert (rec.failed, rec.spoiled) == ((["s1"], False) if isolated else ([], True))
