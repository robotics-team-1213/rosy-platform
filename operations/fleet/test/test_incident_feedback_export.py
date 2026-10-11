import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from dataclasses import asdict, replace

import pytest

from rosy.decision.deliberation import canonical
from fleet.incidents.automation.store import CaseBudget, CaseScope, IncidentCaseStore
from test_judgment_profiles import profile

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / 'tools/incident_model_feedback.py'


def exporter():
    spec = importlib.util.spec_from_file_location('incident_model_feedback', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(tmp_path, primary_id='model-primary'):
    models = (profile(profile_id=primary_id), profile(profile_id='reviewer', role='reviewer'))
    manifest = [asdict(p) for p in models]
    digest = hashlib.sha256(canonical(manifest).encode()).hexdigest()
    scope = CaseScope('pinky', 'case', 'core', digest, 'policy-1')
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: 101)
    store.begin_case(scope, CaseBudget(100, 200, 2, 2, .3))
    store.reserve(scope, attempt_id='attempt', input_hash='b' * 64,
                  observation_revision='r1', kind='model', max_cost_usd=.1, worker_id='private-worker')
    store.mark_submitting(scope, 'attempt', worker_id='private-worker')
    return store, scope, manifest


def test_unknown_remains_in_feedback_with_reserved_cost_and_pinned_models(tmp_path):
    store, scope, manifest = fixture(tmp_path)
    store.complete(scope, 'attempt', worker_id='private-worker', state='UNKNOWN',
                   actual_cost_usd=None, summary={'reason': 'PROVIDER_OUTCOME_UNKNOWN'})
    result = exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)
    case = result['case']
    assert result['schema'] == 'rosy.incident.model_feedback/1'
    assert case['outcome'] == 'UNRESOLVED' and case['closure'] is None
    assert case['calls'] == 1 and case['spent_micros'] == 0 and case['reserved_micros'] == 100000
    assert case['attempts'][0]['actual_micros'] is None and case['attempts'][0]['state'] == 'UNKNOWN'
    assert case['profiles'] == json.loads(canonical(manifest))
    assert result['digest'] == hashlib.sha256(canonical(case).encode()).hexdigest()
    assert 'private-worker' not in canonical(result)
    assert result['label_state'] == 'UNREVIEWED' and result['field_accepted'] is False


def test_active_is_in_progress_and_export_is_readonly_and_stable(tmp_path):
    store, scope, manifest = fixture(tmp_path)
    before = store.path.read_bytes()
    one = exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)
    two = exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)
    assert one == two and one['case']['outcome'] == 'IN_PROGRESS'
    assert store.path.read_bytes() == before
    assert one['case']['attempts'][0]['state'] == 'SUBMITTING'


def test_foreign_case_and_changed_profile_manifest_are_rejected(tmp_path):
    store, scope, manifest = fixture(tmp_path)
    with pytest.raises(ValueError):
        exporter().snapshot(store.path, 'other', scope.case_id, manifest)
    changed = [asdict(replace(profile(), model_revision='changed')), manifest[1]]
    with pytest.raises(ValueError):
        exporter().snapshot(store.path, scope.subject_id, scope.case_id, changed)


@pytest.mark.parametrize('tamper', ['counter', 'summary', 'closure'])
def test_corrupt_counters_free_text_and_unbound_closure_are_rejected(tmp_path, tamper):
    store, scope, manifest = fixture(tmp_path)
    with sqlite3.connect(store.path) as conn:
        if tamper == 'counter':
            conn.execute('UPDATE fleet_incident_v2_cases SET spent_micros=1')
        elif tamper == 'summary':
            conn.execute('UPDATE fleet_incident_v2_attempts SET summary_json=?',
                         ('{"secret":"must-not-export"}',))
        else:
            conn.execute('CREATE TABLE IF NOT EXISTS fleet_incident_v2_closures '
                         '(subject_id TEXT,case_id TEXT,receipt_json TEXT)')
            conn.execute('INSERT INTO fleet_incident_v2_closures VALUES (?,?,?)',
                         ('pinky', 'case', '{"state":"RESOLVED_OBSERVED","scope":{"case_id":"other"}}'))
    with pytest.raises(ValueError):
        exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)


