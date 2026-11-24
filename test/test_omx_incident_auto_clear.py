"""D-1047: the cell reports what the rule recomputes rest from, judges with Fleet's own rule and clears at once."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts" / "foundation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import omx_incident  # noqa: E402

REAL = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "foundation" / "test" / "fixtures"
                   / "arm_incidents_link" / "20261118T232302-arm_s.json").read_text(encoding="utf-8"))["facts"]
HOME = [0.0, -58.0, 50.0, 50.0, -5.0, 48.8]
LAST = [-0.02, -58.0, 55.9, 50.33, -4.91, 49.21]


def session(tmp_path, rows):
    io = tmp_path / "io"
    io.mkdir(exist_ok=True)
    (io / "chunk-status.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {"safe_end": True, "torque_after": {str(i): 0 for i in range(11, 17)}, "caps_restored": True,
            "chunks": {"io": str(io)}, "started": 0}


def test_facts_carry_the_rest_evidence_and_list_totals(tmp_path):
    rows = [{"command": "state", "ok": True, "state": LAST, "target": LAST, "t": 1.0},
            {"command": "tick", "ok": False, "state": LAST, "target": LAST, "fault": REAL["flagged"][0]["fault"],
             "person_needed": True, "t": 2.0}]
    f = omx_incident.facts(session(tmp_path, rows), HOME)
    assert f["home"] == HOME and f["last_target"] == LAST and f["last_command"] == "tick"
    assert f["flagged_total"] == 1 and f["fault_records_total"] == 0
    assert f["flagged"][0]["person_needed"] is True  # kept, so the rule can refuse it


def test_torque_off_extended_arm_enters_incident_recovery_even_after_clean_stop(tmp_path):
    extended = [0.0, -30.0, 10.0, 20.0, -5.0, 48.8]
    rows = [{"command": "state", "ok": True, "state": extended, "target": extended}]
    facts = omx_incident.facts(session(tmp_path, rows), HOME)
    assert facts["safe_end"] and not facts["folded"]
    decision = omx_incident.decide(facts)
    assert decision["hold"] and "guarded fold required" in decision["reason"]


def test_fault_record_kinds_are_read_from_the_record(tmp_path):
    record = tmp_path / "rec.json"
    record.write_text(json.dumps({"fault": "(5, 'Input/output error')", "stop_reasons": []}))
    assert omx_incident._fault_kind(record) == {"fault": "(5, 'Input/output error')", "stop_reasons": []}
    assert omx_incident._fault_kind(tmp_path / "missing.json") == {"fault": None, "stop_reasons": None}


def test_auto_clear_clears_what_the_rule_allows_and_nothing_else(tmp_path, monkeypatch):
    token = tmp_path / "cell-s-ai-assessor.token"
    token.write_text("t")
    monkeypatch.setenv("ROSY_ARM_ASSESSOR_TOKEN_FILE", str(token))
    calls = []
    clear = lambda *a, **k: calls.append((a, k))  # noqa: E731
    out = omx_incident.auto_clear("arm_s", REAL, link=object(), clear_fn=clear)
    assert out["cleared"] is True and calls[0][1] == {"cause": "software_or_config", "basis": "measured"}
    assert calls[0][0][2] == token
    calls.clear()
    moving = {**REAL, "last_command": "run descend_pick"}
    assert omx_incident.auto_clear("arm_s", moving, link=object(), clear_fn=clear)["cleared"] is False and calls == []
    assert omx_incident.auto_clear("arm_s", REAL, link=None, clear_fn=clear)["cleared"] is False


def test_a_refused_clear_keeps_the_hold(tmp_path, monkeypatch):
    token = tmp_path / "t.token"
    token.write_text("t")
    monkeypatch.setenv("ROSY_ARM_ASSESSOR_TOKEN_FILE", str(token))

    def refused(*a, **k):
        raise SystemExit("arm_s held for a person: AI_CLEAR_REPEAT_LIMIT")

    out = omx_incident.auto_clear("arm_s", REAL, link=object(), clear_fn=refused)
    assert out["cleared"] is False and "REPEAT_LIMIT" in out["why"]


def test_auto_clear_enforces_95_score_floor_and_returns_risk_fields(tmp_path, monkeypatch):
    token = tmp_path / "cell-s-ai-assessor.token"
    token.write_text("t")
    monkeypatch.setenv("ROSY_ARM_ASSESSOR_TOKEN_FILE", str(token))
    calls = []
    clear = lambda *a, **k: calls.append((a, k))  # noqa: E731

    ok = omx_incident.auto_clear("arm_s", REAL, link=object(), clear_fn=clear)
    assert ok["cleared"] is True and ok["safety_score"] == 95 and ok["risk_score"] == 5 and ok["decision"] == "auto_clear"

    calls.clear()
    # Second clear of rested REAL arm within 24h scores 93 < 95 -> escalated, clear_fn not called
    low = omx_incident.auto_clear("arm_s", REAL, link=object(), clear_fn=clear, recent_clears_24h=1)
    assert low["cleared"] is False and low["safety_score"] == 93 and low["decision"] == "escalate_human"
    assert calls == []

    # Attempting to weaken min_score below 95 fails closed
    bad = omx_incident.auto_clear("arm_s", REAL, link=object(), clear_fn=clear, min_score=90)
    assert bad["cleared"] is False and bad["safety_score"] == 0 and bad["decision"] == "escalate_human"
    assert calls == []


def test_incident_risk_pipeline_applies_only_at_95_plus_and_logs_audit(tmp_path, monkeypatch):
    import time
    import omx_incident_pipeline as pipe

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "arm-home"))
    mh_dir = tmp_path / "mh"
    mh_dir.mkdir()
    monkeypatch.setenv("ROSY_OMX_MOTOR_HEALTH_DIR", str(mh_dir))
    token = tmp_path / "cell-s-ai-assessor.token"
    token.write_text("t")
    monkeypatch.setenv("ROSY_ARM_ASSESSOR_TOKEN_FILE", str(token))

    class Link:
        def __init__(self, held=True):
            self._held = held

        def hold(self):
            return type("Hold", (), {"held": self._held, "incident_ids": ["d" * 32] if self._held else [], "reason": "hold"})()

    # 1) No open incident -> noop exit 0
    noop, code_noop = pipe.run_pipeline("arm_s", link=Link(held=False))
    assert code_noop == 0 and noop["status"] == "no_open_incident" and noop["decision"] == "noop"

    # 2) Open incident + healthy telemetry -> score 95 -> --apply clears
    import omx_incident_fleet as fleet
    t0 = time.time()
    inc_folder = fleet.incidents_dir() / "20261125T010000-arm_s"
    inc_folder.mkdir(parents=True)
    (inc_folder / "incident.json").write_text(json.dumps({"arm": "arm_s", "facts": REAL, "reported_at": t0 - 20.0}))
    fleet.keep_hold("arm_s", "link hold", ["d" * 32])
    (mh_dir / "arm_s.json").write_text(json.dumps({
        "status": "ended", "observed_at": t0 - 5.0, "stop_reasons": ["session ended"],
        "motors": [{"joint": "shoulder_lift", "temperature_c": 41.0, "temperature_limit_c": 65.0,
                    "torque_enabled": 0, "hardware_error": 0, "voltage_v": 12.1, "min_voltage_v": 9.5,
                    "max_voltage_v": 14.5, "warnings": []}],
    }))
    cleared_calls = []
    res_ok, code_ok = pipe.run_pipeline(
        "arm_s", apply=True, link=Link(held=True),
        clear_fn=lambda *a, **k: cleared_calls.append((a, k)), now_fn=lambda: t0,
    )
    assert code_ok == 0 and res_ok["decision"] == "auto_clear" and res_ok["safety_score"] == 95 and res_ok["cleared"] is True
    assert len(cleared_calls) == 1 and cleared_calls[0][1]["only"] == "d" * 32

    # 3) Elevated temperature (52C -> -3) drops REAL below 95 -> escalates (exit 2), clear_fn NOT called
    cleared_calls.clear()
    (mh_dir / "arm_s.json").write_text(json.dumps({
        "status": "ended", "observed_at": t0 + 5.0, "stop_reasons": ["session ended"],
        "motors": [{"joint": "shoulder_lift", "temperature_c": 52.0, "temperature_limit_c": 65.0,
                    "torque_enabled": 0, "hardware_error": 0}],
    }))
    res_low, code_low = pipe.run_pipeline(
        "arm_s", apply=True, link=Link(held=True),
        clear_fn=lambda *a, **k: cleared_calls.append((a, k)), now_fn=lambda: t0 + 10.0,
    )
    assert code_low == 2 and res_low["decision"] == "escalate_human" and res_low["cleared"] is False
    assert res_low["safety_score"] <= 92 and cleared_calls == []
    auto_events = [json.loads(line) for line in (tmp_path / "incidents" / "auto-events.jsonl").read_text().splitlines()]
    assert any(e["kind"] == "auto_clear" and e["result"] is True and "score=95/95" in e["why"] for e in auto_events)
    risk_events = [json.loads(line) for line in (fleet.incidents_dir() / "risk-events.jsonl").read_text().splitlines()]
    assert [e["decision"] for e in risk_events] == ["auto_clear", "escalate_human"]
    assert risk_events[0]["safety_score"] == 95 and risk_events[0]["cleared"] is True
    assert risk_events[1]["safety_score"] <= 92 and risk_events[1]["cleared"] is False

    # 4) Corrupt local HOLD JSON & unreadable motor_health fail closed to score 0 (escalate_human, exit 2)
    (mh_dir / "arm_s.json").unlink()
    fleet.hold_path("arm_s").write_text("{corrupt json", encoding="utf-8")
    cleared_calls.clear()
    res_corrupt, code_corrupt = pipe.run_pipeline(
        "arm_s", apply=True, link=Link(held=False),
        clear_fn=lambda *a, **k: cleared_calls.append((a, k)), now_fn=lambda: t0 + 20.0,
    )
    assert code_corrupt == 2 and res_corrupt["decision"] == "escalate_human" and res_corrupt["cleared"] is False
    assert res_corrupt["safety_score"] == 0 and res_corrupt["risk_score"] == 100
    assert any(v["code"] == "HOLD_UNREADABLE" for v in res_corrupt["hard_vetoes"]) and cleared_calls == []

    # 5) Corrupt motor_health JSON fails closed to score 0 even with healthy hold/incident
    fleet.keep_hold("arm_s", "link hold", ["d" * 32])
    (mh_dir / "arm_s.json").write_text("{bad motor health", encoding="utf-8")
    res_bad_mh, code_bad_mh = pipe.run_pipeline(
        "arm_s", apply=True, link=Link(held=True),
        clear_fn=lambda *a, **k: cleared_calls.append((a, k)), now_fn=lambda: t0 + 30.0,
    )
    assert code_bad_mh == 2 and res_bad_mh["decision"] == "escalate_human" and res_bad_mh["safety_score"] == 0
    assert any(v["code"] == "MOTOR_HEALTH_UNREADABLE" for v in res_bad_mh["hard_vetoes"]) and cleared_calls == []


def test_incident_risk_clear_job_spec_is_non_motion_and_enforces_95_floor(tmp_path):
    import cell_job_guards as guards
    import cell_job_spec as spec

    (tmp_path / "cell-auto-arm-s-live.json").write_text("{}", encoding="utf-8")
    job = spec.JOBS["incident_risk_clear"]
    params = {"arm": "arm_s", "config": "cell-auto-arm-s-live.json", "apply": True, "reassess": True, "min_score": 95,
              "out": "risk.json"}
    assert spec.moves_arm(job, params) is False
    _, err = guards.authorize_principal("incident_risk_clear", job, params,
                                        guards.Principal(guards.ROLE_MACHINE, "rosy-cli"), moves_arm_fn=spec.moves_arm)
    assert err is None
    argv = spec.build_argv(job, params, tmp_path)
    assert "omx_incident_pipeline.py" in argv and "--apply" in argv and "--reassess" in argv
    assert argv[argv.index("--min-score") + 1] == "95"
    with pytest.raises(ValueError, match="min_score"):
        spec.build_argv(job, {**params, "min_score": 94}, tmp_path)
