"""Belt container pose as policy input (Panel L, 2026-11-27): 13-wide environment_state only for a checkpoint that names it,
measured once from the top frame in the sim fixture frame, refused (never clamped) when unknown or past the training range."""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "robot" / "omx"))
sys.path.insert(0, str(ROOT / "tools" / "sim"))
import cell_belt_pose as bp  # noqa: E402
import cell_belt_vision as vision  # noqa: E402
import cell_lerobot_shadow as lrs  # noqa: E402
from cell_policy_goals import GOALS  # noqa: E402
import omx_env_state  # noqa: E402

cv2 = pytest.importorskip("cv2")
FIXTURES = ROOT / "test" / "fixtures" / "omx_belt_pose_1127"
PRESET = "v24-20261126-real-home"
# top_refit.json of 2026-11-27 (the camera Panel L views were rendered around; rms 1.65 mm over 4 anchors)
TOP = {"eye": [0.026, -0.0045, 0.6837], "focus": [0.0528, 0.0122, 0.1847], "up": [0.9971, -0.0556, 0.0516],
       "f_px": 618.5, "width": 640, "height": 480}
NAMES = [*GOALS, *bp.BELT_NAMES]
INFO = {"features": {lrs.GOAL: {"shape": [13], "names": NAMES}}}
REFERENCE = omx_env_state.build(INFO, {"ok": True, "camera": TOP}, PRESET)["belt_reference"]
CONFIG = {"type": "act",
          "input_features": {"observation.state": {"shape": [6]}, "observation.images.top": {"shape": [3, 8, 12]}},
          "output_features": {"action": {"shape": [6]}}}


def checkpoint(tmp_path, width, env_state=None):
    root = tmp_path / "ckpt"
    root.mkdir(parents=True)
    config = {**CONFIG, "input_features": {**CONFIG["input_features"], lrs.GOAL: {"shape": [width]}}}
    (root / "config.json").write_text(json.dumps(config))
    (root / lrs.WEIGHTS).write_bytes(b"weights")
    if env_state is not None:
        (root / lrs.ENV_STATE).write_text(json.dumps(env_state))
    return lrs.LeRobotShadow(root, hashlib.sha256(b"weights").hexdigest(), loader=lambda *_: None)


def frames():
    return {"top": np.zeros((8, 12, 3), np.uint8)}


def test_ten_wide_and_undeclared_checkpoints_are_unchanged(tmp_path):
    ten = checkpoint(tmp_path / "a", 10)
    assert ten.goal_size == 10 and not ten.belt_input and ten.env_names is None
    obs, meta = ten.inputs([0] * 6, frames(), goal=3)
    np.testing.assert_array_equal(obs[lrs.GOAL], np.eye(10, dtype=np.float32)[3])
    assert "belt_pose" not in meta
    with pytest.raises(ValueError, match="no belt pose input"):
        ten.inputs([0] * 6, frames(), goal=3, belt=[0, 0, 0])
    other = checkpoint(tmp_path / "b", 13, {"names": [*GOALS, "x", "y", "belt_yaw_x5"]})  # names differ: one-hot as before
    assert other.goal_size == 13 and not other.belt_input
    assert other.inputs([0] * 6, frames(), goal=12)[0][lrs.GOAL].tolist() == [0] * 12 + [1]
    assert checkpoint(tmp_path / "c", 13).goal_size == 13  # no declaration file: unchanged
    with pytest.raises(ValueError, match="names must list the 13"):
        checkpoint(tmp_path / "d", 13, {"names": NAMES[:-1]})


