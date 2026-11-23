"""A LeRobot checkpoint trained on one real arm is shadowed with the cell's own inputs and never executed (2026-11-18)."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_act_shadow  # noqa: E402
import cell_lerobot_shadow as lrs  # noqa: E402

cv2 = pytest.importorskip("cv2")

CONFIG = {"type": "act",
          "input_features": {"observation.state": {"type": "STATE", "shape": [6]},
                             "observation.images.top": {"type": "VISUAL", "shape": [3, 8, 12]},
                             "observation.images.wrist": {"type": "VISUAL", "shape": [3, 8, 12]}},
          "output_features": {"action": {"type": "ACTION", "shape": [6]}}}


def checkpoint(tmp_path, *, warp=None, config=CONFIG):
    root = tmp_path / "ckpt"
    root.mkdir()
    (root / "config.json").write_text(json.dumps(config))
    (root / "model.safetensors").write_bytes(b"weights")
    if warp is not None:
        (root / "cam_warp.json").write_text(json.dumps(warp))
    return root, hashlib.sha256(b"weights").hexdigest()


class Recorder:
    def __init__(self):
        self.seen = []

    def __call__(self, root, device):
        def predict(obs):
            self.seen.append(obs)
            return np.tile(obs["observation.state"], (3, 1))
        return predict


def bgr(value=(10, 20, 30)):
    return np.tile(np.asarray(value, dtype=np.uint8), (8, 12, 1))


def test_goal_feature_requires_a_valid_slot_or_one_hot(tmp_path):
    config = {**CONFIG, "input_features": {**CONFIG["input_features"], lrs.GOAL: {"shape": [10]}}}
    root, sha = checkpoint(tmp_path, config=config)
    shadow = lrs.LeRobotShadow(root, sha, loader=Recorder())
    frames = {view: bgr() for view in shadow.image_views}
    assert lrs.read_features(config)[2] == 10
    for goal in (None, -1, 10, 2.0, [1] * 10, [1] * 9):
        with pytest.raises(ValueError, match="goal"):
            shadow.inputs([0] * 6, frames, goal=goal)
    for goal in (9, [0] * 9 + [1]):
        obs, meta = shadow.inputs([0] * 6, frames, goal=goal)
        np.testing.assert_array_equal(obs[lrs.GOAL], [0] * 9 + [1])
        assert obs[lrs.GOAL].dtype == np.float32 and meta["goal_slot"] == 9
    with pytest.raises(ValueError, match="one-hot"):
        shadow.inputs([0] * 6, frames, goal=[0] * 10)
    goal = np.asarray([0] * 9 + [1], dtype=np.float32)
    obs, meta = shadow.inputs([0] * 6, frames, goal=goal, mask_goal=True)
    np.testing.assert_array_equal(obs[lrs.GOAL], [0] * 10)
    np.testing.assert_array_equal(goal, [0] * 9 + [1])
    assert meta["goal_slot"] == 9 and meta["goal_masked"] is True
    with pytest.raises(ValueError, match="goal slot"):
        shadow.inputs([0] * 6, frames, goal=10, mask_goal=True)


@pytest.mark.parametrize("arm,roll,gripper,held", [
    ("arm_a", 44.66, 49.18, 53.83),
    ("arm_b", 44.62, 48.86, 53.38),
])
def test_sim_checkpoint_home_round_trip(tmp_path, arm, roll, gripper, held):
    from cell_act_inputs import sim_gripper

    root, sha = checkpoint(tmp_path)
    (root / "UNITS.json").write_text(json.dumps({"state": "sim_rad", "gripper": "sim_jaw", "arm": arm}))
    rule = {"held_30mm": held, "gap_mm_per_unit": 5.0}
    (tmp_path / f"arm-cal-{arm}.json").write_text(json.dumps({"arm_id": arm, **rule}))
    config = {"arm_id": arm, "work_dir": str(tmp_path)}
    with pytest.raises(ValueError, match="arm"):
        lrs.LeRobotShadow(root, sha, loader=Recorder(), cell_config={**config, "arm_id": "arm_s"})
    shadow = lrs.LeRobotShadow(root, sha, loader=Recorder(), cell_config=config)
    home = [0.76, -62.25, 53.06, 51.65, roll, gripper]
    frames = {view: bgr() for view in shadow.image_views}
    obs, _ = shadow.inputs(home, frames)
    assert obs["observation.state"][4] == pytest.approx(1.402, abs=0.01)
    assert obs["observation.state"][5] == pytest.approx(sim_gripper(gripper, rule))
    for actual in (home, [*home[:5], held]):
        obs, _ = shadow.inputs(actual, frames)
        assert shadow.infer(obs, state=actual).chunk[0] == pytest.approx(actual, abs=0.5)


def test_pin_is_the_weights_sha256(tmp_path):
    root, sha = checkpoint(tmp_path)
    with pytest.raises(ValueError, match="differs from the pinned revision"):
        lrs.LeRobotShadow(root, "0" * 64, loader=Recorder())
    assert lrs.LeRobotShadow(root, sha, loader=Recorder()).image_views == {"top": (8, 12), "wrist": (8, 12)}


def test_only_single_arm_act_binds(tmp_path):
    root, sha = checkpoint(tmp_path, config={**CONFIG, "type": "diffusion"})
    with pytest.raises(ValueError, match="only LeRobot ACT"):
        lrs.LeRobotShadow(root, sha, loader=Recorder())


def test_inputs_are_rgb_chw_by_trained_name_and_wrong_size_refuses(tmp_path):
    root, sha = checkpoint(tmp_path)
    rec = Recorder()
    shadow = lrs.LeRobotShadow(root, sha, loader=rec)
    obs, meta = shadow.inputs([1, 2, 3, 4, 5, 6], {"top": bgr(), "wrist": bgr()})
    assert obs["observation.images.top"].shape == (3, 8, 12)
    assert obs["observation.images.top"][:, 0, 0] == pytest.approx(np.array([30, 20, 10]) / 255.0)  # BGR -> RGB
    assert set(meta["model_frame_sha256"]) == {"top", "wrist"} and meta["warp_sha256"] is None
    assert shadow.infer(obs).chunk[0] == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    with pytest.raises(ValueError, match="differs from the trained"):
        shadow.inputs([0] * 6, {"top": np.zeros((16, 12, 3), np.uint8), "wrist": bgr()})
    with pytest.raises(ValueError, match="unavailable"):
        shadow.inputs([0] * 6, {"top": bgr()})
    with pytest.raises(ValueError, match="6 finite"):
        shadow.inputs([0, 0, 0, 0, 0, float("nan")], {"top": bgr(), "wrist": bgr()})


def test_cam_warp_applies_to_its_camera_only(tmp_path):
    warp = {"camera": "top", "matrix": [[1, 0, 2], [0, 1, 0]], "size": [12, 8]}
    root, sha = checkpoint(tmp_path, warp=warp)
    shadow = lrs.LeRobotShadow(root, sha, loader=Recorder())
    frame = np.zeros((8, 12, 3), np.uint8)
    frame[:, 3] = 255
    obs, meta = shadow.inputs([0] * 6, {"top": frame, "wrist": frame})
    assert meta["warp_sha256"] == shadow.warp["sha256"]
    assert obs["observation.images.top"][0, 0, 5] == 1.0 and obs["observation.images.top"][0, 0, 3] == 0.0  # shifted +2 px
    assert obs["observation.images.wrist"][0, 0, 3] == 1.0


def test_cam_warp_for_an_untrained_size_refuses(tmp_path):
    root, sha = checkpoint(tmp_path, warp={"camera": "top", "matrix": [[1, 0, 0], [0, 1, 0]], "size": [640, 480]})
    with pytest.raises(ValueError, match="cam_warp size"):
        lrs.LeRobotShadow(root, sha, loader=Recorder())


def test_non_finite_chunk_refuses(tmp_path):
    root, sha = checkpoint(tmp_path)
    shadow = lrs.LeRobotShadow(root, sha, loader=lambda r, d: (lambda obs: np.full((2, 6), np.nan)))
    obs, _ = shadow.inputs([0] * 6, {"top": bgr(), "wrist": bgr()})
    with pytest.raises(ValueError, match="finite"):
        shadow.infer(obs)


class Cell:
    """Reads only: a wrist frame and the runner state. Any other call is a test failure."""

    def __init__(self):
        self.calls = []

    def frame(self, view):
        self.calls.append(("frame", view))
        return bgr((1, 2, 3))

    def act(self, verb):
        self.calls.append(("act", verb))
        assert verb == "state"
        return {"state": [18.0, -31.0, 27.0, 48.0, 68.0, 49.0]}


def test_capture_row_uses_the_plan_frame_for_top_and_reads_only(tmp_path):
    root, sha = checkpoint(tmp_path)
    shadow = cell_act_shadow.Shadow(lrs.LeRobotShadow(root, sha, loader=Recorder()), tmp_path, None, lerobot=True)
    cell = Cell()
    row = shadow.capture(cell, {"cameras": {}}, 3, bgr((9, 9, 9)))
    assert "error" not in row, row.get("error")
    assert cell.calls == [("frame", "wrist"), ("act", "state")]
    assert row["policy_id"] == sha and row["policy_environment"] == "real_lerobot"
    assert row["observation"]["unit"] == "lerobot_norm" and len(row["proposed"]) == 3
    assert row["observation"]["joint_names"] == list(lrs.JOINT_NAMES)
    shadow.record(row, "a-1", "placed", 1.0)
    logged = json.loads((tmp_path / "act-shadow.jsonl").read_text().splitlines()[0])
    assert logged["ik"]["outcome"] == "placed"


def test_load_routes_lerobot_kind_and_keeps_failures_in_the_row(tmp_path):
    shadow = cell_act_shadow.load({"act_shadow": {"kind": "lerobot", "policy_root": str(tmp_path / "missing"),
                                                  "policy_revision": "rev"}}, tmp_path)
    row = shadow.capture(Cell(), {"cameras": {}}, 0, bgr())
    assert row["policy_id"] == "rev" and "FileNotFoundError" in row["error"]


def test_cell_quality_reports_the_pinned_shadow_model_and_never_grants_execution(tmp_path):
    import cell_camera_telemetry_sync as sync

    root, sha = checkpoint(tmp_path, warp={"camera": "top", "matrix": [[1, 0, 0], [0, 1, 0]], "size": [12, 8]})
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "cell-auto-arm-s-live.json").write_text(json.dumps(
        {"work_dir": str(work), "act_shadow": {"kind": "lerobot", "policy_root": str(root), "policy_revision": sha}}))
    (tmp_path / "cell-auto-arm-s-live.json.bak-1").write_text("{}")  # backups are not configs
    rows = [{"policy_id": "older", "ik": {"outcome": "placed"}},
            {"policy_id": sha, "proposed": [[0] * 6], "ik": {"outcome": "placed"}},
            {"policy_id": sha, "error": "ValueError: camera 'wrist' unavailable", "ik": {"outcome": "empty"}}]
    (work / "act-shadow.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    model = sync._collect_arm_models(tmp_path)["arm_s"]
    assert model["name"] == "ckpt" and model["policy_revision"] == sha and model["binding"] == "lerobot"
    assert model["execution_allowed"] is False and model["block_reason"]
    assert model["warp_sha256"] == hashlib.sha256((root / "cam_warp.json").read_bytes()).hexdigest()
    assert model["shadow"]["rows"] == 2 and model["shadow"]["errors"] == 1
    assert model["shadow"]["last_ik_outcome"] == "empty" and "wrist" in model["shadow"]["last_error"]
    assert len(model["block_reason"]) <= 200 and len(model["name"]) <= 128  # Fleet nulls longer strings

    sent = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, **kwargs):
        if request.full_url.endswith("/cell-quality"):
            sent.append(json.loads(request.data))
            return Reply()
        raise OSError("no local viewer")

    sync.sync_cell_telemetry("https://fleet.test", "token", prep_dir=tmp_path, urlopen_fn=fake_urlopen)
    assert sent and sent[0]["arm_models"]["arm_s"]["policy_revision"] == sha


def test_cell_quality_has_no_model_without_act_shadow(tmp_path):
    import cell_camera_telemetry_sync as sync

    (tmp_path / "cell-auto-arm-s-live.json").write_text(json.dumps({"work_dir": str(tmp_path)}))
    assert sync._collect_arm_models(tmp_path) == {"arm_s": {}, "arm_a": {}, "arm_b": {}}


def test_shadow_offset_maps_cell_state_to_model_units_and_back(tmp_path):
    root, sha = checkpoint(tmp_path)
    rec = Recorder()
    shadow = cell_act_shadow.Shadow(lrs.LeRobotShadow(root, sha, loader=rec), tmp_path, None, lerobot=True,
                                    offset=[0, 0, 0, 0, 46.7, 0])
    row = shadow.capture(Cell(), {"cameras": {}}, 0, bgr())
    assert rec.seen[0]["observation.state"][4] == pytest.approx(68.0 + 46.7)
    assert row["proposed"][0][4] == pytest.approx(68.0)  # back in cell units


def test_checkpoint_camera_names_must_be_cell_roles():
    # 2026-11-21: Purple-SY named the side camera "top" and the overhead D435 "rs"
    config = {"type": "act", "input_features": {"observation.state": {"shape": [6]}, "observation.images.rs": {"shape": [3, 480, 640]}},
              "output_features": {"action": {"shape": [6]}}}
    with pytest.raises(ValueError, match="not cell roles"):
        lrs.read_features(config)
    config["input_features"] = {"observation.state": {"shape": [6]}, "observation.images.side": {"shape": [3, 480, 640]},
                                "observation.images.wrist": {"shape": [3, 480, 640]}}
    assert lrs.read_features(config)[0] == {"side": (480, 640), "wrist": (480, 640)}


def test_load_torch_caps_cpu_threads_and_preserves_caller_env(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import os

    root, _ = checkpoint(tmp_path)
    calls = []
    fake_torch = SimpleNamespace(
        set_num_threads=lambda n: calls.append(("threads", n)),
        set_num_interop_threads=lambda n: (_ for _ in ()).throw(RuntimeError("already started")),
    )
    fake_policy = SimpleNamespace(config=SimpleNamespace(device="cuda"), to=lambda _d: SimpleNamespace(eval=lambda: None))
    fake_act = SimpleNamespace(ACTPolicy=SimpleNamespace(from_pretrained=lambda _p: fake_policy))
    fake_factory = SimpleNamespace(make_pre_post_processors=lambda *a, **kw: (lambda x: x, lambda x: x))
    for name, mod in (
        ("torch", fake_torch),
        ("lerobot", SimpleNamespace()),
        ("lerobot.policies", SimpleNamespace()),
        ("lerobot.policies.act", SimpleNamespace()),
        ("lerobot.policies.act.modeling_act", fake_act),
        ("lerobot.policies.factory", fake_factory),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setenv("OMP_NUM_THREADS", "3")
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)
    monkeypatch.delenv("OPENBLAS_NUM_THREADS", raising=False)

    lrs._load_torch(root, "cpu")
    assert os.environ["OMP_NUM_THREADS"] == "3"
    assert os.environ["MKL_NUM_THREADS"] == "2" and os.environ["OPENBLAS_NUM_THREADS"] == "2"
    assert calls == [("threads", min(2, os.cpu_count() or 1))]
