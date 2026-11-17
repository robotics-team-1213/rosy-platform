"""Fake Rosy Learning producer directories and sim-format stand-ins for test_two_arm_export (no pytest, so the learner venv can run them too)."""
import hashlib
import json
from pathlib import Path
import sys
import ast

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(ROOT / "deploy/robot/omx"), str(ROOT / "tools/sim")]
import cv2  # noqa: E402
import cell_act_inputs as inputs  # noqa: E402
import omx_two_arm_policy_helpers as helpers  # noqa: E402
import two_arm_export as export  # noqa: E402

T0, FPS = 1000.0, 15
RULE = {"held_30mm": 52.3, "gap_mm_per_unit": 5.0}
CLOCK = "host-monotonic:test-boot"
COLORS = {"top": (10, 0, 0), "side": (0, 20, 0), "a_wrist": (0, 0, 30), "b_wrist": (40, 40, 0)}  # BGR


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_source(root, ticks=40, *, skip=None, units=export.FOLLOWER_UNITS, clock=CLOCK):
    """The six producer directories, an event every 1/15 s from T0. `skip`: {producer name: set of ticks it publishes nothing at}."""
    skip = skip or {}
    for arm in inputs.ARMS:
        base = {"owner_id": f"{arm}:chunk_runner", "source_identity": f"omx-cell:{arm}", "session_epoch": f"epoch-{arm}", "clock_domain": clock,
                "joint_names": list(inputs.JOINTS), "state_units": units, "action_units": units, "calibration_revision": "cal", "profile_revision": "p",
                "reference_stage": "post_guard_accepted"}
        _write(root / arm / "descriptor.json", {"kind": "arm", "rate_hz": 15.0, "grip_rule": RULE, **base})
        for k in range(ticks):
            if k in skip.get(arm, ()):
                continue
            t = T0 + k / FPS
            _write(root / arm / "events" / f"{k}.json", {
                "schema": export.ARM_SCHEMA, "sequence": k, **base, "state_timestamp": t, "reference_timestamp": t,
                "state": [k % 5, -k % 7, 3, 0, 1, 50.0], "accepted_reference": [k % 5 + 1, -k % 7, 3, 0, 1, 20.0 + k % 3], "reference_id": f"live@{t}"})
    for view in inputs.VIEWS:
        name = export.SOURCES[view]
        base = {"source_identity": f"cam:{view}", "session_epoch": f"epoch-{view}", "clock_domain": clock, "shape": [3, 24, 32], "timestamp_semantics": "host_receive"}
        _write(root / name / "descriptor.json", {"kind": "camera", "rate_hz": 15.0, **base})
        for k in range(ticks):
            if k in skip.get(view, ()):
                continue
            image = np.zeros((24, 32, 3), np.uint8)
            image[:] = COLORS[view]
            jpeg = cv2.imencode(".jpg", image)[1].tobytes()
            (root / name / "events").mkdir(parents=True, exist_ok=True)
            (root / name / "events" / f"{k}.jpg").write_bytes(jpeg)
            _write(root / name / "events" / f"{k}.json", {"schema": export.CAMERA_SCHEMA, "sequence": k, **base, "timestamp": T0 + k / FPS,
                                                           "jpeg_sha256": hashlib.sha256(jpeg).hexdigest()})
    return root


def window(name="a1", k0=0, k1=29, outcome="placed", **extra):
    return {"episode_id": name, "t_start": T0 + k0 / FPS, "t_end": T0 + k1 / FPS, "outcome": outcome, **extra}


def info_of(root):
    return json.loads((Path(root) / "meta/info.json").read_text(encoding="utf-8"))


def world_source():
    """FPS and JOINTS of the sim world, read from its source: importing it needs MuJoCo."""
    tree = ast.parse((ROOT / "tools/sim/omx_two_arm_world.py").read_text(encoding="utf-8"))
    return {t.targets[0].id: ast.literal_eval(t.value) for t in tree.body if isinstance(t, ast.Assign) and getattr(t.targets[0], "id", "") in ("FPS", "JOINTS")}


def sim_features(size=None):
    """What `collect` builds: its own `dataset_features` over the world's joints and RECORDED views."""
    names = [f"{arm}.{joint}" for arm in helpers.sites.ARMS for joint in world_source()["JOINTS"]]
    return json.loads(json.dumps(helpers.dataset_features(names, helpers.teaching.RECORDED, size)))


def sim_stand_in(root, frames, goal=None):
    """A dataset the way `collect` writes one: the same features, random pictures."""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    names = [f"{arm}.{joint}" for arm in helpers.sites.ARMS for joint in world_source()["JOINTS"]]
    dataset = LeRobotDataset.create("rosy/omx-two-arm", FPS, root=root, robot_type="omx_follower_pair",
                                    features=helpers.dataset_features(names, helpers.teaching.RECORDED, goal))
    rng = np.random.default_rng(0)
    for _ in range(frames):
        row = {"observation.state": np.zeros(12, np.float32), "action": np.zeros(12, np.float32), "task": helpers.PROMPT,
               **{f"observation.images.{v}": rng.integers(0, 255, (240, 320, 3), dtype=np.uint8) for v in inputs.VIEWS}}
        if goal:
            row[helpers.GOAL] = np.zeros(goal, np.float32)
        dataset.add_frame(row)
    dataset.save_episode()
    dataset.finalize()
    (Path(root).parent / f"{Path(root).name}.steps.json").write_text(json.dumps({"goal_mode": "joints" if goal else None}), encoding="utf-8")


