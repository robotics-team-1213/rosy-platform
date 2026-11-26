"""Two-arm policy entry stage: both arms take the reviewed entry chunk before any policy chunk (2026-11-26)."""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import time

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
_ADDED = [str(ROOT / "deploy/robot/omx"), str(ROOT / "middleware/devices/omx/adapter"), str(ROOT / "learning/training/omx")]
for _p in _ADDED:
    sys.path.insert(0, _p)
try:
    import cell_two_arm_entry as entry_mod  # noqa: E402
    import cell_two_arm_guard as guard_mod  # noqa: E402
    import cell_two_arm_policy as pol_mod  # noqa: E402
finally:
    for _p in _ADDED:
        if _p in sys.path:
            sys.path.remove(_p)

HOME = {"a": [-40.0, -40.0, 40.0, 40.0, 0.0, 50.0], "b": [40.0, -40.0, 40.0, 40.0, 0.0, 50.0]}
ENTRY = {"a": [-30.0, -20.0, 30.0, 30.0, 0.0, 50.0], "b": [30.0, -20.0, 30.0, 30.0, 0.0, 50.0]}


class PlanarKin:
    def link_points(self, joints_rad, fingertip_m=0.074):
        pan, lift = float(joints_rad[0]), float(joints_rad[1])
        p_mid = (0.084 * np.cos(pan), 0.084 * np.sin(pan), 0.14)
        p_tip = (0.14 * np.cos(pan), 0.14 * np.sin(pan), max(-0.08, 0.14 - 0.12 * max(0.0, lift)))
        return [(0.0, 0.0, 0.1), p_mid, p_mid, p_tip, p_tip, p_tip], (0.0, 0.0, -1.0)


class FakeCell:
    def __init__(self, arm, *, fail_run=False, fail_load=False):
        self.arm, self.pose, self.fail_run, self.fail_load = arm, list(HOME[arm]), fail_run, fail_load
        self.commands: list[str] = []

    def act(self, cmd):
        self.commands.append(cmd)
        if cmd == "state":
            return {"ok": True, "state": list(self.pose), "holding": False, "t": time.time()}
        if cmd == "human-hold":
            return {"ok": True, "command": "human-hold", "human_hold_latched": True, "torque_hold_commanded": True, "state": list(self.pose)}
        if " load " in cmd:
            return {"ok": False, "error": "load_rejected"} if self.fail_load else {"ok": True}
        if cmd.endswith("run entry"):
            if self.fail_run:
                return {"ok": False, "command": cmd, "error": "runner_refused", "settled": False, "state": list(self.pose)}
            self.pose = list(ENTRY[self.arm])
            return {"ok": True, "command": cmd, "settled": True, "holding": False, "state": list(self.pose)}
        return {"ok": True, "settled": True, "state": list(self.pose)}

    def moves(self):
        return [c for c in self.commands if "run " in c or " load " in c]

    def holds(self):
        return [c for c in self.commands if c == "human-hold"]


def _lib(arm, *, entry=True):
    chunks = {"home": [HOME[arm]]}
    if entry:
        chunks["entry"] = [HOME[arm], ENTRY[arm]]
    return {"fps": 30.0, "gripper_closed": 10.0, "chunks": chunks}


def _auth(lib, state, seq, **_kw):
    return {"session_id": "s", "library_sha256": "h"}


def _setup(tmp_path, *, entry=True, **cell_kw):
    cells = {"a": FakeCell("a", **cell_kw.get("a", {})), "b": FakeCell("b", **cell_kw.get("b", {}))}
    libs = {"a": _lib("a", entry=entry), "b": _lib("b", entry=entry)}
    guard = guard_mod.TwoArmChunkGuard(
        {"a": PlanarKin(), "b": PlanarKin()}, {"a": (0.0, 0.0, -0.25), "b": (0.0, 0.0, 0.25)}, {"a": 0.074, "b": 0.074},
        margin_m=0.02, min_z_m=-0.05,
    )
    return cells, libs, guard


def _run(tmp_path, cells, libs, guard, **kw):
    kw.setdefault("authorizers", {"a": _auth, "b": _auth})
    return entry_mod.run_two_arm_entry(cells, libs, guard, tmp_path / "entry", kins={"a": PlanarKin(), "b": PlanarKin()}, **kw)


