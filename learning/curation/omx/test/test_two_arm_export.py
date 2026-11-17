"""Real two-arm recordings -> the sim `collect` dataset format, and mixing them into a round. Fake producer directories, tiny images, no device.
The real LeRobot round trip and aggregation run in the pinned learner venv: test_two_arm_export_lerobot.py."""
import ast
import json
from pathlib import Path
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
pytest.importorskip("cv2")
from two_arm_fixture import (  # noqa: E402
    COLORS, FPS, RULE, T0, cv2, export, helpers, inputs, make_source, sim_features, window, world_source, _write,
)
import omx_two_arm_mix as mix  # noqa: E402


class Fake:
    """The part of LeRobotDataset the exporter calls; keeps what it was created with and every saved episode."""

    def __init__(self, repo_id, fps, root=None, robot_type=None, features=None, **kwargs):
        self.fps, self.robot_type, self.features, self.buffer, self.episodes, self.finalized = fps, robot_type, features, [], [], False

    def add_frame(self, row):
        self.buffer.append(row)

    def save_episode(self):
        self.episodes.append(self.buffer)
        self.buffer = []

    def clear_episode_buffer(self):
        self.buffer = []

    def finalize(self):
        self.finalized = True


@pytest.fixture
def made(monkeypatch):
    seen = {}
    module = types.ModuleType("lerobot.datasets.lerobot_dataset")
    module.LeRobotDataset = types.SimpleNamespace(create=lambda *a, **k: seen.setdefault("ds", Fake(*a, **k)))
    for name, mod in (("lerobot", types.ModuleType("lerobot")), ("lerobot.datasets", types.ModuleType("lerobot.datasets")),
                      ("lerobot.datasets.lerobot_dataset", module)):
        monkeypatch.setitem(sys.modules, name, mod)
    return seen


def streams_of(src):
    return {n: export.Stream(Path(src) / export.SOURCES[n], n) for n in export.SOURCES}


def test_views_arms_joints_and_fps_are_the_sims():
    assert export.SIM_FPS == world_source()["FPS"] == FPS
    assert tuple(helpers.teaching.RECORDED) == inputs.VIEWS and tuple(helpers.sites.ARMS) == inputs.ARMS
    assert [f"{a}.{j}" for a in helpers.sites.ARMS for j in world_source()["JOINTS"]] == list(inputs.JOINT_NAMES)
    text = Path(helpers.__file__).read_text(encoding="utf-8")
    collect = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "collect")
    assert "dataset_features(" in ast.get_source_segment(text, collect)  # collect builds its features there, not by hand


def test_a_successful_carry_becomes_an_episode_with_the_sim_features(tmp_path, made):
    meta = export.export(make_source(tmp_path / "src"), [window("a1"), window("a2", outcome="held"), window("a3", 5, 34)], tmp_path / "real")
    ds = made["ds"]
    assert json.loads(json.dumps(ds.features)) == sim_features() and ds.fps == FPS and ds.robot_type == "omx_follower_pair" and ds.finalized
    assert [len(e) for e in ds.episodes] == [30, 30] and meta["episodes"] == 2
    assert [(r["episode_id"], "not a success" in r["reason"]) for r in meta["real"]["rejected"]] == [("a2", True)]
    assert json.loads((tmp_path / "real.steps.json").read_text(encoding="utf-8"))["real"]["success_outcomes"] == ["placed", "success"]