def test_declared_checkpoint_takes_one_hot_then_the_three_numbers(tmp_path):
    shadow = checkpoint(tmp_path, 13, {"names": NAMES, "belt_reference": REFERENCE})
    assert shadow.belt_input and shadow.goal_size == 10 and shadow.belt_reference == REFERENCE
    obs, meta = shadow.inputs([0] * 6, frames(), goal=9, belt=[0.6, -0.25, 0.5])
    assert obs[lrs.GOAL].dtype == np.float32
    np.testing.assert_allclose(obs[lrs.GOAL], [0] * 9 + [1] + [0.6, -0.25, 0.5])
    assert meta["goal_slot"] == 9 and meta["belt_pose"] == pytest.approx([0.6, -0.25, 0.5])
    masked, _ = shadow.inputs([0] * 6, frames(), goal=9, mask_goal=True, belt=[0.6, -0.25, 0.5])
    np.testing.assert_allclose(masked[lrs.GOAL], [0] * 10 + [0.6, -0.25, 0.5])  # masking hides the slot, not the pose
    for belt in (None, [0, 0], [0, 0, float("nan")], [0, 0, 0, 0]):
        with pytest.raises(ValueError, match="belt container pose"):
            shadow.inputs([0] * 6, frames(), goal=9, belt=belt)
    with pytest.raises(ValueError, match="goal slot"):
        shadow.inputs([0] * 6, frames(), goal=10, belt=[0, 0, 0])


