"""D-1047: the cell reports what the rule recomputes rest from, judges with Fleet's own rule and clears at once."""
import json
import sys
from pathlib import Path

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
