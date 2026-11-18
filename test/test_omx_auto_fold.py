"""D-1048: a held, extended arm folds home on its own only along a clear, reserved corridor; otherwise it holds."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts" / "foundation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_auto_fold as af  # noqa: E402

HOME = [0.0, -58.0, 50.0, 50.0, -5.0, 46.6]
REACH = [20.0, -20.0, 20.0, 45.0, -5.0, 46.6]
CLOSED = 46.6
TORQUE0 = {str(i): 0 for i in range(11, 17)}


class Cell:
    def __init__(self, state, target=None, park_ok=True, refuse=()):
        self.state, self.target = list(state), list(target or state)
        self.park_ok, self.refuse, self.commands = park_ok, set(refuse), []

    def act(self, command):
        self.commands.append(command)
        verb = command.split()[0]
        if verb in self.refuse:
            return {"ok": False, "error": f"{verb} refused", "state": self.state, "target": self.target}
        if command.startswith("jog shoulder_pan.pos"):
            self.state[0] += float(command.split()[-1])
            self.target[0] += float(command.split()[-1])
        if verb == "park" and self.park_ok:
            self.state, self.target = list(HOME), list(HOME)
            return {"ok": True, "settled": True, "state": self.state, "target": self.target}
        if verb == "park":
            return {"ok": False, "contact": True, "error": "contact in park", "state": self.state}
        return {"ok": True, "state": self.state, "target": self.target}


def run(cell, blocked=(), reserve_ok=True, rise="risen", low=True):
    seen, booked, released = [], [], []

    def look(frames):
        seen.append(frames)
        return {"clear": len(seen) - 1 not in blocked, "low": [], "high": [], "off_map": 0, "off_surface": 0}

    def reserve(frames):
        booked.append(frames)
        return {"ok": reserve_ok, "reason": None if reserve_ok else "other arm"}

    result = af.recover(cell, HOME, CLOSED, plan=lambda s: [s, HOME], look=look, reserve=reserve,
                        release=lambda: released.append(1), release_and_rise=lambda c: {"result": rise},
                        low=lambda s: low)
    return result, seen, booked, released


def test_clear_park_path_folds_home_after_reserving_it():
    cell = Cell(REACH)
    result, seen, booked, released = run(cell)
    assert result["result"] == "folded" and result["candidate"] == "park"
    assert cell.commands == ["state", "park"] and len(booked) == 1 and released == [1]


def test_blocked_park_path_detours_around_by_pan_after_checking_the_detour():
    cell = Cell(REACH)
    result, seen, booked, _ = run(cell, blocked=(0,))
    assert result["candidate"] == "pan+5" and "jog shoulder_pan.pos 5.0" in cell.commands
    assert cell.commands.index("jog shoulder_pan.pos 5.0") < cell.commands.index("park")
    assert len(seen) == 2 and seen[1][0] == REACH and seen[1][1][0] == REACH[0] + 5  # the detour itself was checked


def test_everything_blocked_holds_with_torque_on_and_never_moves():
    cell = Cell(REACH)
    result, *_ = run(cell, blocked=(0, 1, 2, 3, 4))
    assert result["result"] == "held" and result["reason"] == "ALL_PATHS_BLOCKED"
    assert cell.commands == ["state", "human-hold"]  # no motion, no stop (torque stays ON out on the reach)


def test_jaws_on_a_box_low_let_go_after_the_rise_is_checked():
    box = Cell([*REACH[:5], CLOSED + 10], target=[*REACH[:5], CLOSED])
    result, seen, booked, _ = run(box)
    assert result["result"] == "folded" and len(seen[0]) == 2 and seen[0][1][1] == REACH[1] - af.RISE_UNITS
    high = Cell([*REACH[:5], CLOSED + 10], target=[*REACH[:5], CLOSED])
    result, *_ = run(high, low=False)
    assert result["reason"] == "HOLDING_HIGH" and high.commands == ["state", "human-hold"]  # never dropped from up high
    blocked = Cell([*REACH[:5], CLOSED + 10], target=[*REACH[:5], CLOSED])
    result, *_ = run(blocked, blocked=(0,))
    assert result["reason"] == "RISE_BLOCKED" and "park" not in blocked.commands
    stuck = Cell([*REACH[:5], CLOSED + 10], target=[*REACH[:5], CLOSED])
    result, *_ = run(stuck, rise="stuck")
    assert result["reason"] == "RELEASE_STUCK" and "park" not in stuck.commands


def test_open_approach_jaws_are_not_holding():
    assert af.holding([*REACH[:5], 60.0], [*REACH[:5], 60.0], CLOSED) is False
    assert af.holding([*REACH[:5], 56.0], [*REACH[:5], CLOSED], CLOSED) is True


def test_other_arm_reservation_or_a_short_park_holds():
    cell = Cell(REACH)
    result, *_ = run(cell, reserve_ok=False)
    assert "park" not in cell.commands and result["result"] == "held"
    short = Cell(REACH, park_ok=False)
    result, *_ = run(short)
    assert result["result"] == "held" and result["reason"] == "PARK_NOT_HOME" and short.commands[-1] == "human-hold"


FACTS = {"torque_after": TORQUE0, "latched": {}, "windup_hits": [], "stops": [{"error": "contact in lift"}],
         "flagged": [{"command": "run lift", "error": "contact in lift: elbow lag 3.0"}], "fault_records": [],
         "home": HOME}


def test_evidence_is_what_the_fleet_rule_reads_for_that_incident():
    from core_common.protocol.arm_incidents import clearable_after_fold

    result, *_ = run(Cell(REACH))
    proof = af.evidence(result, HOME, TORQUE0, "inc-1", 1000.0)
    assert clearable_after_fold(FACTS, proof, "inc-1", 990.0)[0] is True
    for facts in ({**FACTS, "latched": {"13": {"hw_error": 32}}}, {**FACTS, "windup_hits": [{"reason": "cable"}]},
                  {k: v for k, v in FACTS.items() if k != "home"}, {**FACTS, "fault_records": ["f.json"]}):
        assert clearable_after_fold(facts, proof, "inc-1", 990.0)[0] is False
    for bad in ({"folded_state": REACH}, {"torque_after": {"11": 1, **{str(i): 0 for i in range(12, 17)}}},
                {"torque_after": {"gripper": 0}}, {"corridor_clear": False}, {"home": [5.0, *HOME[1:]]}):
        assert clearable_after_fold(FACTS, {**proof, **bad}, "inc-1", 990.0)[0] is False, bad
    assert clearable_after_fold(FACTS, proof, "inc-2", 990.0)[0] is False  # evidence for another incident
    assert clearable_after_fold(FACTS, proof, "inc-1", 5000.0)[0] is False  # older than the incident
    assert clearable_after_fold(FACTS, None)[0] is False


class Link:
    def __init__(self, ids):
        self.ids = ids

    def hold(self):
        return SimpleNamespace(incident_ids=self.ids, held=bool(self.ids), reason="x")


def _conf(tmp_path):
    conf, cwd = tmp_path / "auto-fold.json", tmp_path / "prep"
    cwd.mkdir()
    conf.write_text(json.dumps({"arm_s": {"wrapper": "w.sh", "config": "c.json", "library": "l.json", "site": "pinky",
                                          "roi": [0, 0, 10, 10], "cwd": str(cwd)}}))
    return conf, cwd


def test_launch_folds_one_incident_once_and_clears_it_with_bound_evidence(tmp_path, monkeypatch):
    import omx_incident

    monkeypatch.setattr(omx_incident, "INCIDENTS", tmp_path / "incidents")
    conf, cwd = _conf(tmp_path)
    calls, clears = [], []

    def run_fn(command, **kw):
        calls.append((command, kw["env"]["ROSY_RECOVERY_INCIDENT"], kw["timeout"]))
        Path(command[command.index("--out") + 1]).write_text(json.dumps(
            {"result": "folded", "candidate": "park", "state": HOME, "home": HOME, "corridor": {"clear": True}}))
        (cwd / "session.json").write_text(json.dumps({"torque_after": TORQUE0}))
        return SimpleNamespace(stdout="", stderr="")

    clear = lambda *a, **k: clears.append((a, k))  # noqa: E731
    out = af.launch("arm_s", conf, link=Link(["inc-1"]), run=run_fn, sleep=lambda s: None, clear=clear)
    assert out["result"] == "cleared" and calls[0][1] == "inc-1" and "--arm" in calls[0][0] and calls[0][2] >= 3600
    assert clears[0][1]["only"] == "inc-1" and clears[0][1]["recovery"]["incident_id"] == "inc-1"
    again = af.launch("arm_s", conf, link=Link(["inc-1"]), run=run_fn, sleep=lambda s: None, clear=clear)
    assert again["result"] == "skipped" and len(calls) == 1  # one try per incident
    assert af.launch("arm_s", conf, link=Link(["a", "b"]), run=run_fn, clear=clear)["result"] == "skipped"


def test_launch_never_sends_a_stale_session(tmp_path, monkeypatch):
    import omx_incident

    monkeypatch.setattr(omx_incident, "INCIDENTS", tmp_path / "incidents")
    conf, cwd = _conf(tmp_path)

    def run_fn(command, **kw):
        Path(command[command.index("--out") + 1]).write_text(json.dumps(
            {"result": "folded", "candidate": "park", "state": HOME, "home": HOME, "corridor": {"clear": True}}))
        return SimpleNamespace(stdout="", stderr="")

    clears = []
    out = af.launch("arm_s", conf, link=Link(["inc-9"]), run=run_fn, sleep=lambda s: None,
                    clear=lambda *a, **k: clears.append(1))
    assert out["result"] == "not_cleared" and clears == []


def test_recovery_session_opens_only_for_the_one_named_incident(monkeypatch):
    import omx_incident

    monkeypatch.setattr(omx_incident, "_probe_hold", lambda arm, link=None: (True, "held"))
    omx_incident.refuse_if_held("arm_s", Link(["inc-1"]), allow_incident="inc-1")
    for ids, allow in ((["inc-1", "inc-2"], "inc-1"), (["inc-2"], "inc-1"), (["inc-1"], None)):
        with pytest.raises(SystemExit):
            omx_incident.refuse_if_held("arm_s", Link(ids), allow_incident=allow)


def test_launch_is_off_without_its_config(tmp_path, monkeypatch):
    import omx_incident

    monkeypatch.setenv("ROSY_AUTO_FOLD_CONFIG", str(tmp_path / "missing.json"))
    assert omx_incident.launch_auto_fold("arm_s", popen=lambda *a, **k: 1 / 0)["started"] is False
    conf = tmp_path / "auto-fold.json"
    conf.write_text(json.dumps({"arm_s": {}}))
    monkeypatch.setenv("ROSY_AUTO_FOLD_CONFIG", str(conf))
    started = []
    assert omx_incident.launch_auto_fold("arm_s", popen=lambda *a, **k: started.append(a))["started"] is True
    assert omx_incident.launch_auto_fold("arm_b", popen=lambda *a, **k: started.append(a))["started"] is False