def test_values_are_the_cells_conversion_and_images_are_rgb_240x320(tmp_path, made):
    export.export(make_source(tmp_path / "src"), [window()], tmp_path / "real")
    first = made["ds"].episodes[0][0]
    # tick 0 of make_source: state [0, 0, 3, 0, 1, 50], accepted reference [1, 0, 3, 0, 1, 20] in follower units
    body = inputs.to_radians([0, 0, 3, 0, 1, 50.0])
    want = [body[j] for j in inputs.JOINTS[:5]] + [inputs.sim_gripper(50.0, RULE)]
    np.testing.assert_allclose(first["observation.state"], want * 2, atol=1e-6)
    np.testing.assert_allclose(first["action"][:5], [inputs.to_radians([1, 0, 3, 0, 1, 20.0])[j] for j in inputs.JOINTS[:5]], atol=1e-6)
    assert first["action"][5] == pytest.approx(inputs.sim_gripper(20.0, RULE)) and first["action"][5] != pytest.approx(first["observation.state"][5])
    assert first["observation.state"].dtype == np.float32 and first["observation.state"].shape == (12,) and first["action"].shape == (12,)
    for view, bgr in COLORS.items():
        image = first[f"observation.images.{view}"]
        assert image.shape == (240, 320, 3) and image.dtype == np.uint8
        assert np.abs(image[120, 160].astype(int) - np.array(bgr[::-1])).max() <= 3  # BGR frame in, RGB out
    assert first["task"] == helpers.PROMPT and helpers.GOAL not in first


def test_goal_feature_follows_the_window_goals(tmp_path, made):
    goal = [0.5] * 22
    export.export(make_source(tmp_path / "src"), [window(goal=goal)], tmp_path / "real", goal_mode="joints")
    assert json.loads(json.dumps(made["ds"].features)) == sim_features(22)
    assert made["ds"].episodes[0][0][helpers.GOAL].tolist() == goal
    with pytest.raises(ValueError, match="goal"):
        export.export(tmp_path / "src", [window(goal=goal), window("b")], tmp_path / "x", goal_mode="joints")
    with pytest.raises(ValueError, match="goal_mode"):
        export.export(tmp_path / "src", [window(goal=goal)], tmp_path / "y")


def test_dropped_ticks_are_counted_and_a_ragged_carry_is_refused(tmp_path, made):
    # top misses ticks 10-12: tick 10 is one beat old (kept), 11 is 0.133 s old but 0.133 s behind the others (skew), 12 is 0.2 s old (stale)
    meta = export.export(make_source(tmp_path / "src", skip={"top": {10, 11, 12}}), [window("one")], tmp_path / "real")
    (done,) = meta["real"]["accepted"]
    assert done["frames"] == 28 and done["dropped"] == {"skew": 1, "stale": 1} and meta["real"]["dropped_ticks"] == {"skew": 1, "stale": 1}
    ragged = make_source(tmp_path / "src2", skip={"side": set(range(5, 20))})  # side is silent for 15 beats: 14 of 30 ticks dropped
    with pytest.raises(ValueError, match="ticks dropped"):
        export.export(ragged, [window("ragged")], tmp_path / "real2")
    holes = make_source(tmp_path / "src3", skip={"arm_a": {8, 9, 10, 11}})  # ticks 9-11 dropped: 10% of the carry, but a hole longer than 2 ticks
    with pytest.raises(ValueError, match="hole"):
        export.export(holes, [window("hole")], tmp_path / "real3")


def test_a_camera_far_behind_the_arms_is_dropped_for_skew(tmp_path):
    src = make_source(tmp_path / "src", skip={"side": {10, 11}})  # at tick 11 the side event is 0.133 s old (<0.15) but 2 beats behind the arms
    kept, dropped, ticks = export.plan(streams_of(src), window("w", 0, 29))
    assert dict(dropped) == {"skew": 1} and ticks == 30 and 11 not in [k for k, _ in kept] and 10 in [k for k, _ in kept]


def test_a_tampered_jpeg_drops_its_tick(tmp_path):
    src = make_source(tmp_path / "src")
    (src / "cam_top/events/7.jpg").write_bytes(b"not the jpeg the producer hashed")
    kept, dropped, _ = export.plan(streams_of(src), window("w", 0, 29))
    assert dict(dropped) == {"bad_event": 1} and 7 not in [k for k, _ in kept]