def scene(*boxes, size=(0.09, 0.03)):
    """A 640x480 top frame: grey deck, one orange top face per (dx m, dy m, yaw deg) from the nominal belt site."""
    import omx_two_arm_sites as sites
    from omx_real2sim_helpers import Camera

    layout = sites.Layout(preset=PRESET)
    site, z = layout.sites["belt"], layout.belt_top + sites.CONTAINER[layout.choices["ship_source"]][2]
    cam, img = Camera(TOP, (480, 640)), np.full((480, 640, 3), 200, np.uint8)
    for dx, dy, yaw_deg in boxes:
        c, s, (half_l, half_w) = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg)), (size[0] / 2, size[1] / 2)
        corners = [(site["xy"][0] + dx + a * half_l * c - b * half_w * s, site["xy"][1] + dy + a * half_l * s + b * half_w * c)
                   for a, b in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
        px = np.array([cam.project((x, y, z)) for x, y in corners], np.float32)
        cv2.fillPoly(img, [np.round(px).astype(np.int32)], (0, 120, 255))
    return img


@pytest.mark.parametrize("yaw_deg", [10.0, 190.0, -170.0])  # one box, three spellings of its long axis: yaw folds to +10
def test_known_offset_gives_the_trained_numbers(yaw_deg):
    out = bp.measure(scene((0.006, 0.004, yaw_deg)), REFERENCE)
    assert out["ok"], out
    assert out["features"] == pytest.approx([0.6, 0.4, math.radians(10) / 0.2], abs=0.1)
    assert out["names"] == list(bp.BELT_NAMES) and out["belt_site_mm"] == [207.0, -3.0]
    assert out["offset_mm"] == pytest.approx([6, 4], abs=1.0) and out["yaw_deg"] == pytest.approx(10, abs=1.0)
    assert out["score"] > 0.8 and len(out["frame_sha256"]) == 64


@pytest.mark.parametrize("box,name", [((0.016, 0, 0), "belt_dx_cm"), ((-0.004, 0, 0), "belt_dx_cm"),
                                      ((0.006, 0.012, 0), "belt_dy_cm"), ((0.006, 0, 16), "belt_yaw_x5")])
def test_past_the_training_range_refuses_with_the_unclamped_value(box, name):
    out = bp.measure(scene(box), REFERENCE)
    assert not out["ok"] and out["reason_code"] == bp.OUT_OF_RANGE and name in out["reason"]
    expected = [box[0] / 0.01, box[1] / 0.01, math.radians(box[2]) / 0.2]
    assert out["features"] == pytest.approx(expected, abs=0.12)


@pytest.mark.parametrize("frame,reference,why", [
    (scene(), REFERENCE, "no container"),
    (scene((0.0, -0.02, 0), (0.006, 0.025, 0)), REFERENCE, "2 containers"),
    (scene((0.006, 0, 0), size=(0.05, 0.05)), REFERENCE, "footprint"),
    (scene((0.006, 0, 0)), None, "NOT_AVAILABLE"),
    (scene((0.006, 0, 0)), {**REFERENCE, "top_camera": {"eye": [0, 0, 1]}}, "NOT_AVAILABLE"),
    (scene((0.006, 0, 0)), {k: v for k, v in REFERENCE.items() if k != "belt_site"}, "belt_site"),
    (scene((0.006, 0, 0)), {**REFERENCE, "container": {"length_m": 0.09, "width_m": 0.03}}, "container"),
    (scene((0.006, 0, 0)), {**REFERENCE, "belt_top_m": float("nan")}, "belt_top_m"),
    (np.zeros((240, 320, 3), np.uint8), REFERENCE, "320x240"),
    (None, REFERENCE, "no top frame"),
])
def test_unknown_pose_refuses(frame, reference, why):
    out = bp.measure(frame, reference)
    assert not out["ok"] and out["reason_code"] == bp.UNKNOWN and why in out["reason"]


def test_real_belt_frames_read_one_container_off_the_belt_centre():
    """2026-11-27 run 6 (container turned at the belt end, the arm touched it) and run 4: one container each, but
    34-49 mm to -y of the sim belt site, so a Panel L run on them refuses instead of guessing."""
    six = bp.measure(cv2.imread(str(FIXTURES / "real6-before-top.jpg")), REFERENCE)
    assert six["reason_code"] == bp.OUT_OF_RANGE and "belt_dy_cm" in six["reason"]
    assert six["offset_mm"][1] == pytest.approx(-49, abs=4) and six["yaw_deg"] == pytest.approx(6, abs=3)
    four = bp.measure(cv2.imread(str(FIXTURES / "real4-before-top.jpg")), REFERENCE)
    assert four["reason_code"] == bp.OUT_OF_RANGE and four["offset_mm"][1] == pytest.approx(-34.5, abs=4)


def test_generator_fills_the_reference_from_the_sim_layout(tmp_path):
    import omx_two_arm_sites as sites

    layout = sites.Layout(preset=PRESET)
    assert REFERENCE["belt_site"] == {"xy": list(layout.sites["belt"]["xy"]), "yaw": layout.sites["belt"]["yaw"]}
    assert REFERENCE["belt_top_m"] == layout.belt_top and REFERENCE["top_camera"] == TOP and REFERENCE["preset"] == PRESET
    assert list(REFERENCE["container"].values()) == list(sites.CONTAINER[layout.choices["ship_source"]])
    (tmp_path / "info.json").write_text(json.dumps(INFO))
    (tmp_path / "top_refit.json").write_text(json.dumps({"ok": True, "camera": TOP, "rms_mm": 1.65}))
    argv = ["--info", str(tmp_path / "info.json"), "--top-camera", str(tmp_path / "top_refit.json"), "--preset", PRESET]
    assert omx_env_state.main([*argv, "--out", str(tmp_path / "ENV_STATE.json")]) == 0
    assert json.loads((tmp_path / "ENV_STATE.json").read_text()) == {"names": NAMES, "belt_reference": REFERENCE}
    for info, top, why in ((INFO, {"ok": False, "camera": TOP}, "not ok"), (INFO, {"eye": [0, 0, 1]}, "needs"),
                           ({"features": {lrs.GOAL: {"shape": [10], "names": list(GOALS)}}}, TOP, "end with")):
        with pytest.raises(ValueError, match=why):
            omx_env_state.build(info, top, PRESET)


def _sim_containers(frame):
    """The tools/sim original: container blobs and lane_blobs' accepted containers (the cell copy must match it)."""
    import omx_two_arm_sites as sites
    from omx_real2sim_helpers import Camera, blobs, lane_blobs, rect

    layout = sites.Layout(preset=PRESET)
    cam, h = Camera(TOP, frame.shape[:2]), sites.CONTAINER[layout.choices["ship_source"]][2]
    seen = [rect(cam.to_plane(px, layout.belt_top + h)) for kind, px in blobs(frame) if kind == "container"]
    return seen, [{k: b[k] for k in ("xy", "yaw", "size", "partial")} for b in lane_blobs(frame, cam, layout.belt_top, h)
                  if b["kind"] == "container"]


@pytest.mark.parametrize("name", ["real4-before-top.jpg", "real6-before-top.jpg", "synthetic", "synthetic-odd"])
def test_cell_detection_matches_the_tools_sim_original(name):
    from omx_real2sim_helpers import LANE, PARTIAL_MIN, SIZE_TOL

    frame = {"synthetic": lambda: scene((0.006, 0.004, 10.0), (-0.03, 0.05, 80.0)),
             "synthetic-odd": lambda: scene((0.006, 0.0, -20.0), size=(0.06, 0.03))}.get(name, lambda: cv2.imread(str(FIXTURES / name)))()
    box = (LANE[0], LANE[1], REFERENCE["container"]["height_m"])
    seen, found = vision.containers(frame, vision.Camera(TOP, frame.shape[:2]), REFERENCE["belt_top_m"], box,
                                    (SIZE_TOL[0], SIZE_TOL[1] + 0.004, PARTIAL_MIN))
    sim_seen, sim_found = _sim_containers(frame)
    assert len(seen) == len(sim_seen) >= 1 and len(found) == len(sim_found)
    for mine, theirs in zip(seen, sim_seen):
        assert np.allclose(np.hstack([*mine[0], mine[1], *mine[2]]), np.hstack([*theirs[0], theirs[1], *theirs[2]]), atol=1e-9)
    for mine, theirs in zip(found, sim_found):
        assert mine["partial"] == theirs["partial"]
        assert np.allclose([*mine["xy"], mine["yaw"], *mine["size"]], [*theirs["xy"], theirs["yaw"], *theirs["size"]], atol=1e-9)
    shipped = bp.measure(frame, REFERENCE)  # the generator's container width (0.02998) against the original's 0.030 lane
    if "centre_mm" in shipped:
        site = REFERENCE["belt_site"]["xy"]
        theirs = min(sim_found, key=lambda b: math.dist(b["xy"], site))
        assert shipped["centre_mm"] == pytest.approx([v * 1000 for v in theirs["xy"]], abs=0.15)
        assert shipped["yaw_deg"] == pytest.approx(math.degrees(theirs["yaw"]), abs=0.1)


def test_cell_reading_needs_no_tools_sim(tmp_path):
    """The cell release has deploy/robot/omx but no tools/sim: import and measure with tools/sim unimportable."""
    import subprocess

    frame = scene((0.006, 0.004, 10.0))
    np.save(tmp_path / "frame.npy", frame)
    (tmp_path / "ref.json").write_text(json.dumps(REFERENCE))
    code = (
        "import importlib.abc, json, sys\n"
        "class Block(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.startswith(('omx_two_arm', 'omx_real2sim', 'omx_env_state', 'mapped_stack_fixture')):\n"
        "            raise ImportError('tools/sim is not on the cell: ' + name)\n"
        "sys.meta_path.insert(0, Block())\n"
        f"sys.path = [p for p in sys.path if 'tools' not in p.replace(chr(92), '/').split('/')]\n"
        f"sys.path.insert(0, {str(ROOT / 'deploy' / 'robot' / 'omx')!r})\n"
        "import numpy as np, cell_belt_pose, cell_lerobot_shadow\n"
        f"out = cell_belt_pose.measure(np.load({str(tmp_path / 'frame.npy')!r}), json.load(open({str(tmp_path / 'ref.json')!r})))\n"
        "assert not any(m.startswith(('omx_two_arm', 'omx_real2sim')) for m in sys.modules)\n"
        "print(json.dumps(out))\n"
    )
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path, timeout=120)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout.strip().splitlines()[-1])
    assert out["ok"] and out["features"] == bp.measure(frame, REFERENCE)["features"]