def test_cli_writes_once_and_never_creates_missing_input_database(tmp_path):
    store, scope, manifest = fixture(tmp_path)
    profiles, output = tmp_path / 'profiles.json', tmp_path / 'feedback.json'
    profiles.write_text(canonical(manifest), encoding='utf-8')
    args = [sys.executable, str(TOOL), str(store.path), '--subject', scope.subject_id,
            '--case', scope.case_id, '--profiles', str(profiles), '--out', str(output)]
    first = subprocess.run(args, capture_output=True, text=True)
    assert first.returncode == 0, first.stdout + first.stderr
    data = output.read_bytes()
    assert subprocess.run(args, capture_output=True).returncode != 0
    assert output.read_bytes() == data
    absent = tmp_path / 'absent.db'
    args[2], args[-1] = str(absent), str(tmp_path / 'other.json')
    assert subprocess.run(args, capture_output=True).returncode != 0
    assert not absent.exists()


@pytest.mark.parametrize('tamper', ['pending_cost', 'observation_cost', 'inflight_closure'])
def test_impossible_attempt_states_are_rejected_even_with_matching_totals(tmp_path, tamper):
    store, scope, manifest = fixture(tmp_path)
    with sqlite3.connect(store.path) as conn:
        if tamper == 'pending_cost':
            conn.execute('UPDATE fleet_incident_v2_attempts SET actual_micros=50000')
            conn.execute('UPDATE fleet_incident_v2_cases SET spent_micros=50000,reserved_micros=50000')
        elif tamper == 'observation_cost':
            conn.execute("UPDATE fleet_incident_v2_attempts SET kind='observation'")
            conn.execute('UPDATE fleet_incident_v2_cases SET calls=0,observations=1')
        else:
            conn.execute('CREATE TABLE IF NOT EXISTS fleet_incident_v2_closures '
                         '(subject_id TEXT,case_id TEXT,receipt_json TEXT)')
            proof = dict(scope=asdict(scope), requested_at=100, observed_at=102, closed_at=102,
                         normal_revision='r2', action_credit='NONE', state='RESOLVED_OBSERVED')
            conn.execute('INSERT INTO fleet_incident_v2_closures VALUES (?,?,?)', ('pinky', 'case', canonical(proof)))
            conn.execute("UPDATE fleet_incident_v2_cases SET state='HOLD',reason='RESOLVED_OBSERVED'")
    with pytest.raises(ValueError):
        exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)


@pytest.mark.parametrize('primary_id', ['model-primary', '로컬-primary'])
def test_real_export_links_to_recording_without_creating_model_truth(tmp_path, primary_id):
    store, scope, manifest = fixture(tmp_path, primary_id)
    store.complete(scope, 'attempt', worker_id='private-worker', state='UNKNOWN',
                   actual_cost_usd=None, summary={'reason': 'PROVIDER_OUTCOME_UNKNOWN'})
    exported = exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)
    spec = importlib.util.spec_from_file_location('learning_feedback', ROOT / 'learning/curation/perception/incident_feedback.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = dict(schema='rosy.incident.v1', id='line_stuck:pinky:case', classification='line_stuck',
                  robot_ids=['pinky'], stuck_id='case', evidence={}, reviews=[])
    markers = dict(schema='rosy.recording.stuck_markers/1', markers=[dict(stuck_id='case')])
    result = module.attach_model_feedback(module.bind({'reports': [report]}, markers), exported)
    row = result['matches'][0]
    assert row['model_feedback']['digest'] == exported['digest']
    assert row['model_feedback']['reserved_micros'] == 100000 and row['reviewed_root_cause'] is None


