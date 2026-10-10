"""Fleet incident reviews are candidates for a recording, never pixel labels."""

import json
import sys

import incident_feedback
import pytest


def report(stuck_id="stuck-a", reviews=()):
    return {"schema": "rosy.incident.v1", "id": f"line_stuck:rosy_40:{stuck_id}",
            "stuck_id": stuck_id, "classification": "line_stuck", "robot_ids": ["rosy_40"],
            "evidence": {"core": {"cause": "lane_lost"}, "rosy_cam": None,
                         "ai_facts": [{"kind": "incident_context", "evidence": {"stuck_id": stuck_id},
                                       "value": {"cause_draft": "line_marking"}}],
                         "front_image": {"status": "not_retained"}}, "reviews": list(reviews)}


def markers(*ids):
    return {"schema": "rosy.recording.stuck_markers/1",
            "markers": [{"stuck_id": sid, "opened_at": "2026-10-10T00:00:00Z"} for sid in ids]}


def test_exact_stuck_id_review_stays_candidate_and_drops_identity():
    reviewed = {"at": "2026-10-10T01:00:00Z", "principal_id": "operator-robttt",
                "root_cause": "line_marking", "note": "private operator note"}
    result = incident_feedback.bind({"reports": [report(reviews=[reviewed])]}, markers("stuck-a", "stuck-b"))
    assert result["schema"] == "rosy.recording.incident_feedback/1"
    assert result["missing_incidents"] == ["stuck-b"]
    assert result["matches"] == [{"incident_id": "line_stuck:rosy_40:stuck-a", "stuck_id": "stuck-a",
                                  "robot_id": "rosy_40", "core_cause": "lane_lost",
                                  "ai_cause_draft": "line_marking", "rosy_cam_linked": False,
                                  "front_image_status": "not_retained", "review_state": "review_candidate",
                                  "reviewed_root_cause": "line_marking", "review_count": 1}]
    assert "operator-robttt" not in str(result) and "private operator note" not in str(result)


def test_unreviewed_and_conflicting_reviews_never_become_a_label():
    one = {"at": "2026-10-10T01:00:00Z", "principal_id": "operator-robttt",
           "root_cause": "line_marking"}
    two = {"at": "2026-10-10T01:01:00Z", "principal_id": "operator-robttt",
           "root_cause": "obstacle"}
    result = incident_feedback.bind({"reports": [report("stuck-a"), report("stuck-b", [one, two])]},
                                    markers("stuck-a", "stuck-b"))
    assert [(x["review_state"], x["reviewed_root_cause"]) for x in result["matches"]] == [
        ("unreviewed", None), ("disputed", None)]


def test_ambiguous_or_invalid_report_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        incident_feedback.bind({"reports": [report(), report()]}, markers("stuck-a"))
    broken = report()
    broken["id"] = "line_stuck:rosy_41:stuck-a"
    with pytest.raises(ValueError, match="identity"):
        incident_feedback.bind({"reports": [broken]}, markers("stuck-a"))


def test_cli_accepts_windows_utf8_bom_exports(tmp_path, monkeypatch):
    incidents = tmp_path / "incidents.json"
    marks = tmp_path / "stuck_markers.json"
    output = tmp_path / "feedback.json"
    incidents.write_text(json.dumps({"reports": [report()]}), encoding="utf-8-sig")
    marks.write_text(json.dumps(markers("stuck-a")), encoding="utf-8-sig")
    monkeypatch.setattr(sys, "argv", ["incident_feedback.py", str(incidents), str(marks),
                                    "--out", str(output)])
    incident_feedback.main()
    assert json.loads(output.read_text(encoding="utf-8"))["matches"][0]["review_state"] == "unreviewed"