def test_both_arms_enter_in_order_without_a_policy_command(tmp_path):
    cells, libs, guard = _setup(tmp_path)
    res = _run(tmp_path, cells, libs, guard)
    assert res["result"] == "entered" and res["arms"]["a"]["outcome"] == res["arms"]["b"]["outcome"] == "entered"
    for cell in cells.values():
        assert [c.split(" ", 3)[-1].split(" ")[0] for c in cell.moves()] == ["load", "run"]
        assert any(c.endswith("run entry") and c.startswith("checked s h ") for c in cell.commands)
        assert not any("run policy" in c for c in cell.commands) and not cell.holds()
    assert cells["a"].pose == ENTRY["a"] and cells["b"].pose == ENTRY["b"]
    assert guard.stopped_reason is None


def test_arm_a_entry_failure_holds_both_and_b_never_moves(tmp_path):
    cells, libs, guard = _setup(tmp_path, a={"fail_run": True})
    res = _run(tmp_path, cells, libs, guard)
    assert res["result"] == "refused" and guard.stopped_reason and "a:entry" in guard.stopped_reason
    assert cells["b"].moves() == [] and cells["b"].holds()
    assert cells["a"].holds()
    # the policy stage after a failed entry sends no policy command
    out = pol_mod.run_two_arm_policy(
        cells, {"a": SimpleNamespace(), "b": SimpleNamespace()}, libs, guard,
        {"src": "belt", "dst": "temp_a:r1-s1-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"}, tmp_path / "pol",
        authorizers={"a": _auth, "b": _auth},
    )
    assert out["result"] != "chunks_done"
    sent = [c for cell in cells.values() for c in cell.commands if "run policy" in c or "chunk-" in c]
    assert sent == [], (sent, [cell.commands for cell in cells.values()])


def test_arm_b_entry_failure_stops_arm_a(tmp_path):
    cells, libs, guard = _setup(tmp_path, b={"fail_load": True})
    res = _run(tmp_path, cells, libs, guard)
    assert res["result"] in ("refused", "fault") and res["arms"]["a"]["outcome"] == "entered"
    assert cells["a"].holds() and cells["b"].holds()
    assert not any(c.endswith("run entry") for c in cells["b"].commands)


def test_state_gate_verdict_after_entry_stops_both(tmp_path):
    cells, libs, guard = _setup(tmp_path)
    gate = SimpleNamespace(roll_error=lambda s: None, verdict=lambda s, after_entry: "POLICY_START_POSE_MISMATCH" if after_entry else None)
    res = _run(tmp_path, cells, libs, guard, state_gates={"a": gate})
    assert res["result"] == "refused" and "POLICY_START_POSE_MISMATCH" in res["reason"]
    assert cells["b"].moves() == [] and cells["a"].holds() and cells["b"].holds()


def test_arm_off_home_refuses_before_any_motion(tmp_path):
    cells, libs, guard = _setup(tmp_path)
    cells["a"].pose = list(ENTRY["a"])
    res = _run(tmp_path, cells, libs, guard)
    assert res["result"] == "refused" and "START_POSE_OFF_HOME" in res["reason"]
    assert cells["a"].moves() == [] and cells["b"].moves() == []


def test_dry_run_sends_nothing_but_state_and_reports_entry_end(tmp_path):
    cells, libs, guard = _setup(tmp_path)
    res = _run(tmp_path, cells, libs, guard, dry_run=True, authorizers=None)
    assert res["result"] == "dry_run" and res["arms"]["a"]["entry_end"] == ENTRY["a"]
    for cell in cells.values():
        assert set(cell.commands) == {"state"}
    assert guard.stopped_reason is None


def test_library_without_entry_is_skipped_and_live_needs_authorizers(tmp_path):
    cells, libs, guard = _setup(tmp_path, entry=False)
    assert _run(tmp_path, cells, libs, guard)["result"] == "no_entry"
    assert all(set(c.commands) <= {"state"} for c in cells.values())
    with pytest.raises(ValueError, match="authorizer"):
        _run(tmp_path, cells, libs, guard, authorizers=None)
