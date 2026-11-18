"""A policy chunk reaches the arm only as a runner chunk inside the reviewed envelope, never faster than taught (2026-11-18)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_policy_drive as drive  # noqa: E402

NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def cal(wrist_roll_homing=0):
    return {n: {"id": i, "drive_mode": 0, "homing_offset": wrist_roll_homing if n == "wrist_roll" else 0,
                "range_min": 0, "range_max": 4095} for i, n in enumerate(NAMES)}


def test_homing_difference_becomes_a_unit_offset():
    off = drive.calibration_offset(cal(957), cal(0))
    assert off[4] == pytest.approx(957 * 200 / 4095) and off[:4] == [0.0] * 4 and off[5] == 0.0
    other = cal(0)
    other["elbow_flex"]["range_max"] = 4000
    with pytest.raises(ValueError, match="not a pure homing shift"):
        drive.calibration_offset(cal(0), other)


LIB = {"fps": 30, "gripper_closed": 46.6,
       "chunks": {"home": [[0, -58, 51, 50, -5, 49]] * 2,
                  "reach": [[0, -58, 51, 50, -5, 49], [10, -40, 40, 45, -5, 49], [20, -20, 30, 40, -5, 60]]}}


def test_envelope_is_the_reviewed_range_and_fastest_step():
    low, high, fastest = drive.envelope(LIB)
    assert low == [0, -58, 30, 40, -5, 49] and high == [20, -20, 51, 50, -5, 60]
    assert fastest == pytest.approx(20.0)


def test_shape_refuses_outside_and_stretches_fast_steps():
    low, high, _ = drive.envelope(LIB)
    with pytest.raises(ValueError, match="wrist_roll"):
        drive.shape_chunk([[0, -58, 51, 50, 40, 49]], [0, -58, 51, 50, -5, 49], low, high, 2.0)
    out = drive.shape_chunk([[10, -58, 51, 50, -5, 49]], [0, -58, 51, 50, -5, 49], low, high, 2.0)
    assert len(out) == 5 and out[-1] == [10, -58, 51, 50, -5, 49]
    assert max(abs(b[0] - a[0]) for a, b in zip([[0] * 6] + out, out)) <= 2.0 + 1e-9
    with pytest.raises(ValueError, match="finite"):
        drive.shape_chunk([[np.nan] * 6], [0] * 6, low, high, 2.0)


class Policy:
    image_views = {"top": (4, 4), "wrist": (4, 4)}

    def __init__(self, chunks):
        self.chunks, self.seen = list(chunks), []

    def inputs(self, state, frames):
        self.seen.append(state)
        return {"state": state}, {"model_frame_sha256": {}}

    def infer(self, obs):
        from types import SimpleNamespace
        return SimpleNamespace(chunk=self.chunks.pop(0))


class Cell:
    def __init__(self, replies=None):
        self.commands, self.replies = [], dict(replies or {})
        self.state = [0, -58, 51, 50, -5, 49]

    def frame(self, view):
        return np.zeros((4, 4, 3), np.uint8)

    def act(self, command):
        self.commands.append(command)
        if command.startswith("load "):
            lib = json.loads(Path(command[5:]).read_text())
            assert set(lib["chunks"]) == {"home", "reach", "policy"}  # IK chunks stay beside the policy chunk
        reply = self.replies.get(command.split()[0] if command.startswith("load ") else command, {"ok": True})
        return {"state": self.state, **reply}


def write_lib(tmp_path):
    path = tmp_path / "lib.json"
    path.write_text(json.dumps(LIB))
    return path


GRASP_THEN_RELEASE = [[[5, -50, 45, 48, -5 + 46.7, 46.0]], [[5, -50, 45, 48, -5 + 46.7, 58.0]]]


def test_episode_runs_policy_chunks_then_parks_after_release(tmp_path):
    cell, rows = Cell(), []
    off = [0, 0, 0, 0, 46.7, 0]
    result = drive.run_episode(cell, Policy(GRASP_THEN_RELEASE), write_lib(tmp_path), tmp_path, offset=off,
                               max_chunks=3, dry_run=False, log=rows.append)
    assert result["result"] == "released" and result["parked"]
    assert [c.split()[0] for c in cell.commands] == ["state", "load", "run", "state", "load", "run", "park"]
    assert cell.commands[2] == "run policy"


def test_policy_sees_model_units(tmp_path):
    policy = Policy(GRASP_THEN_RELEASE)
    drive.run_episode(Cell(), policy, write_lib(tmp_path), tmp_path, offset=[0, 0, 0, 0, 46.7, 0], max_chunks=1,
                      dry_run=True, log=lambda r: None)
    assert policy.seen[0][4] == pytest.approx(-5 + 46.7)


def test_dry_run_never_loads_or_moves(tmp_path):
    cell = Cell()
    result = drive.run_episode(cell, Policy(GRASP_THEN_RELEASE), write_lib(tmp_path), tmp_path, offset=[0, 0, 0, 0, 46.7, 0],
                               max_chunks=2, dry_run=True, log=lambda r: None)
    assert result["result"] == "dry_run" and set(cell.commands) == {"state"}


def test_out_of_envelope_parks_without_loading(tmp_path):
    cell = Cell()
    result = drive.run_episode(cell, Policy([[[0, -58, 51, 50, 80, 49]]]), write_lib(tmp_path), tmp_path,
                               offset=[0] * 6, max_chunks=1, dry_run=False, log=lambda r: None)
    assert result["result"] == "refused" and cell.commands == ["state", "park"]


def test_contact_retreats_then_parks(tmp_path):
    cell = Cell({"run policy": {"ok": False, "contact": True, "error": "strain"}})
    result = drive.run_episode(cell, Policy(GRASP_THEN_RELEASE), write_lib(tmp_path), tmp_path,
                               offset=[0, 0, 0, 0, 46.7, 0], max_chunks=2, dry_run=False, log=lambda r: None)
    assert result["result"] == "contact" and cell.commands[-2:] == ["retreat", "park"]


def test_refused_load_parks(tmp_path):
    cell = Cell({"load": {"ok": False, "error": "plan_check: overload"}})
    result = drive.run_episode(cell, Policy(GRASP_THEN_RELEASE), write_lib(tmp_path), tmp_path,
                               offset=[0, 0, 0, 0, 46.7, 0], max_chunks=2, dry_run=False, log=lambda r: None)
    assert result["result"] == "refused" and cell.commands[-1] == "park" and "run policy" not in cell.commands


def test_moving_needs_person_at_switch():
    with pytest.raises(SystemExit):
        drive.main(["--config", "c", "--library", "l", "--policy-root", "p", "--policy-revision", "r",
                    "--model-calibration", "m", "--cell-calibration", "c", "--operator", "x"])
