"""cell_push: the jaws go down behind the object and sweep it along; a path with something ahead is refused."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_push as cpu  # noqa: E402
import chunk_runner  # noqa: E402

PLAN = json.loads((ROOT / "deploy/robot/omx/grasp-plan.example.json").read_text())
ROI = (0, 0, 200, 200)


def to_px(p):  # 1 px per mm, arm (0, 0.1) at pixel (100, 100)
    return (100 + p[0] * 1000, 100 + (p[1] - 0.1) * 1000)


def test_start_is_behind_the_object_and_end_moves_it_the_asked_distance():
    start, end, d = cpu.geometry((0.0, 0.1), (0, 2), 15, 35, 10)
    assert np.allclose(d, (0, 1)) and np.allclose(start, (0, 0.075)) and np.allclose(end, (0, 0.120))


def test_a_clear_path_passes_and_an_object_ahead_or_behind_is_refused():
    mask = np.zeros((200, 200), np.uint8)
    mask[85:116, 85:116] = 255  # the object itself (30 mm) is not in the way
    d = np.array([0.0, 1.0])
    assert cpu.path_clear(mask, ROI, to_px, (0.0, 0.1), d, 15, 35, 10) == []
    ahead = mask.copy()
    ahead[140:150, 90:110] = 255  # another container 40-50 mm ahead
    assert {w for w, _ in cpu.path_clear(ahead, ROI, to_px, (0.0, 0.1), d, 15, 35, 10)} == {"ahead"}
    behind = mask.copy()
    behind[72:80, 95:105] = 255  # where the jaws would go down
    assert {w for w, _ in cpu.path_clear(behind, ROI, to_px, (0.0, 0.1), d, 15, 35, 10)} == {"behind"}
    assert cpu.path_clear(mask, ROI, lambda p: None, (0.0, 0.1), d, 15, 35, 10)  # no map: never "clear"
    floor_only = [(0, 85), (200, 85), (200, 200), (0, 200)]  # behind (y 75) lies on a raised tray past the floor
    assert {w for w, _ in cpu.path_clear(mask, ROI, to_px, (0.0, 0.1), d, 15, 35, 10, floor_only)} == {"behind"}


def test_push_library_loads_in_the_runner_with_a_level_slow_slide(tmp_path):
    lib = cpu.push_library(PLAN, (0.15, -0.02), (0.15, 0.025), -14.4, 0.054, 0.010)
    path = tmp_path / "push.json"
    path.write_text(json.dumps(lib))
    loaded = chunk_runner.load_library(path)
    slide = loaded["chunks"]["slide_push"]
    assert len(slide) >= 0.045 / 0.010 * PLAN["fps"] * 0.95  # 45 mm at 1 cm/s
    assert all(f[5] == PLAN["grip_closed"] for f in slide)


class Scripted:
    def __init__(self, answers=None):
        self.answers, self.sent = answers or {}, []

    def act(self, command):
        self.sent.append(command)
        return {"ok": True, **self.answers.get(command, {})}


def test_a_strain_while_sliding_backs_out_and_folds():
    cell = Scripted({"run slide_push": {"ok": False, "contact": True}})
    out = cpu.run_push(cell, Path("lib.json"))
    assert out["result"] == "contact" and cell.sent[-2:] == ["retreat", "park"]
    cell = Scripted()
    assert cpu.run_push(cell, Path("lib.json"))["result"] == "pushed" and cell.sent[-1] == "park"
