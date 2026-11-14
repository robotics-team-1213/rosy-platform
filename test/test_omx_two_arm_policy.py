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
    fake_factory.make_pre_post_processors = lambda cfg, pretrained_path=None: (lambda b: b, lambda y: y)
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
    monkeypatch.setattr(policy.skills, "disturb", lambda *a, **k: None)
    monkeypatch.setattr(policy.teaching.Teacher, "run_task", lambda *a, **k: None)

    policy.collect([0], ["stack"], tmp_path / "ds", no_goal=True)
    assert policy.GOAL not in created["features"] and "observation.state" in created["features"]

    ds = FakeDataset(created["features"])
    rec = policy.Recorder(types.SimpleNamespace(layout=sites.Layout()), ds, {}, no_goal=True)
    rec.goal = True
    monkeypatch.setattr(helpers, "observe", lambda *a: (np.zeros(12, dtype=np.float32), {"top": np.zeros((4, 4, 3), dtype=np.uint8)}))
    monkeypatch.setattr(policy.teaching.Teacher, "frame", lambda *a: None)
    rec.frame(None, {arm: np.zeros(6, dtype=np.float32) for arm in sites.ARMS}, "s1")
    assert len(ds.frames) == 1 and policy.GOAL not in ds.frames[0] and "observation.state" in ds.frames[0]
