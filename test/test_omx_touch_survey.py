"""Touch survey: one probe chunk pair per reachable point, unreachable points reported, heights from the held pose."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

pytest.importorskip("yaml")
pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("touch_survey", OMX / "touch_survey.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.remove(str(OMX))

PLAN = json.loads((OMX / "grasp-plan.example.json").read_text())


class Cell:
    """Answers like the runner: descend_touch_<k> holds on a contact `stop_at` frames in, except chunks in `free`."""

    def __init__(self, lib, stop_at=40, free=()):
        self.lib, self.stop_at, self.free, self.sent, self.held = lib, stop_at, set(free), [], None

    def act(self, command):
        self.sent.append(command)
        words = command.split()
        if words[0] == "run" and words[1] not in self.free:
            self.held = self.lib["chunks"][words[1]][self.stop_at]
            return {"ok": False, "contact": True}
        if words[0] == "state":
            return {"ok": True, "state": self.held}
        return {"ok": True}


def test_each_reachable_point_gets_a_vertical_probe_and_an_unreachable_one_is_skipped():
    planner = m.Planner(PLAN)
    lib, kept, skipped = m.library(planner, [(0.0, -0.05), (0.05, -0.1)], 0.10, 0.02)
    assert kept == [(0.05, -0.1)] and skipped[0]["xy"] == [0.0, -0.05]  # singular right above the base
    frames = lib["chunks"]["descend_touch_0"]
    assert lib["chunks"]["above_0"] == [frames[0]] and "home" in lib["chunks"]
    first, last = (planner.kin.fk([m.norm_to_rad(v) for v in f[:5]]) for f in (frames[0], frames[-1]))
    assert abs(first.z - 0.10) < 2e-3 and abs(last.z - 0.02) < 2e-3
    assert abs(first.x - last.x) < 2e-3 and abs(first.y - last.y) < 2e-3


def test_the_held_pose_is_the_height_and_a_free_descent_needs_no_retreat():
    planner = m.Planner(PLAN)
    lib, kept, _ = m.library(planner, [(0.05, -0.1), (0.075, -0.1)], 0.10, 0.02)
    cell = Cell(lib, free={"descend_touch_1"})
    touched = m.survey(cell, planner, kept, log=lambda row: None)
    held = planner.kin.fk([m.norm_to_rad(v) for v in lib["chunks"]["descend_touch_0"][40][:5]])
    assert touched == [[held.x, held.y, held.z]]
    assert cell.sent == ["goto above_0", "run descend_touch_0", "state", "retreat",
                         "goto above_1", "run descend_touch_1", "goto above_1", "park"]


def test_motion_without_the_d911_flags_is_refused_before_any_port_is_opened(tmp_path, monkeypatch, capsys):
    import types

    opened = []
    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(FifoCell=lambda *a, **k: opened.append(a)))
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}")  # never read: the flags are checked first
    base = ["--config", str(cfg), "--plan", str(cfg), "--name", "n", "--kind", "object", "--x=0.05", "--y=-0.1"]
    for flags in ([], ["--commissioning"], ["--person-at-switch"]):
        assert m.main(base + flags) == 2
    assert "held" in capsys.readouterr().out and opened == []


def test_plan_only_never_touches_the_port(tmp_path, monkeypatch):
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(FifoCell=lambda *a, **k: pytest.fail("port opened")))
    (tmp_path / "plan.json").write_text(json.dumps(PLAN))
    (tmp_path / "cfg.json").write_text("{}")
    assert m.main(["--config", str(tmp_path / "cfg.json"), "--plan", str(tmp_path / "plan.json"), "--name", "n",
                   "--kind", "object", "--x=0.05", "--y=-0.1", "--plan-only"]) == 0
    assert (tmp_path / "touch-survey-n.json").exists()