class ReceiptCell:
    def __init__(self, frame, error=None):
        self.image, self.error, self.calls = frame, error, []

    def frame(self, view):
        pytest.fail("a cell with source-stamped receipts must not be read through the plain frame cache")

    def frame_receipt(self, camera, *, max_age_s, timeout_s):
        self.calls.append((camera, max_age_s))
        if self.error:
            raise ValueError(self.error)
        return {"image": self.image, "source_seq": 41, "source_stamp": 1.7e9}


def test_live_read_takes_only_a_fresh_source_stamped_frame():
    cell = ReceiptCell(scene((0.006, 0.004, 10.0)))
    out = bp.measure_cell(cell, REFERENCE)
    assert out["ok"] and out["source_seq"] == 41 and cell.calls == [("top", 2.0)]
    stale = bp.measure_cell(ReceiptCell(None, "camera frame source metadata is stale or invalid"), REFERENCE)
    assert stale["reason_code"] == bp.UNKNOWN and "stale" in stale["reason"] and "features" not in stale


class Cell:
    def __init__(self, frame):
        self.commands, self.image, self.state = [], frame, [0, -58, 51, 50, -5, 49]

    def frame(self, view):
        return self.image

    def act(self, command):
        self.commands.append(command)
        return {"state": self.state, "command": command, "settled": True, "holding": False, "ok": True}


