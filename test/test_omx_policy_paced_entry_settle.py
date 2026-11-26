"""Paced ACT start after the entry chunk waits for the arm to settle (2026-11-26 arm_b)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from test_omx_policy_drive import Cell, SimPolicy, drive, write_lib  # noqa: E402


def test_paced_entry_waits_while_the_jaws_finish_opening(tmp_path, monkeypatch):
    """2026-11-26 arm_b: entry reported settled with the jaws still opening (54.90 -> 55.21), so the paced stillness
    check (STILL_TOL over all six joints against live.json) refused at once. It now re-reads for up to ~2 s."""
    import time as _t
    import cell_policy_paced as paced

    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.8, -62.2, 53.1, 51.6, 45.2, 48.8]
    canon = [6.0, -55.0, 46.5, 49.0, 40.0, 55.78]
    lib_path = write_lib(tmp_path, {
        "fps": 30, "gripper_closed": 48.8,
        "chunks": {"home": [home], "entry": [home, [0.8, -55.0, 46.5, 49.0, 45.2, 48.8], canon],
                   "reach": [home, [25.0, 18.0, 5.0, 25.0, -35.0, 57.5]]},
    })

    class CreepCell(Cell):
        def __init__(self, creep_reads):
            super().__init__(expected_chunks={"home", "entry", "reach", "policy"})
            self.state, self.target, self.creep = list(home), list(home), creep_reads

        def policy_state(self):
            jaw = self.state[5] - (0.3 if self.creep > 0 and "run entry" in self.commands else 0.0)
            return {"state": self.state[:5] + [jaw], "target": list(self.target), "t": _t.time()}

        def act(self, command):
            self.commands.append(command)
            base = command.split(" ", 3)[-1] if command.startswith("checked ") else command
            if base == "state" and "run entry" in self.commands:
                self.creep -= 1
            if base == "run entry":
                self.state, self.target = list(canon), list(canon)
            elif base == "run policy":
                self.state = self.target = [8.0, -40.0, 35.0, 45.0, 15.0, 55.8]
            elif base == "park":
                self.state, self.target = list(home), list(home)
            extra = {"human_hold_latched": True, "torque_hold_commanded": True} if base == "human-hold" else {}
            return {"state": list(self.state), "target": list(self.target), "command": base, "ok": True, "settled": True,
                    "holding": False, "health": {"current_ma": [0] * 6}, **extra}

    chunk = [[8.0, -40.0, 35.0, 45.0, 15.0, 55.8]] * 16
    settles = CreepCell(creep_reads=3)
    res = drive.run_episode(settles, SimPolicy([chunk]), lib_path, tmp_path, offset=[0] * 6, max_chunks=1,
                            dry_run=False, log=[].append, paced_chunks=True, n_action=4)
    assert res["result"] == "chunks_done" and "run policy" in settles.commands

    never = CreepCell(creep_reads=10**6)
    res = drive.run_episode(never, SimPolicy([chunk]), lib_path, tmp_path, offset=[0] * 6, max_chunks=1,
                            dry_run=False, log=[].append, paced_chunks=True, n_action=4)
    assert res["result"] == "refused" and "not stationary" in res["reason"] and "run policy" not in never.commands
