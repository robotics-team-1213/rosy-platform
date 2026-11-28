"""Auto-release of an arm incident hold by rule id (panel 2026-11-27 C): after torque_off_folded and before ARM_INCIDENT_HELD."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts/foundation"))
import cell_incident_release as rel  # noqa: E402
import cell_job_api as api  # noqa: E402
import omx_incident_fleet  # noqa: E402
from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON  # noqa: E402

BLOCK = {"torque_after": {"11": 0, "12": 0}, "hardware_error": {"11": 0, "12": 0}, "folded": True, "max_home_err": 0.4, "stable": True}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(omx_incident_fleet, "incidents_dir", lambda: tmp_path / "incidents")
    for memory in (rel._last, rel._ticked, rel._judged, rel._last_refusal):
        memory.clear()


def fake_pipeline(allowed=True, status="evaluated", incident=None):
    calls = []

    def run(arm, **kw):
        calls.append((arm, kw))
        if kw["reassess"]:
            kw["reassess_fn"](arm, kw["config"])
        cleared = allowed
        if cleared:
            kw["clear_fn"](arm, "automatic (D-1047, score=97/100): torque OFF", "token", None, cause="software_or_config", basis="measured")
        return {"status": status, "cleared": cleared, "incident_id": "inc-1", "safety_score": 97 if allowed else 40,
                "decision": "allow" if allowed else "escalate_human", "hard_vetoes": [] if allowed else [{"code": "LATCHED"}],
                "why": "ok" if allowed else "latched", "incident_file": str(incident) if incident else None}, (0 if allowed else 2)
    return run, calls


def test_release_runs_the_pipeline_with_reassess_and_tags_clear_note_audit_and_incident(tmp_path):
    incident = tmp_path / "incidents" / "20261127T0100-arm_s" / "incident.json"
    incident.parent.mkdir(parents=True)
    run, calls = fake_pipeline(incident=incident)
    notes = []
    out = rel.after_torque_off("arm_s", pipeline=run, config=Path("cell-s.json"), reassess_fn=lambda a, c: BLOCK,
                               clear_fn=lambda arm, note, *a, **k: notes.append(note))
    assert calls[0][1]["apply"] is True and calls[0][1]["reassess"] is True
    assert out["cleared"] and out["rule"] == "torque_off_folded_remeasure"
    assert "[rule=torque_off_folded_remeasure; torque=0 hw_error=0 folded=True home_err=0.4 stable=True]" in notes[0]
    audit = json.loads((tmp_path / "incidents" / "auto-release.jsonl").read_text().splitlines()[0])
    assert audit["rule"] == "torque_off_folded_remeasure" and audit["cleared"] and audit["safety_score"] == 97 and "folded=True" in audit["measured"]
    assert json.loads(incident.with_name("release.json").read_text())["incident_id"] == "inc-1"


def test_without_a_cell_config_there_is_no_reread_and_a_veto_keeps_the_hold(tmp_path):
    run, calls = fake_pipeline(allowed=False)
    out = rel.evaluate("arm_s", "r", pipeline=run, config=None)
    assert calls[0][1]["reassess"] is False and out["cleared"] is False and out["measured"] == "no re-read"
    assert json.loads((tmp_path / "incidents" / "auto-release.jsonl").read_text())["hard_vetoes"] == ["LATCHED"]
    assert not list((tmp_path / "incidents").rglob("release.json"))


def test_pipeline_error_fails_closed_and_no_open_incident_leaves_no_audit(tmp_path):
    def boom(arm, **kw):
        raise SystemExit("lease held")

    assert rel.evaluate("arm_s", "r", pipeline=boom, config=None)["cleared"] is False
    assert "lease held" in json.loads((tmp_path / "incidents" / "auto-release.jsonl").read_text())["why"]
    (tmp_path / "incidents" / "auto-release.jsonl").unlink()
    run, _ = fake_pipeline(allowed=False, status="no_open_incident")
    rel.evaluate("arm_s", "r", pipeline=run, config=None)
    assert not (tmp_path / "incidents" / "auto-release.jsonl").exists()


@pytest.mark.parametrize("facts,held,why", [
    ({"latched": {"11": 1}}, None, "latched"),
    ({"windup_hits": [{"reason": "x"}]}, None, "wind-up"),
    ({"latched": {}, "windup_hits": []}, HOME_RECOVERY_REASON, "home recovery"),
])
def test_latch_cable_windup_and_home_recovery_stay_with_a_person(tmp_path, monkeypatch, facts, held, why):
    import omx_incident_pipeline

    incident = tmp_path / "incidents" / "20261127T0100-arm_s" / "incident.json"
    incident.parent.mkdir(parents=True)
    incident.write_text(json.dumps({"facts": facts}))
    monkeypatch.setattr(omx_incident_pipeline, "_latest_incident_file", lambda arm: incident)
    monkeypatch.setattr(omx_incident_fleet, "held", lambda arm: held)
    run, calls = fake_pipeline()
    out = rel.after_torque_off("arm_s", pipeline=run, config=None)
    assert calls == [] and out["cleared"] is False and why in out["why"]
    assert json.loads((tmp_path / "incidents" / "auto-release.jsonl").read_text())["cleared"] is False


def test_before_refusal_has_a_cooldown_and_skips_free_arms_home_recovery_and_disabled():
    ran, clock = [], [100.0]
    ev = lambda arm, rule: ran.append((arm, rule))  # noqa: E731
    held = lambda arm: {"arm_s": "held"}.get(arm)  # noqa: E731
    kw = dict(evaluate_fn=ev, now_fn=lambda: clock[0])
    rel.before_refusal(["arm_s", "arm_a"], held, **kw)
    assert ran == [("arm_s", "precheck_auto_clear")]
    clock[0] += rel.COOLDOWN_S - 1
    rel.before_refusal(["arm_s"], held, **kw)
    assert len(ran) == 1
    clock[0] += 2
    rel.before_refusal(["arm_s"], held, **kw)
    assert len(ran) == 2
    rel.before_refusal(["arm_s"], held, enabled=False, **{**kw, "now_fn": lambda: 9999.0})
    rel.before_refusal(["arm_b"], lambda a: HOME_RECOVERY_REASON, **kw)
    rel.before_refusal(["arm_b"], Mock(side_effect=OSError), **kw)  # a failing check is the caller's to decide
    assert len(ran) == 2


def _runner(tmp_path, monkeypatch, holds):
    for name in ("cell-a.json", "cell-b.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/x\n", encoding="utf-8")
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    monkeypatch.setattr(api, "_check_arm_incident", lambda arm: holds.get(arm))
    monkeypatch.setattr(api.subprocess, "Popen", lambda argv, **kw: Mock(poll=Mock(return_value=None)))
    return api.Runner(tmp_path, lock_dir=tmp_path, fleet_safety_check_fn=lambda _: {"online": False, "blocked": False})


def test_api_goes_on_when_the_pre_refusal_evaluation_releases_the_hold(tmp_path, monkeypatch):
    holds = {"arm_a": "arm_a incident open"}
    runner = _runner(tmp_path, monkeypatch, holds)
    monkeypatch.setattr(rel, "evaluate", lambda arm, rule: holds.pop(arm))
    res = runner.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})
    assert res.get("error_code") != "ARM_INCIDENT_HELD" and not holds


def test_api_still_refuses_when_the_evaluation_leaves_the_hold(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch, {"arm_a": "arm_a incident open"})
    seen = []
    monkeypatch.setattr(rel, "evaluate", lambda arm, rule: seen.append(arm))
    res = runner.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})
    assert res["error_code"] == "ARM_INCIDENT_HELD" and seen == ["arm_a"]


def test_concurrent_requests_for_one_arm_share_one_reread():
    import threading

    started, release, ran = threading.Event(), threading.Event(), []

    def slow(arm, rule):
        ran.append(arm)
        started.set()
        release.wait(5)

    first = threading.Thread(target=rel.before_refusal, args=(["arm_s"], lambda a: "held"), kwargs={"evaluate_fn": slow})
    first.start()
    assert started.wait(5)
    second = threading.Thread(target=rel.before_refusal, args=(["arm_s"], lambda a: "held"), kwargs={"evaluate_fn": slow})
    second.start()
    second.join(0.3)
    assert second.is_alive()  # waits for the first instead of re-reading
    release.set()
    first.join(5)
    second.join(5)
    assert ran == ["arm_s"] and not second.is_alive() and rel._inflight == {}


@pytest.mark.parametrize("reason", [HOME_RECOVERY_REASON, "1 open arm incident(s): latched hardware error on 11", "2 open arm incident(s): wind-up before the end"])
def test_a_fleet_only_home_recovery_or_latch_hold_stays_with_a_person(tmp_path, monkeypatch, reason):
    monkeypatch.setattr(omx_incident_fleet, "held", lambda arm: None)  # the local copy knows nothing of it
    monkeypatch.setattr(rel, "fleet_hold_reason", lambda arm: reason)
    run, calls = fake_pipeline()
    out = rel.evaluate("arm_s", "r", pipeline=run, config=None)
    assert calls == [] and out["cleared"] is False and "Fleet hold" in out["why"]


def test_an_unreadable_fleet_hold_does_not_decide_and_a_plain_fleet_hold_goes_to_the_pipeline(monkeypatch):
    monkeypatch.setattr(omx_incident_fleet, "held", lambda arm: None)
    monkeypatch.setattr(rel, "fleet_hold_reason", Mock(side_effect=OSError))
    run, calls = fake_pipeline()
    assert rel.evaluate("arm_s", "r", pipeline=run, config=None, clear_fn=lambda *a, **k: None)["cleared"] and len(calls) == 1
    monkeypatch.setattr(rel, "fleet_hold_reason", lambda arm: "1 open arm incident(s): torque lost")
    assert rel.evaluate("arm_s", "r", pipeline=run, config=None, clear_fn=lambda *a, **k: None)["cleared"] and len(calls) == 2


def test_the_same_refusal_is_audited_once(tmp_path):
    run, _ = fake_pipeline(allowed=False)
    for _ in range(3):
        rel.evaluate("arm_s", "r", pipeline=run, config=None)
    assert len((tmp_path / "incidents" / "auto-release.jsonl").read_text().splitlines()) == 1


def test_api_does_not_reread_for_a_request_refused_for_another_reason(tmp_path, monkeypatch):
    runner = _runner(tmp_path, monkeypatch, {"arm_a": "arm_a incident open"})
    seen = []
    monkeypatch.setattr(rel, "evaluate", lambda arm, rule: seen.append(arm))
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, lock_dir: True)
    assert "session lock" in runner.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})["error"]
    assert runner.start("remap", {"arm": "arm_a", "config": "missing.json", "person_at_switch": True})["code"] == 400
    runner.runs["x"] = {"moving": True, "proc": Mock(poll=Mock(return_value=None)), "arms": ["arm_a"], "arm": "arm_a", "job": "j"}
    assert "already runs" in runner.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})["error"]
    assert seen == []


HELD = {"fleet_held": True, "local_held": True, "incident_ids": ["d" * 32]}
OFF = ((False,) * 6, (0,) * 6, (2048.0,) * 6)
LINK = json.loads((Path(__file__).resolve().parents[1] / "contracts/foundation/test/fixtures/arm_incidents_link"
                   / "20261118T232302-arm_s.json").read_text(encoding="utf-8"))["facts"]
CLEAN = {**LINK, "folded": True, "flagged": [], "flagged_total": 0, "fault_records": [], "fault_records_total": 0,
         "fault_record_kinds": []}  # folded, torque OFF, no hardware error, nothing flagged: 100


@pytest.mark.parametrize("facts,score,cleared", [
    (CLEAN, 100, True),
    ({**LINK, "folded": True}, 98, False),  # a bus link end: 2 points off, under the cell's 99
    ({**CLEAN, "stops": [{"command": "run park", "error": "contact in descend", "t": 1.0}]}, 0, False),  # D-1039
])
def test_watch_releases_only_at_99_and_a_hard_veto_keeps_the_hold(tmp_path, monkeypatch, facts, score, cleared):
    import omx_incident_pipeline

    monkeypatch.setattr(omx_incident_fleet, "INCIDENTS", omx_incident_fleet.INCIDENTS)  # restored after the test
    monkeypatch.setattr(omx_incident_fleet, "held", lambda arm: "held")
    monkeypatch.setattr(rel, "fleet_hold_reason", lambda arm: None)
    monkeypatch.setenv("ROSY_OMX_MOTOR_HEALTH_DIR", str(tmp_path / "mh"))
    token = tmp_path / "t.token"
    token.write_text("t")
    monkeypatch.setenv("ROSY_ARM_ASSESSOR_TOKEN_FILE", str(token))
    answer = type("Hold", (), {"held": True, "incident_ids": ["d" * 32], "reason": "hold"})()
    monkeypatch.setattr(omx_incident_fleet, "link_for", lambda arm: type("Link", (), {"hold": lambda self: answer})())
    rel.use_record_dir(tmp_path / "prep")  # the record is found where the sessions write it, whatever the cwd is
    record = tmp_path / "prep" / "incidents" / "20261127T010000-arm_s" / "incident.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"arm": "arm_s", "facts": facts}))
    asked, results = [], []

    def run(arm, rule):
        results.append(rel.evaluate(arm, rule, config=None, clear_fn=lambda *a, **k: asked.append(a)))

    for _ in range(4):
        rel.watch(["arm_s"], status_fn=lambda a: HELD, state_fn=lambda a: OFF, busy_fn=lambda a: False, evaluate_fn=run)
    assert len(results) == 1 and results[0]["safety_score"] == score and results[0]["threshold"] == 99
    assert results[0]["cleared"] is cleared and len(asked) == int(cleared)


def test_watch_judges_again_only_when_the_state_changes():
    ran, now = [], {"status": HELD, "state": OFF, "busy": False}

    def tick(n=3):
        for _ in range(n):
            rel.watch(["arm_s"], status_fn=lambda a: now["status"], state_fn=lambda a: now["state"],
                      busy_fn=lambda a: now["busy"], evaluate_fn=lambda a, r: ran.append(r))
        return len(ran)

    assert tick(1) == 0  # not yet stable over two ticks
    assert tick() == 1 and ran == ["open_incident_watch"]
    now["state"] = (OFF[0], OFF[1], (2060.0,) * 6)  # jitter
    assert tick() == 1
    now["state"] = (OFF[0], OFF[1], (2100.0,) * 6)  # moved
    assert tick() == 2
    now["state"] = (OFF[0], (32, 0, 0, 0, 0, 0), now["state"][2])  # hardware error
    assert tick() == 3
    now["state"] = ((True,) * 6, OFF[1], OFF[2])  # torque ON: not judged
    assert tick() == 3
    now["state"], now["busy"] = OFF, True  # a session has the arm: wait
    assert tick() == 3
    now["busy"] = False
    assert tick() == 4
    now["state"] = None  # no evidence: hold stays, and the same state afterwards is not judged again
    assert tick() == 4
    now["state"] = OFF
    assert tick() == 4
    now["status"] = {**HELD, "fleet_held": None}  # Fleet unreachable
    assert tick() == 4
    now["status"] = {**HELD, "incident_ids": ["e" * 32]}  # a new incident
    assert tick() == 5


def test_arm_state_reads_the_passive_snapshot_and_rejects_a_stale_one(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OMX_MOTOR_HEALTH_DIR", str(tmp_path))
    motors = [{"id": i, "torque_enabled": False, "hardware_error": 0, "present_raw": 2000.0 + i} for i in range(11, 17)]
    (tmp_path / "arm_s.json").write_text(json.dumps({"observed_at": 100.0, "motors": motors}))
    assert rel.arm_state("arm_s", now_fn=lambda: 101.0)[2][0] == 2011.0
    assert rel.arm_state("arm_s", now_fn=lambda: 200.0) is None and rel.arm_state("arm_a") is None
