"""data_gate: decoded frames 1:1 with rows, role names (D-1065), black runs, ranges, goal text, fixed sources, stale receipts."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import data_gate as dg  # noqa: E402

FPS = 15
HOME_B = [0.023, -1.967, 1.667, 1.626, 1.399, 0.6]


def _media_deps():
    return pytest.importorskip("numpy"), pytest.importorskip("pandas"), pytest.importorskip("av")


def _video(path, frames, black=False, static=False):
    np, _, av = _media_deps()
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as c:
        s = c.add_stream("mpeg4", rate=FPS)
        s.width, s.height, s.pix_fmt = 64, 48, "yuv420p"
        for i in range(frames):
            img = np.zeros((48, 64, 3), np.uint8) if black else np.full((48, 64, 3), 90 if static else 40 + (i * 7) % 200, np.uint8)
            for p in s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                c.mux(p)
        for p in s.encode():
            c.mux(p)


def make(root, *, cams=("top", "side", "wrist"), n=80, video_frames=None, black=None, task="Move the designated container from belt to ship-h1r1-l0.",
         state0=HOME_B, gripper=0.6, static=None):
    np, pd, _ = _media_deps()
    root = Path(root)
    feats = {"observation.state": {"dtype": "float32", "shape": [6]}, "action": {"dtype": "float32", "shape": [6]}}
    for c in cams:
        feats[f"observation.images.{c}"] = {"dtype": "video", "shape": [48, 64, 3]}
    info = dict(fps=FPS, robot_type="omx_sim_arm", total_episodes=1, total_frames=n, features=feats,
                video_path="videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4")
    (root / "meta/episodes/chunk-000").mkdir(parents=True)
    (root / "data/chunk-000").mkdir(parents=True)
    (root / "meta/info.json").write_text(json.dumps(info))
    ep = {"episode_index": 0}
    for c in cams:
        key = f"observation.images.{c}"
        _video(root / info["video_path"].format(video_key=key, chunk_index=0, file_index=0),
               (video_frames or {}).get(c, n), black=(black == c), static=(static == c))
        ep.update({f"videos/{key}/chunk_index": 0, f"videos/{key}/file_index": 0,
                   f"videos/{key}/from_timestamp": 0.0, f"videos/{key}/to_timestamp": n / FPS})
    pd.DataFrame([ep]).to_parquet(root / "meta/episodes/chunk-000/file-000.parquet")
    pd.DataFrame({"task_index": [0]}, index=[task]).to_parquet(root / "meta/tasks.parquet")
    q = np.tile(np.array(state0[:5] + [gripper], np.float32), (n, 1))
    q[:, 0] += np.linspace(0, 0.3, n, dtype=np.float32)
    pd.DataFrame(dict(index=range(n), episode_index=0, frame_index=range(n), task_index=0, timestamp=np.arange(n) / FPS,
                      **{"observation.state": list(q), "action": list(q)})).to_parquet(root / "data/chunk-000/file-000.parquet")
    return root


SIM = {"kind": "sim", "layout": "random"}


def test_an_intact_three_camera_episode_passes_and_the_receipt_admits_it(tmp_path):
    root = make(tmp_path / "ok")
    r = dg.gate(root, "arm_b", SIM)
    assert r["counts"] == {"pass": 1, "review": 0, "reject": 0} and r["goals_passing"] == ["ship-h1r1-l0"]
    assert dg.check_receipt(root) == [0]


def test_nonfinite_episode_is_rejected_without_breaking_receipt_summary(tmp_path):
    np, pd, _ = _media_deps()
    root = make(tmp_path / "nonfinite")
    ep_path = root / "meta/episodes/chunk-000/file-000.parquet"
    episodes = pd.read_parquet(ep_path)
    pd.concat([episodes, episodes.assign(episode_index=1)]).to_parquet(ep_path)
    data_path = root / "data/chunk-000/file-000.parquet"
    data = pd.read_parquet(data_path)
    invalid = data.assign(episode_index=1, index=data["index"] + len(data))
    state = np.stack(invalid["observation.state"])
    state[0, 0] = np.nan
    invalid["observation.state"] = list(state)
    pd.concat([data, invalid]).to_parquet(data_path)

    receipt = dg.gate(root, "arm_b", SIM)
    assert receipt["counts"] == {"pass": 1, "review": 0, "reject": 1}
    assert receipt["measured_summary"]["pan_f0_std_rad"] == 0
    assert "pan_f0_rad" not in receipt["episodes"][1]["measured"]
    assert "non-finite state or action" in receipt["episodes"][1]["reject"]


def test_a_dropped_video_frame_is_rejected(tmp_path):
    r = dg.gate(make(tmp_path / "drop", video_frames={"side": 79}), "arm_b", SIM)
    assert r["episodes"][0]["verdict"] == "reject" and any("side: decoded 79 frames for 80 rows" in x for x in r["episodes"][0]["reject"])


def test_camera_names_must_be_roles_or_declared_legacy(tmp_path):
    with pytest.raises(ValueError, match="D-1065"):
        dg.gate(make(tmp_path / "front", cams=("top", "side", "front")), "arm_b", SIM)   # 11-21 cell config name
    with pytest.raises(ValueError, match="cover"):
        dg.gate(make(tmp_path / "two", cams=("rs", "wrist")), "arm_b", SIM)            # two-camera data
    legacy = make(tmp_path / "psy", cams=("rs", "top", "wrist"))                          # Purple-SY names
    with pytest.raises(ValueError, match="two cameras map to role top"):
        dg.gate(legacy, "arm_b", SIM)                                                     # rs->top default collides
    r = dg.gate(legacy, "arm_b", {"kind": "real", "layout": "random"}, legacy={"rs": "top", "top": "side"})
    assert r["cameras"] == {"observation.images.rs": "top", "observation.images.top": "side", "observation.images.wrist": "wrist"}


def test_black_camera_goal_text_units_and_start_pose(tmp_path):
    assert any("black" in x for x in dg.gate(make(tmp_path / "b", black="wrist"), "arm_b", SIM)["episodes"][0]["reject"])
    assert any("goal" in x for x in dg.gate(make(tmp_path / "g", task="pick something"), "arm_b", SIM)["episodes"][0]["reject"])
    raw = [v * 40 for v in HOME_B[:5]] + [53.0]                                            # follower units, not radians
    assert dg.gate(make(tmp_path / "u", state0=raw, gripper=53.0), "arm_b", SIM)["episodes"][0]["verdict"] == "reject"
    far = list(HOME_B); far[2] -= 0.6
    r = dg.gate(make(tmp_path / "far", state0=far), "arm_b", SIM)
    assert r["episodes"][0]["verdict"] == "review"
    with pytest.raises(ValueError, match="waiting for review"):
        dg.check_receipt(tmp_path / "far")
    receipt = json.loads((tmp_path / "far" / dg.RECEIPT).read_text())
    receipt["approved_reviews"] = [{"episode_index": 0, "reviewer": "kim", "reason": "start pose seen on the frames"}]
    (tmp_path / "far" / dg.RECEIPT).write_text(json.dumps(receipt))
    assert dg.check_receipt(tmp_path / "far") == [0]


def test_a_fixed_layout_source_cannot_enter_a_randomized_set_and_a_changed_file_needs_a_new_gate(tmp_path):
    root = make(tmp_path / "fixed")
    r = dg.gate(root, "arm_b", {"kind": "sim", "layout": "fixed"})
    assert r["dataset_reject"]
    with pytest.raises(ValueError, match="dataset rejected"):
        dg.check_receipt(root)
    ok = make(tmp_path / "ok2")
    dg.gate(ok, "arm_b", SIM)
    (ok / "meta/info.json").write_text((ok / "meta/info.json").read_text() + " ")
    with pytest.raises(ValueError, match="differ from the gated"):
        dg.check_receipt(ok)
    with pytest.raises(ValueError, match="kind="):
        dg.gate(ok, "arm_b", {"kind": "sim"})


def test_an_unchanged_camera_is_reviewed_only_for_real_sources(tmp_path):
    root = make(tmp_path / "still", static="side")    # sim side camera with nothing moving in view: identical renders
    assert dg.gate(root, "arm_b", SIM)["counts"]["review"] == 0
    r = dg.gate(root, "arm_b", {"kind": "real", "layout": "random"})
    assert any("side: unchanged" in x for x in r["episodes"][0]["review"])


def test_stand_destination_episode_passes_data_gate(tmp_path):
    home_a = [0.023, -1.965, 1.666, 1.618, 1.41, 0.5]
    root = make(tmp_path / "stand", task="Move the designated container from ship-h1r0-l0 to stand.", state0=home_a, gripper=0.5)
    r = dg.gate(root, "arm_a", SIM)
    assert r["counts"] == {"pass": 1, "review": 0, "reject": 0} and r["goals_passing"] == ["stand"]
    assert dg.check_receipt(root) == [0]


def test_goal_regex_and_camera_map_without_video_deps():
    for valid, expected in (
        ("Move the designated container from ship-h1r0-l0 to stand.", "stand"),
        ("Move the designated container from belt to tray.", "tray"),
        ("Move the designated container from belt to ship-h1r2-l2.", "ship-h1r2-l2"),
    ):
        m = dg.GOAL_RE.search(valid)
        assert m and m.group(1) == expected
    for invalid in ("Move from ship-h1r0-l0 to belt.", "pick something"):
        assert dg.GOAL_RE.search(invalid) is None
    feats = {f"observation.images.{c}": {} for c in ("top", "side", "wrist")}
    assert dg.camera_map(feats, {}) == {
        "observation.images.top": "top",
        "observation.images.side": "side",
        "observation.images.wrist": "wrist",
    }
    legacy_feats = {f"observation.images.{c}": {} for c in ("rs", "top", "wrist")}
    assert dg.camera_map(legacy_feats, {"rs": "top", "top": "side"}) == {
        "observation.images.rs": "top",
        "observation.images.top": "side",
        "observation.images.wrist": "wrist",
    }
    with pytest.raises(ValueError, match="D-1065"):
        dg.camera_map({f"observation.images.{c}": {} for c in ("top", "side", "front")}, {})
    assert dg.GOAL_SCOPES["h2"].search("Move the designated container from belt to ship-h2r1-l0.").group(1) == "ship-h2r1-l0"
    assert dg.GOAL_SCOPES["unload"].search("Move the designated container from ship-l0 to temp-plate.").group(1) == "temp-plate"
    assert dg.GOAL_RE.search("Move the designated container from belt to ship-h2r1-l0.") is None


def test_goal_scope_enforcement_and_measured_summary(tmp_path):
    h2 = make(tmp_path / "h2", task="Move the designated container from belt to ship-h2r2-l0.")
    assert dg.gate(h2, "arm_b", SIM, goal_scope="h1")["episodes"][0]["verdict"] == "reject"
    r = dg.gate(h2, "arm_b", SIM, goal_scope="h2")
    assert r["counts"] == {"pass": 1, "review": 0, "reject": 0} and r["goal_scope"] == "h2"
    assert "wrist_roll_f0_median_rad" in r["measured_summary"] and "pan_f0_std_rad" in r["measured_summary"]
    with pytest.raises(ValueError, match="goal_scope"):
        dg.check_receipt(h2, expected_scope="h1")
    assert dg.check_receipt(h2, expected_scope="h2") == [0]