def test_zero_call_not_needed_is_exported_as_nonintervention(tmp_path):
    store, scope, manifest = fixture(tmp_path)
    with sqlite3.connect(store.path) as conn:
        conn.execute('DELETE FROM fleet_incident_v2_attempts')
        conn.execute('UPDATE fleet_incident_v2_cases SET calls=0,reserved_micros=0')
    store.close_case(scope, state='NOT_NEEDED', reason='NORMAL')
    result = exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)
    assert result['case']['outcome'] == 'DO_NOT_INTERVENE'
    assert result['case']['calls'] == 0 and result['case']['attempts'] == []


def traced_case(tmp_path, count=1):
    from test_incident_model_receipt import fixture as receipt_fixture
    from fleet.incidents.automation.ledger.receipt import model_receipt
    scope, p, models, bound, checked, _ = receipt_fixture()
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: 101)
    store.begin_case(scope, CaseBudget(100, 200, count, 0, .8))
    trace = model_receipt(scope, p, bound, checked, profiles=models)
    for index in range(count):
        aid = f'model-{index}-0123456789abcdef0123456789abcdef'
        store.reserve(scope, attempt_id=aid, input_hash=p.digest, observation_revision=p.generation,
                      kind='model', max_cost_usd=.1, worker_id='worker', role='primary')
        store.mark_submitting(scope, aid, worker_id='worker')
        store.complete(scope, aid, worker_id='worker', state='COMPLETED', actual_cost_usd=.05,
                       summary={'reason': 'MODEL_CHECKED'}, model_receipt=trace)
    return store, scope, [asdict(p) for p in models], trace


def test_model_trace_is_joined_with_its_actual_cost_and_remains_unreviewed(tmp_path):
    store, scope, manifest, trace = traced_case(tmp_path)
    result = exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)
    attempt = result['case']['attempts'][0]
    assert attempt['model_receipt'] == json.loads(trace.payload_json)
    assert attempt['actual_micros'] == result['case']['spent_micros'] == 50000
    assert result['label_state'] == 'UNREVIEWED' and result['field_accepted'] is False
    assert 'worker' not in canonical(attempt)


@pytest.mark.parametrize('fault', ['foreign_input', 'raw_response', 'orphan'])
def test_corrupted_or_orphan_model_trace_cannot_be_exported(tmp_path, fault):
    store, scope, manifest, trace = traced_case(tmp_path)
    with sqlite3.connect(store.path) as conn:
        if fault == 'foreign_input':
            conn.execute("UPDATE fleet_incident_v2_attempts SET input_hash=?", ('b' * 64,))
        elif fault == 'raw_response':
            conn.execute("UPDATE fleet_incident_v2_model_receipts SET receipt_json=?",
                         ('{"raw_response":"private"}',))
        else:
            conn.execute("INSERT INTO fleet_incident_v2_model_receipts VALUES (?,?,?,?)",
                         (scope.subject_id, scope.case_id, 'missing', trace.payload_json))
    with pytest.raises(ValueError):
        exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)


def test_old_database_without_model_receipt_table_has_explicitly_missing_trace(tmp_path):
    store, scope, manifest = fixture(tmp_path)
    with sqlite3.connect(store.path) as conn:
        conn.execute('DROP TABLE fleet_incident_v2_model_receipts')
    result = exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)
    assert result['case']['attempts'][0]['model_receipt'] is None


def test_multiple_model_traces_can_exceed_one_invocation_budget_without_losing_evidence(tmp_path):
    store, scope, manifest, _ = traced_case(tmp_path, count=8)
    result = exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)
    encoded = json.dumps(result['case'], sort_keys=True, separators=(',', ':'), allow_nan=False)
    assert len(encoded.encode()) > 16384
    assert len(encoded.encode()) <= 1024 * 1024
    assert result['digest'] == hashlib.sha256(encoded.encode()).hexdigest()
    assert all(a['model_receipt'] is not None for a in result['case']['attempts'])
