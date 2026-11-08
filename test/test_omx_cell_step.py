"""cell_step: one body joint at a time ramps off the folded home and back, slow enough for the runner's loader."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_step  # noqa: E402
import chunk_runner  # noqa: E402

PLAN = json.loads((ROOT / "deploy/robot/omx/grasp-plan.example.json").read_text())


def test_each_ramp_moves_one_joint_and_returns_home(tmp_path):
    path = tmp_path / "step.json"
    path.write_text(json.dumps(cell_step.step_library(PLAN, 2.0, 1.0)))
    chunks = chunk_runner.load_library(path)["chunks"]  # the loader refuses frames faster than the guard streams
    home = chunks["home"][0]
    for j in range(5):
        frames = chunks[f"step_j{j + 1}"]
        moved = {i for f in frames for i, (a, b) in enumerate(zip(f, home)) if a != b}
        assert moved == {j}
        assert max(f[j] for f in frames) == pytest.approx(home[j] + 2.0) and frames[-1] == home


def test_ramps_stay_small_and_move_only_supervised():
    with pytest.raises(SystemExit, match="--units"):
        cell_step.step_library(PLAN, 5.0, 1.0)
    with pytest.raises(SystemExit, match="--hold-s"):
        cell_step.step_library(PLAN, 2.0, 30.0)
    lib = cell_step.step_library(PLAN, 0.4, 1.0)  # a short ramp rounds its frame count up, never its speed
    ramp = [f[0] for f in lib["chunks"]["step_j1"]]
    assert max(b - a for a, b in zip(ramp, ramp[1:])) * PLAN["fps"] <= cell_step.SPEED + 1e-9
    with pytest.raises(SystemExit, match="D-911"):
        cell_step.main(["--config", "nope.json"])


class Scripted:
    def __init__(self, fail=None):
        self.fail, self.sent = fail, []

    def act(self, command):
        self.sent.append(command)
        return {"ok": command != self.fail}


def test_a_stopped_ramp_parks_and_says_where():
    cell = Scripted("run step_j3")
    out = cell_step.run_steps(cell, Path("lib.json"))
    assert out["result"] == "stopped" and out["at"] == "run step_j3" and cell.sent[-1] == "park"
    assert cell_step.run_steps(Scripted(), Path("lib.json"))["result"] == "stepped"
