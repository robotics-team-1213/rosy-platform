"""omx_sim_real_mirror with fake live.json rows and fake frames: no cell, no arm command."""
import json
from pathlib import Path
import sys
import time

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_sim_real_mirror as mirror_mod  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402

HOME = [0.0, -40.0, 40.0, 20.0, 0.0, 54.3]  # follower units, gripper at arm_a's held_30mm


def live(path, state, target=None, t=None):
    path.write_text(json.dumps({"t": time.time() if t is None else t, "state": state, "target": target or state, "chunk": "c1"}))
    return str(path)


def test_plan_points_reads_both_chunk_shapes_and_refuses_others():
    layout = sites.Layout()
    one = mirror_mod.plan_points(layout, {"arm": "arm_a", "rows": [HOME, [10.0, *HOME[1:]]]})
    assert set(one) == {"arm_a"} and one["arm_a"].shape == (2, 3)
    assert np.linalg.norm(one["arm_a"][1] - one["arm_a"][0]) > .005  # joint1 turned: the TCP moved
    two = mirror_mod.plan_points(layout, {"rows": [[0.0] * 12] * 3})
    assert set(two) == {"arm_a", "arm_b"} and np.isfinite(two["arm_b"]).all()
    with pytest.raises(ValueError):
        mirror_mod.plan_points(layout, {"rows": [HOME]})  # six values without the arm they belong to


def test_preview_draws_projected_points_on_the_top_frame(tmp_path):
    layout = sites.Layout()
    top = np.zeros((480, 640, 3), np.uint8)
    focus = layout.fixture["real_cameras"]["top"]["focus"]
    pixels = mirror_mod.preview(layout, {"arm": "arm_a", "points": [focus, np.add(focus, [.05, 0, 0])]}, top, tmp_path)
    (u, v), _ = pixels["arm_a"]
    assert abs(u - 320) < 1 and abs(v - 240) < 1  # the camera's focus point is the image centre
    drawn = cv2.imread(str(tmp_path / "preview_top.png"))
    assert drawn.any() and not top.any()  # drawn on a copy


def test_mirror_poses_arms_from_live_rows_and_names_the_missing_one(tmp_path):
    pytest.importorskip("mujoco")
    import omx_two_arm_world

    world = omx_two_arm_world.World()
    rules = {arm: mirror_mod.inputs.grip_rule({"work_dir": str(tmp_path)}, arm) for arm in mirror_mod.inputs.ARMS}
    target = [5.0, *HOME[1:]]
    lives = {"arm_a": live(tmp_path / "a.json", HOME, target)}
    data, report = mirror_mod.mirror(world, lives, rules)
    assert report["missing"] == {"arm_b": "no --live given"}
    a = report["arms"]["arm_a"]
    assert not a["stale"] and a["chunk"] == "c1"
    assert np.allclose(data.qpos[world.q["arm_a"]], a["q_rad"], atol=1e-5)
    assert a["target_minus_state_rad"][0] > 0 and a["target_minus_state_tcp_mm"] > 1
    assert np.linalg.norm(a["fk_minus_sim_mm"]) < 5  # same chain and TCP (.0740 both): kin and MuJoCo agree
    cid = world.model.camera("top").id  # preview's Camera must put a point where the sim render (blend) shows it
    c = data.cam_xmat[cid].reshape(3, 3).T @ (np.array(a["sim_tcp_m"]) - data.cam_xpos[cid])
    f = 240 / np.tan(np.radians(world.model.cam_fovy[cid]) / 2)
    cam = mirror_mod.Camera(world.layout.fixture["real_cameras"]["top"], (480, 640))
    assert np.allclose(cam.project(a["sim_tcp_m"]), (320 - f * c[0] / c[2], 240 + f * c[1] / c[2]), atol=.5)
    frames = {"top": np.full((480, 640, 3), 90, np.uint8)}
    views = mirror_mod.write_views(world, data, frames, tmp_path / "out")
    assert views["top"] == ["sim_top.png", "blend_top.png"] and views["side"] == ["sim_side.png"]
    old = {"arm_a": live(tmp_path / "old.json", HOME, t=time.time() - 60), "arm_b": str(tmp_path / "absent.json")}
    _, report = mirror_mod.mirror(world, old, rules)
    assert report["arms"]["arm_a"]["stale"] and "FileNotFoundError" in report["missing"]["arm_b"]


def test_the_mirror_cannot_command_an_arm():
    source = Path(mirror_mod.__file__).read_text(encoding="utf-8")
    for word in ("act(", "torque", "send(", "requests", "socket"):
        assert word not in source