@pytest.fixture
def drive(monkeypatch):
    import cell_policy_drive
    import cell_policy_start_gate as gate

    monkeypatch.setattr(gate, "read_state_range", lambda _root: {"min": np.full(6, -1e3), "max": np.full(6, 1e3)})
    return cell_policy_drive


def drive_args(tmp_path, drive, env_state):
    root = tmp_path / "model"
    root.mkdir()
    (root / lrs.WEIGHTS).write_bytes(b"pinned ACT")
    (root / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 4, "chunk_size": 16,
        "input_features": {"observation.state": {"shape": [6]}, lrs.GOAL: {"shape": [13]},
                           "observation.images.top": {"shape": [3, 480, 640]}},
        "output_features": {"action": {"shape": [6]}}}))
    (root / lrs.UNITS).write_text('{"state":"sim_rad","gripper":"sim_jaw","arm":"arm_b"}')
    (root / lrs.ENV_STATE).write_text(json.dumps(env_state))
    (tmp_path / "arm-cal-arm_b.json").write_text('{"arm_id":"arm_b","held_30mm":53.38,"gap_mm_per_unit":5}')
    (tmp_path / "cell.json").write_text('{"arm_id":"arm_b","io":"unused","cameras":{}}')
    names = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    (tmp_path / "cal.json").write_text(json.dumps({n: {"id": i, "drive_mode": 0, "homing_offset": 0, "range_min": 0,
                                                       "range_max": 4095} for i, n in enumerate(names)}))
    (tmp_path / "lib.json").write_text(json.dumps({"fps": 30, "gripper_closed": 46.6, "chunks": {
        "home": [[0, -58, 51, 50, -5, 49]] * 2, "reach": [[0, -58, 51, 50, -5, 49], [20, -20, 30, 40, -5, 60]]}}))
    return ["--config", str(tmp_path / "cell.json"), "--library", str(tmp_path / "lib.json"), "--policy-root", str(root),
            "--policy-revision", hashlib.sha256(b"pinned ACT").hexdigest(), "--cell-calibration", str(tmp_path / "cal.json"),
            "--operator", "test", "--max-chunks", "1", "--goal-site", "yard:r1-s2-t1", "--dry-run"]


