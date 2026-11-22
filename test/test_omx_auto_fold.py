"""D-1048: a held, extended arm folds home on its own only along a clear, reserved corridor; otherwise it holds."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts" / "foundation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_auto_fold as af  # noqa: E402

@pytest.fixture(autouse=True)
def _own_incidents(tmp_path, monkeypatch):  # launch writes auto-events.jsonl beside the markers: never the real ones
    import omx_incident
    import omx_incident_fleet

    monkeypatch.setattr(omx_incident_fleet, "INCIDENTS", tmp_path / "incidents")
    monkeypatch.setattr(omx_incident, "INCIDENTS", tmp_path / "incidents")


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


def run(cell, blocked=(), reserve_ok=True, rise="risen", low=True, order=None):
    seen, booked, released = [], [], []

    def look(frames):
        seen.append(frames)
        return {"clear": len(seen) - 1 not in blocked, "low": [], "high": [], "off_map": 0, "off_surface": 0}

    def reserve(frames):
        booked.append(frames)
        return {"ok": reserve_ok, "reason": None if reserve_ok else "other arm"}

    result = af.recover(cell, HOME, CLOSED, plan=lambda s: [s, HOME], look=look, reserve=reserve,
                        release=lambda: released.append(1), release_and_rise=lambda c: {"result": rise},
                        low=lambda s: low, order=order)
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


def test_hold_at_rest_near_home_ends_the_session_but_an_extended_arm_keeps_torque():
    rest = Cell([5.0, *HOME[1:]])  # 5 units off home: past the fold tolerance, inside the rest tolerance
    result, *_ = run(rest, blocked=(0, 1, 2, 3, 4))
    assert result["result"] == "held" and result["reason"] == "ALL_PATHS_BLOCKED" and result["ended"] == "stop_now"
    assert rest.commands == ["state", "state", "stop now"]  # the pose is read again right before the stop
    far = Cell([af.REST_TOL + 5.0, *HOME[1:]])
    result, *_ = run(far, blocked=(0, 1, 2, 3, 4))
    assert far.commands == ["state", "human-hold"] and "ended" not in result
    unreadable = Cell(REACH, refuse=("state",))
    result, *_ = run(unreadable)
    assert result["reason"] == "STATE_UNREADABLE" and unreadable.commands == ["state", "human-hold"]


def test_a_failed_stop_now_falls_back_to_the_human_hold():
    rest = Cell([5.0, *HOME[1:]], refuse=("stop",))
    result, *_ = run(rest, blocked=(0, 1, 2, 3, 4))
    assert rest.commands == ["state", "state", "stop now", "human-hold"] and "ended" not in result


def test_a_stalled_park_gives_no_state_to_trust_so_it_holds_with_torque():
    near = Cell([5.0, *HOME[1:]], park_ok=False)
    result, *_ = run(near)
    assert result["reason"] == "PARK_NOT_HOME" and near.commands[-1] == "human-hold"  # park gave no state to trust


def test_order_changes_only_the_order_of_the_same_candidates():
    names = []

    def order(offered):
        names.append(list(offered))
        return ["pan-5", *[n for n in offered if n != "pan-5"]]

    cell = Cell(REACH)
    result, *_ = run(cell, order=order)
    assert names == [af.candidate_names()] and result["candidate"] == "pan-5"
    assert cell.commands.index("jog shoulder_pan.pos -5.0") < cell.commands.index("park")
    plain = Cell(REACH)
    assert run(plain)[0]["candidate"] == "park"


def test_learned_outcome_is_written_to_the_choices_file_named_in_the_result(tmp_path):
    from cell_choices import Choices

    path = tmp_path / "choices.json"
    seed = Choices(path)
    for name in af.candidate_names():
        seed.offer(af.CHOICE, name, "D-1048")
    seed.save()
    af._learn({"choices_path": str(path), "candidate": "park", "result": "held", "reason": "PARK_NOT_HOME"}, False)
    af._learn({"choices_path": str(path), "candidate": None}, False)  # nothing moved: nothing recorded
    af._learn({"choices_path": str(path), "candidate": "already_home"}, True)
    af._learn({"candidate": "park"}, True)
    data = Choices(path).data["values"][af.CHOICE]
    assert [(c["value"], c["tries"], c["ok"]) for c in data if c["tries"]] == [("park", 1, 0)]
    assert Choices(path).ranked(af.CHOICE, af.candidate_names())[-1] == "park"  # a failed one drops behind untried ones


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
    from core_common.protocol.arm_incident.arm_incidents import clearable_after_fold

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


def test_supervised_recover_releases_torque_only_when_unmoved_and_runs_without_incident(tmp_path, monkeypatch):
    import cell_corridor
    import cell_objects
    import cell_pipeline as cp
    import cell_place_fit
    import cell_space

    # Unmoved block / holding high under release_unmoved=True ends cleanly with 'stop now' instead of human-hold
    blocked = Cell(REACH)
    res_blk = af.recover(blocked, HOME, CLOSED, plan=lambda s: [s, HOME],
                         look=lambda f: {"clear": False, "low": [], "high": []},
                         reserve=lambda f: {"ok": True}, release=lambda: None,
                         release_and_rise=lambda c: {"result": "risen"}, low=lambda s: True,
                         release_unmoved=True)
    assert res_blk["ended"] == "stop_now" and res_blk["unmoved"] is True
    assert blocked.commands == ["state", "stop now"]

    # After moving (short park or failed detour): STILL latches human-hold even with release_unmoved=True
    short = Cell(REACH, park_ok=False)
    res_short = af.recover(short, HOME, CLOSED, plan=lambda s: [s, HOME],
                           look=lambda f: {"clear": True, "low": [], "high": []},
                           reserve=lambda f: {"ok": True}, release=lambda: None,
                           release_and_rise=lambda c: {"result": "risen"}, low=lambda s: True,
                           release_unmoved=True)
    assert res_short["reason"] == "PARK_NOT_HOME" and short.commands[-1] == "human-hold"

    # CLI: --supervised runs without ROSY_RECOVERY_INCIDENT while missing --supervised + env still errors
    monkeypatch.delenv("ROSY_RECOVERY_INCIDENT", raising=False)
    cfg = tmp_path / "cfg.json"
    cal = tmp_path / "cal.json"
    lib = tmp_path / "lib.json"
    out = tmp_path / "out.json"
    cal.write_text("{}")
    cfg.write_text(json.dumps({
        "io": str(tmp_path / "io"), "cameras": {}, "calibration_path": str(cal),
        "work_dir": str(tmp_path), "space_dir": str(tmp_path / "space"),
        "sites": {"pinky": {"surface_px": [[0, 0], [10, 0], [10, 10], [0, 10]]}},
    }))
    lib.write_text(json.dumps({"fps": 30, "gripper_closed": CLOSED, "chunks": {"home": [HOME]}}))
    with pytest.raises(SystemExit):
        af.main(["--arm", "arm_s", "--config", str(cfg), "--library", str(lib),
                 "--site", "pinky", "--roi", "0", "0", "10", "10", "--out", str(out)])

    fake_cell = Cell(REACH)
    monkeypatch.setattr(cell_place_fit, "with_tiers", lambda data: [data])
    monkeypatch.setattr(cp, "FifoCell", lambda *a, **k: SimpleNamespace(
        act=fake_cell.act, frame=lambda role: "img"))
    monkeypatch.setattr(cell_objects, "foreground", lambda *a, **k: "mask")
    monkeypatch.setattr(cell_corridor, "check", lambda *a, **k: {"clear": True, "low": [], "high": [], "off_map": 0, "off_surface": 0})
    monkeypatch.setattr(cell_corridor, "runs", lambda pts: (pts, []))
    monkeypatch.setattr(cell_corridor, "corridor", lambda *a, **k: "lane")
    monkeypatch.setattr(cell_space, "Space", lambda *a: SimpleNamespace(
        reserve=lambda *a, **k: {"ok": True}, release=lambda *a: None))
    rc = af.main(["--supervised", "--arm", "arm_s", "--config", str(cfg), "--library", str(lib),
                  "--site", "pinky", "--roi", "0", "0", "10", "10", "--out", str(out)])
    written = json.loads(out.read_text())
    assert rc == 0 and written["result"] == "folded" and written["supervised"] is True and written["incident_id"] is None
    assert "park" in fake_cell.commands and "stop" in fake_cell.commands

    # R3 edge regressions:
    # (1) Pan detour failure (PARK_NOT_HOME / DETOUR_REFUSED) with release_unmoved=True keeps human-hold (no KeyError 'yes')
    detour_cell = Cell(REACH, park_ok=False)
    res_detour = af.recover(detour_cell, HOME, CLOSED, plan=lambda s: [s, HOME],
                            look=lambda f: {"clear": len(f) > 2, "low": [], "high": []},
                            reserve=lambda f: {"ok": True}, release=lambda: None,
                            release_and_rise=lambda c: {"result": "risen"}, low=lambda s: True,
                            release_unmoved=True)
    assert res_detour["reason"] == "PARK_NOT_HOME" and detour_cell.commands[-1] == "human-hold"
    detour_ref = Cell(REACH, refuse=("jog",))
    res_ref = af.recover(detour_ref, HOME, CLOSED, plan=lambda s: [s, HOME],
                         look=lambda f: {"clear": len(f) > 2, "low": [], "high": []},
                         reserve=lambda f: {"ok": True}, release=lambda: None,
                         release_and_rise=lambda c: {"result": "risen"}, low=lambda s: True,
                         release_unmoved=True)
    assert res_ref["reason"] == "DETOUR_REFUSED" and detour_ref.commands[-1] == "human-hold"

    # (2) Held load (HOLDING_HIGH / RISE_BLOCKED) with release_unmoved=True never cuts torque (never sends stop now)
    high_cell = Cell([*REACH[:5], CLOSED + 10], target=[*REACH[:5], CLOSED])
    res_high = af.recover(high_cell, HOME, CLOSED, plan=lambda s: [s, HOME],
                          look=lambda f: {"clear": True, "low": [], "high": []},
                          reserve=lambda f: {"ok": True}, release=lambda: None,
                          release_and_rise=lambda c: {"result": "risen"}, low=lambda s: False,
                          release_unmoved=True)
    assert res_high["reason"] == "HOLDING_HIGH" and high_cell.commands == ["state", "human-hold"]

    # (3) Space() failure right after FifoCell init in main(--supervised) cleanly sends stop now (no UnboundLocalError)
    monkeypatch.setattr(cell_space, "Space", lambda *a: (_ for _ in ()).throw(RuntimeError("space dir bad")))
    err_cell = Cell(REACH)
    monkeypatch.setattr(cp, "FifoCell", lambda *a, **k: SimpleNamespace(act=err_cell.act))
    rc_err = af.main(["--supervised", "--arm", "arm_s", "--config", str(cfg), "--library", str(lib),
                      "--site", "pinky", "--roi", "0", "0", "10", "10", "--out", str(out)])
    written_err = json.loads(out.read_text())
    assert rc_err == 3 and written_err["ended"] == "stop_now" and written_err["unmoved"] is True and "stop now" in err_cell.commands
