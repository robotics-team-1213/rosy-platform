from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
from omx_paired_reset import JOINTS, check_readbacks, prepare_start, validate_pose


def test_paired_reset_rejects_out_of_range_joint_and_different_first_observation():
    bounds = [[-1., 1.]] * 6
    with pytest.raises(ValueError, match="outside"):
        validate_pose({"arm_a": [0.] * 6, "arm_b": [2.] * 6}, bounds)
    state = {"layout_sha256": "a" * 64, "input_sha256": "b" * 64,
             "joints_rad": {"arm_a": [0.] * 6, "arm_b": [.1] * 6}}
    base = {k: state[k] for k in ("layout_sha256", "input_sha256")}
    mujoco = dict(base, engine="mujoco", initial_rad=state["joints_rad"], first_observation_rad=state["joints_rad"])
    isaac = dict(base, engine="isaac", initial_rad=state["joints_rad"], first_observation_rad=state["joints_rad"])
    assert check_readbacks(state, mujoco, isaac)["matched"]
    with pytest.raises(ValueError, match="different"):
        check_readbacks(state, mujoco, dict(isaac, input_sha256="c" * 64))
    isaac["first_observation_rad"] = {"arm_a": [0.] * 6, "arm_b": [.2] * 6}
    assert not check_readbacks(state, mujoco, isaac)["matched"]


def test_prepare_requires_camera_and_calibration_for_this_capture(tmp_path):
    capture = tmp_path / "capture.json"
    capture.write_text("{}")
    calibration = tmp_path / "joints.json"
    identity = "a" * 64
    timing = {"joint_observation": True}
    geometry = {"camera_snapshot_sha256": None, "layout_sha256": identity}
    limits = {"joints": {joint: {"position": [-1., 1.]} for joint in JOINTS[:-1]},
              "gripper": {"position": [-1., 1.]}}
    with pytest.raises(ValueError, match="accepted camera snapshot"):
        prepare_start(capture, calibration, timing, geometry, identity, limits)
    calibration.write_text(json.dumps(dict(schema="rosy.omx.calibrated-joints/1",
        capture_sha256=sha256(capture.read_bytes()).hexdigest(), joint_names=list(JOINTS),
        joints_rad={"arm_a": [0.] * 6, "arm_b": [.1] * 6})))
    geometry["camera_snapshot_sha256"] = "b" * 64
    assert prepare_start(capture, calibration, timing, geometry, identity, limits)["joints_rad"]["arm_b"] == [.1] * 6
    capture.write_text('{"new": true}')
    with pytest.raises(ValueError, match="different capture"):
        prepare_start(capture, calibration, timing, geometry, identity, limits)