def test_producer_layout_is_checked_before_anything_is_written(tmp_path, made):
    bad = make_source(tmp_path / "bad", units="legacy-units")
    with pytest.raises(ValueError, match="arm producer"):
        export.export(bad, [window()], tmp_path / "o1")
    other = make_source(tmp_path / "other")
    d = json.loads((other / "cam_top/descriptor.json").read_text(encoding="utf-8"))
    d["clock_domain"] = "host-monotonic:other-boot"
    _write(other / "cam_top/descriptor.json", d)
    with pytest.raises(ValueError, match="clock domain"):
        export.export(other, [window()], tmp_path / "o2")
    with pytest.raises(ValueError, match="no carry was kept"):
        export.export(make_source(tmp_path / "ok"), [window(outcome="failed")], tmp_path / "o3")
    assert "ds" not in made  # no dataset was ever created for a source nothing could be taken from


def test_windows_come_from_attempt_rows_with_the_sites_goal():
    rows = [{"attempt_id": "x1", "t_start": 5.0, "t_end": 7.0, "outcome": "placed", "from": "S1", "to": "A2"}]
    (w,) = export.windows_from_attempts(rows, 100.0, arm="arm_b", goal_sites=["a", "b", "c"], site_map={"S1": "a", "A2": "c"})
    assert (w["t_start"], w["t_end"], w["outcome"], w["episode_id"]) == (105.0, 107.0, "placed", "x1")
    goal = np.asarray(w["goal"])  # arm_b's half only: active, one-hot source "a", one-hot target "c"
    assert goal.shape == (14,) and (goal[:7] == 0).all() and goal[7] == 1 and goal[8] == 1 and goal[13] == 1 and goal.sum() == 3


def test_the_exporter_is_read_only():
    source = Path(export.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"socket", "subprocess", "serial", "requests", "urllib", "http", "pty"}
    assert "FifoCell" not in source and "mkfifo" not in source and "os.open" not in source and ".act(" not in source


def fake_dataset(root, frames, features=None, *, fps=15, robot="omx_follower_pair", goal_mode=None):
    root = Path(root)
    _write(root / "meta/info.json", {"features": features or sim_features(), "fps": fps, "robot_type": robot, "total_frames": frames})
    _write(root.parent / f"{root.name}.steps.json", {"goal_mode": goal_mode})
    return root


def test_the_mix_repeats_extra_datasets_by_weight_and_reports_shares(tmp_path):
    part, real = fake_dataset(tmp_path / "part0", 10), fake_dataset(tmp_path / "real", 30)
    roots, shares = mix.weighted_roots([part], [real], [3])
    assert roots == [part, real, real, real]
    assert shares[str(part)] == {"weight": 1, "frames": 10, "share": 0.1} and shares[str(real)] == {"weight": 3, "frames": 90, "share": 0.9}
    assert mix.weighted_roots([part], [real])[0] == [part, real]
    assert mix.weighted_roots([], [real, real], [2])[0] == [real] * 4
    other = fake_dataset(tmp_path / "old", 5)
    assert mix.weighted_roots([part], [real, other], [2, 1])[0] == [part, real, real, other]
    assert mix.weighted_roots([part], [real, other], [2])[0] == [part, real, real, other, other]
    for bad in ([0], [1, 2, 3], [-1]):
        with pytest.raises(ValueError, match="weight"):
            mix.weighted_roots([part], [real], bad)


def test_datasets_with_other_features_are_refused_before_training(tmp_path):
    part = fake_dataset(tmp_path / "part0", 3, sim_features(22), goal_mode="joints")
    no_goal = fake_dataset(tmp_path / "real", 3)
    with pytest.raises(ValueError, match="features differ") as raised:
        mix.weighted_roots([part], [no_goal])
    assert "observation.environment_state" in str(raised.value) and "real" in str(raised.value)
    with pytest.raises(ValueError, match="fps"):
        mix.weighted_roots([part], [fake_dataset(tmp_path / "slow", 3, sim_features(22), fps=30)])
    with pytest.raises(ValueError, match="robot_type"):
        mix.weighted_roots([part], [fake_dataset(tmp_path / "other", 3, sim_features(22), robot="so101")])
    with pytest.raises(ValueError, match="goal mode"):
        mix.weighted_roots([part], [fake_dataset(tmp_path / "site", 3, sim_features(22), goal_mode="site")])
    with pytest.raises(ValueError, match="not a LeRobot dataset"):
        mix.weighted_roots([part], [tmp_path / "nothing"])
