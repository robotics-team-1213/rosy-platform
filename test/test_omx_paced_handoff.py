"""Paced ACT hybrid: a settled chunk hands a measured hold to the reviewed taught carry (2026-11-26 field)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_policy_drive as drive  # noqa: E402
import cell_policy_paced as paced  # noqa: E402
from cell_policy_handoff import CellHandoff  # noqa: E402
from cell_transfer import FOLDED, RETURN_HELD  # noqa: E402

HOME = [0, -58, 51, 50, -5, 49]
LIB = {"fps": 30, "gripper_closed": 49,
       "chunks": {"home": [HOME] * 2, "reach": [HOME, [10, -40, 40, 45, -5, 49], [20, -20, 30, 40, -5, 60]]},
       "source": {"pick": {"x": 0.2, "y": 0.1, "z": 0.08, "yaw_deg": 0}}}
GRIP, TARGET = [10, -40, 40, 45, -5, 53], [10, -40, 40, 45, -5, 50]  # jaws stopped 3 units wide of a closed target


class Policy:
    image_views = {"top": (4, 4)}

    def inputs(self, state, frames):
        return {"state": state}, {}

    def infer(self, obs):
        return SimpleNamespace(chunk=[[10, -40, 40, 45, -5, 49]])


class HoldCell:
    """Empty at home until `run policy`; then the runner reports a measured hold (or not)."""

    def __init__(self, holding=True, lift_holds=True):
        self.calls, self.ran, self.holding, self.lift_holds = [], False, holding, lift_holds

    def frame(self, _view):
        return np.zeros((4, 4, 3), np.uint8)

    def act(self, command):
        self.calls.append(command)
        base = command.split(" ", 3)[-1] if command.startswith("checked ") else command
        if base == "human-hold":
            return {"command": base, "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
        if base.startswith("load "):
            return {"command": "load", "ok": True}
        if not self.ran:
            self.ran = base == "run policy"
            return {"command": base, "ok": True, "settled": True, "holding": self.holding if self.ran else False,
                    "state": GRIP if self.ran else HOME, "target": TARGET if self.ran else HOME}
        if base.startswith("run lift_pick_policy_handoff") and not self.lift_holds:
            return {"command": base, "ok": True, "settled": True, "holding": False, "state": TARGET, "target": TARGET}
        released = (base in RETURN_HELD[2:] and base != "park") or self.calls.count("park") > 1 or not self.holding
        return {"command": base, "ok": True, "settled": True, "holding": not released,
                "state": [0] * 5 + [49] if released else GRIP, "target": TARGET}


def _handoff(tmp_path, monkeypatch, pose):
    import grasp_planner

    class Planner:
        kin = SimpleNamespace(fk=lambda _joints: pose)

        def __init__(self, _plan):
            pass

        def line(self, _start, _end, _speed, _yaw, grip, _q5):
            return [TARGET, [10, -39, 40, 45, -5, grip]], 0

    monkeypatch.setattr(grasp_planner, "Planner", Planner)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    path = tmp_path / "taught.json"
    path.write_text(json.dumps(LIB))
    config = {"plan": {}, "sites": {"belt": {"surface_z": 0.05, "rim_z": 0.09}}}
    return CellHandoff(config, "belt", path, LIB, 51, tmp_path), path


def _run(cell, handoff, tmp_path, rows):
    low, high, fastest = drive.envelope(LIB)
    return paced.run_paced_chunks(cell, Policy(), LIB, tmp_path, off=np.zeros(6), max_chunks=1, dry_run=False,
                                  log=rows.append, goal={}, sim_units=False, open_g=60.0, model_closed=46.6, closed=46.6,
                                  low=low, high=high, fastest=fastest, kin=None, jaw_spec=None, resolved_tcp=None,
                                  authorize=None, handoff=handoff)


GOOD = SimpleNamespace(x=0.2, y=0.1, z=0.12, yaw=0, tool_down_error_rad=0)


def test_paced_hybrid_carries_after_a_verified_hold(tmp_path, monkeypatch):
    handoff, path = _handoff(tmp_path, monkeypatch, GOOD)
    cell, rows = HoldCell(), []
    res = _run(cell, handoff, tmp_path, rows)
    assert res["result"] == "placed"
    after = cell.calls[cell.calls.index("run policy") + 1:]
    # hold_frames + 1 settled reads, the Handoff recheck read, then the guarded lift and only the taught tail of the fold.
    assert after[:handoff.spec["hold_frames"] + 2] == ["state"] * (handoff.spec["hold_frames"] + 2)
    assert after[-len(RETURN_HELD) - 3:] == ["run lift_pick_policy_handoff", f"load {path}", *FOLDED[-len(RETURN_HELD) - 1:]]
    assert "park" not in after[:-len(RETURN_HELD) - 1] and "human-hold" not in cell.calls  # the first park is the taught fold
    facts = next(r["paced_handoff"] for r in rows if "paced_handoff" in r)
    assert facts["triggered"] and facts["holding_frames"] == handoff.spec["hold_frames"]


def test_holding_off_the_pick_pose_does_not_carry_and_holds(tmp_path, monkeypatch):
    handoff, _ = _handoff(tmp_path, monkeypatch, SimpleNamespace(**{**vars(GOOD), "x": 0.25}))
    cell, rows = HoldCell(), []
    res = _run(cell, handoff, tmp_path, rows)
    assert res == {"result": "refused", "at": 1, "reason": "ACT ended before a verified handoff", "held": True, "parked": False}
    assert cell.calls[-1] == "human-hold"
    assert "park" not in cell.calls and not any(c.startswith("run lift") for c in cell.calls)


def test_low_hold_does_not_carry(tmp_path, monkeypatch):
    handoff, _ = _handoff(tmp_path, monkeypatch, SimpleNamespace(**{**vars(GOOD), "z": 0.10}))  # below rim + margin
    cell = HoldCell()
    assert _run(cell, handoff, tmp_path, [])["result"] == "refused"
    assert cell.calls[-1] == "human-hold" and "park" not in cell.calls


def test_no_hold_keeps_parking(tmp_path, monkeypatch):
    handoff, _ = _handoff(tmp_path, monkeypatch, GOOD)
    cell = HoldCell(holding=False)
    res = _run(cell, handoff, tmp_path, [])
    assert res["result"] == "chunks_done" and res["parked"] is True
    assert cell.calls[-1] == "park" and "human-hold" not in cell.calls


def test_carry_failure_ends_in_hold_not_park(tmp_path, monkeypatch):
    handoff, _ = _handoff(tmp_path, monkeypatch, GOOD)
    cell = HoldCell(lift_holds=False)
    res = _run(cell, handoff, tmp_path, [])
    assert res["result"] == "refused" and "measured hold" in res["reason"]
    assert cell.calls[-1] == "human-hold" and "park" not in cell.calls


def test_drive_routes_a_hybrid_handoff_into_the_paced_loop(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(paced, "run_paced_chunks", lambda *a, **kw: seen.update(kw) or {"result": "dry_run"})
    marker = object()
    lib = tmp_path / "lib.json"
    lib.write_text(json.dumps(LIB))
    drive.run_episode(HoldCell(), Policy(), lib, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=True,
                      log=[].append, paced_chunks=True, handoff=marker)
    assert seen["handoff"] is marker and seen["pre_home"] is True


def test_cli_still_refuses_paced_taught(tmp_path, capsys):
    with pytest.raises(SystemExit):
        drive.main(["--config", str(tmp_path / "c.json"), "--library", str(tmp_path / "l.json"), "--mode", "taught",
                    "--goal-site", "tray", "--paced-chunks", "--dry-run", "--operator", "x"])
    assert "--paced-chunks requires act or hybrid mode" in capsys.readouterr().err


def test_job_spec_admits_paced_hybrid_and_still_refuses_paced_taught(tmp_path):
    import cell_job_spec as spec

    for name in ("cell-s.json", "chunks-s.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    base = {"arm": "arm_s", "config": "cell-s.json", "library": "chunks-s.json", "max_chunks": 1, "operator": "human_op",
            "dry_run": True, "paced_chunks": True}
    argv = spec.build_argv(spec.JOBS["cell_policy_drive"], {**base, "mode": "hybrid"}, tmp_path)
    assert "--paced-chunks" in argv and argv[argv.index("--mode") + 1] == "hybrid"
    import pytest
    with pytest.raises(ValueError, match="paced_chunks requires"):
        spec.build_argv(spec.JOBS["cell_policy_drive"], {**base, "mode": "taught"}, tmp_path)
