"""arm_incident_labels: a person's cause, the rule's reading and the model's guess stay apart; only a repeat or a measurement
is truth, and a pull never writes an incident twice."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arm_incident_labels as al  # noqa: E402


def incident(i, cause="blocked", basis="repeat", reading="blocked"):
    return {"incident_id": f"{i:032x}", "source_id": "arm_b", "reported_at": 100.0 + i,
            "facts": {"stop_reading": {"hypothesis": reading}, "stops": [{"error": "contact in descend_pick"}]},
            "decision": {"hold": False, "reason": "guard stop"},
            "explanation": {"seen": "jaws at the box", "suspected_cause": "contact", "model": "qwen3.5:9b"},
            "cleared": {"by": "op-7", "at": 200.0 + i, "note": "slower retry stopped at the same place", "cause": cause, "basis": basis},
            "evidence": [{"seq": 0, "camera": "top", "t_rel_s": 0.0, "kind": "tip", "sha256": "1" * 64, "bytes": 90}]}


def test_the_three_answers_stay_apart_and_only_a_repeat_or_a_measurement_is_truth():
    r = al.row(incident(1))
    assert (r["person"]["cause"], r["rule"]["hypothesis"], r["model"]["suspected_cause"]) == ("blocked", "blocked", "contact")
    assert r["truth"] and r["labels"]["origin"] == "human" and r["labels"]["status"] == "unreviewed"
    assert r["labels"]["semantic_ids"] == ["arm_stop_cause:blocked"] and "bytes" not in r["evidence"][0]
    assert not al.row(incident(2, basis="seen"))["truth"]  # pictures alone measure people, they are not truth


def test_a_pull_appends_each_incident_once_and_the_score_counts_truth_only(tmp_path):
    out = tmp_path / "labels.jsonl"
    batch = [incident(1), incident(2, "too_fast", "measured", "blocked"), incident(3, "snagged", "seen", "snagged"),
             {**incident(4), "cleared": {**incident(4)["cleared"], "cause": None}}]
    assert al.keep(batch, out) == 3 and al.keep(batch, out) == 0  # no cause, no row; the same pull again adds nothing
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert al.score(rows) == {"rows": 3, "by_basis": {"repeat": 1, "measured": 1, "seen": 1, "unknown": 0},
                              "truth": 2, "rule_read": 2, "rule_agreed": 1}
