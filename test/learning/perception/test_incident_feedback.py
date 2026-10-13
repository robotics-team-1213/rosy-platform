"""Fleet incident reviews are candidates for a recording, never pixel labels."""

import json
import hashlib
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


def model_feedback(**changes):
    case = dict(scope=dict(subject_id='rosy_40', case_id='stuck-a', owner_id='core',
                           profile_sha256='a' * 64, policy_revision='policy-1'),
                state='HOLD', outcome='UNRESOLVED', reason='PROVIDER_OUTCOME_UNKNOWN',
                calls=1, observations=0, spent_micros=0, reserved_micros=100000)
    case.update(changes)
    digest = hashlib.sha256(json.dumps(case, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return dict(schema='rosy.incident.model_feedback/1', case=case, digest=digest,
                label_state='UNREVIEWED', field_accepted=False)


def test_model_failure_links_to_exact_recording_without_becoming_truth():
    base = incident_feedback.bind({'reports': [report()]}, markers('stuck-a'))
    before = json.dumps(base, sort_keys=True)
    linked = incident_feedback.attach_model_feedback(base, model_feedback())
    row = linked['matches'][0]
    assert linked['schema'] == 'rosy.recording.incident_feedback/2'
    assert (row['review_state'], row['reviewed_root_cause']) == ('unreviewed', None)
    assert row['model_feedback']['reserved_micros'] == 100000
    assert row['model_feedback']['label_state'] == 'UNREVIEWED'
    assert json.dumps(base, sort_keys=True) == before


def handoff_feedback():
    data = model_feedback()
    case = data['case']
    case['budget'] = {'started_at': 100}
    case['handoff'] = dict(schema='rosy.incident.handoff_evidence/1',
        scope_sha256=hashlib.sha256(json.dumps(case['scope'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        tables=dict(claims='PRESENT', outbox='ABSENT', queues='PRESENT'),
        queue={'queued_at': 101}, notifications=[], claim=dict(claimed_at=102, judgment_revision='b' * 64,
            record_sha256='c' * 64, binding='CASE_ONLY'),
        assertions=dict(verified_human_identity=False, independent_quality=False))
    data['schema'] = 'rosy.incident.model_feedback/2'
    data['digest'] = hashlib.sha256(json.dumps(case, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return data


def test_opt_in_handoff_evidence_survives_recording_binding_without_quality_claims():
    base = incident_feedback.bind({'reports': [report()]}, markers('stuck-a'))
    exported = handoff_feedback()
    result = incident_feedback.attach_model_feedback(base, exported)
    assert result['matches'][0]['model_feedback']['handoff'] == exported['case']['handoff']
    assert result['matches'][0]['model_feedback']['label_state'] == 'UNREVIEWED'


@pytest.mark.parametrize('fault', ['identity', 'scope', 'private_extra'])
def test_handoff_proof_tamper_is_rejected_even_with_recomputed_export_digest(fault):
    base = incident_feedback.bind({'reports': [report()]}, markers('stuck-a'))
    data = handoff_feedback(); proof = data['case']['handoff']
    if fault == 'identity': proof['assertions']['verified_human_identity'] = True
    if fault == 'scope': proof['scope_sha256'] = 'e' * 64
    if fault == 'private_extra': proof['claim']['principal_id'] = 'PRIVATE_OPERATOR'
    data['digest'] = hashlib.sha256(json.dumps(data['case'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with pytest.raises(ValueError): incident_feedback.attach_model_feedback(base, data)


@pytest.mark.parametrize('tamper', ['foreign_subject', 'hash', 'label', 'counter'])
def test_invalid_or_self_labeled_model_feedback_cannot_enter_recording(tamper):
    base = incident_feedback.bind({'reports': [report()]}, markers('stuck-a'))
    data = model_feedback()
    if tamper == 'foreign_subject':
        data['case']['scope']['subject_id'] = 'rosy_41'
    elif tamper == 'hash':
        data['digest'] = 'b' * 64
    elif tamper == 'label':
        data['field_accepted'] = True
    else:
        data = model_feedback(calls=True)
    with pytest.raises(ValueError):
        incident_feedback.attach_model_feedback(base, data)


def test_cli_attaches_bounded_model_evidence_and_preserves_review_state(tmp_path, monkeypatch):
    incidents, marks, feedback, output = (tmp_path / name for name in ('incidents.json', 'markers.json', 'model.json', 'out.json'))
    incidents.write_text(json.dumps({'reports': [report()]}), encoding='utf-8')
    marks.write_text(json.dumps(markers('stuck-a')), encoding='utf-8')
    feedback.write_text(json.dumps(model_feedback()), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['incident_feedback.py', str(incidents), str(marks),
                                    '--model-feedback', str(feedback), '--out', str(output)])
    incident_feedback.main()
    linked = json.loads(output.read_text(encoding='utf-8'))
    assert linked['schema'] == 'rosy.recording.incident_feedback/2'
    assert linked['matches'][0]['model_feedback']['label_state'] == 'UNREVIEWED'
    assert linked['matches'][0]['reviewed_root_cause'] is None