def test_dry_run_feeds_and_records_the_measured_pose(tmp_path, monkeypatch, drive, capsys):
    import cell_pipeline

    cell, seen = Cell(scene((0.006, 0.004, 10.0))), []
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_: cell)

    def predict(obs):
        seen.append(obs)
        return np.repeat(obs["observation.state"][None, :], 16, axis=0)

    shadow = drive.lrs.LeRobotShadow
    monkeypatch.setattr(drive.lrs, "LeRobotShadow", lambda *a, **kw: shadow(*a, loader=lambda *_: predict, **kw))
    assert drive.main(drive_args(tmp_path, drive, {"names": NAMES, "belt_reference": REFERENCE})) == 0
    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result["result"] == "dry_run" and result["belt_pose"]["ok"]
    goal = seen[0][lrs.GOAL]
    np.testing.assert_array_equal(goal[:10], np.eye(10)[0])  # yard:r1-s2-t1 -> ship-h1r0-l0
    assert goal[10:].tolist() == pytest.approx(result["belt_pose"]["features"], abs=1e-4)
    assert goal[10:].tolist() == pytest.approx([0.6, 0.4, 0.87], abs=0.1)
    rows = [json.loads(line) for line in (tmp_path / "policy-drive.jsonl").read_text().splitlines()]
    pose_row = next(row["belt_pose"] for row in rows if "belt_pose" in row and "end" not in row)
    assert {"features", "centre_mm", "offset_mm", "yaw_deg", "score"} <= set(pose_row)
    assert rows[-1]["end"] and rows[-1]["belt_pose"]["features"] == pose_row["features"]


def test_refusal_moves_nothing_and_never_starts_the_policy(tmp_path, monkeypatch, drive, capsys):
    import cell_pipeline
    import cell_policy_handoff
    import cell_policy_preflight
    import cell_stop_proof

    cell = Cell(scene((0.006, 0.02, 0.0)))  # dy +20 mm: past +-9 mm
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_: cell)
    shadow = lrs.LeRobotShadow
    monkeypatch.setattr(drive.lrs, "LeRobotShadow", lambda *a, **kw: shadow(*a, loader=lambda *_: None, **kw))
    monkeypatch.setattr(cell_stop_proof, "session_proof", lambda *a, **kw: {"ok": True, "code": "ok", "reason": ""})
    monkeypatch.setattr(cell_policy_handoff, "Authorization", lambda _cfg: None)
    monkeypatch.setattr(cell_policy_preflight, "preflight", lambda *a, **kw: pytest.fail("preflight after a refusal"))
    monkeypatch.setattr(drive, "run_episode", lambda *a, **kw: pytest.fail("policy started after a refusal"))
    monkeypatch.setattr(drive.os, "nice", lambda _inc: None, raising=False)
    args = [a for a in drive_args(tmp_path, drive, {"names": NAMES, "belt_reference": REFERENCE}) if a != "--dry-run"]
    assert drive.main([*args, "--person-at-switch"]) == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["result"] == "refused" and out["reason_code"] == bp.OUT_OF_RANGE and out["parked"] is False
    assert out["belt_pose"]["features"][1] == pytest.approx(2.0, abs=0.12) and cell.commands == []
    (tmp_path / "model" / lrs.ENV_STATE).write_text(json.dumps({"names": NAMES}))  # declared, no reference
    assert drive.main([*args, "--person-at-switch"]) == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["reason_code"] == bp.UNKNOWN and "NOT_AVAILABLE" in out["reason"] and cell.commands == []


def test_goal_names_must_be_the_cell_slots(tmp_path, monkeypatch, drive):
    import cell_pipeline

    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_: Cell(scene((0.006, 0, 0))))
    shadow = lrs.LeRobotShadow
    monkeypatch.setattr(drive.lrs, "LeRobotShadow", lambda *a, **kw: shadow(*a, loader=lambda *_: None, **kw))
    swapped = [GOALS[1], GOALS[0], *GOALS[2:], *bp.BELT_NAMES]
    with pytest.raises(SystemExit) as error:
        drive.main(drive_args(tmp_path, drive, {"names": swapped, "belt_reference": REFERENCE}))
    assert error.value.code == 2
