import json
import sqlite3
from dataclasses import asdict

import pytest

from test_incident_feedback_export import exporter, fixture


def source_tables(store, scope, *, claim=True, sent=True):
    from types import SimpleNamespace
    from fleet.incidents.handoff import IncidentHandoff
    from fleet.incidents.notifications import NotificationOutbox
    def connect():
        conn = sqlite3.connect(store.path); conn.row_factory = sqlite3.Row
        return conn
    log = SimpleNamespace(_connect=connect)
    IncidentHandoff(log); NotificationOutbox(log)
    facts = dict(scope_json=json.dumps(asdict(scope), sort_keys=True, separators=(',', ':')),
        profile_sha256=scope.profile_sha256, calls=1, observations=0, spent_micros=0,
        reserved_micros=100000, observation_revision='r1', reason='PROVIDER_OUTCOME_UNKNOWN',
        robot_id=scope.subject_id, stuck_id=scope.case_id, kind='FINAL_REVIEW',
        observed_at=101, owner='PRIVATE_OWNER', console_link='https://PRIVATE_ENDPOINT')
    with connect() as conn:
        if claim: conn.execute('INSERT INTO fleet_incident_claims VALUES (?,?,?,?,?)',
                              (scope.subject_id, scope.case_id, 'PRIVATE_PRINCIPAL', 'c' * 64, 102))
        if sent: conn.execute('''INSERT INTO fleet_notification_outbox
            (robot_id,stuck_id,judgment_revision,kind,channel,route_hash,payload,
             created_at,expires_at,next_attempt_at,state,attempts,delivered_at,provider_id)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (scope.subject_id,scope.case_id,__import__('hashlib').sha256(facts['scope_json'].encode()).hexdigest(),
             'FINAL_REVIEW','discord','PRIVATE_ROUTE',json.dumps(facts),101,701,101,'SENT',1,102,'PRIVATE_PROVIDER'))
        if sent: conn.execute("UPDATE fleet_notification_outbox SET last_code='PROVIDER_ACCEPTED',last_attempt_at=101")


def prepared(tmp_path):
    store, scope, profiles = fixture(tmp_path)
    store.complete(scope, 'attempt', worker_id='private-worker', state='UNKNOWN',
                   actual_cost_usd=None, summary={'reason': 'PROVIDER_OUTCOME_UNKNOWN'})
    return store, scope, profiles


def test_opt_in_same_snapshot_distinguishes_missing_tables_empty_records_and_queue(tmp_path):
    store, scope, profiles = prepared(tmp_path)
    tool = exporter()
    assert tool.snapshot(store.path, scope.subject_id, scope.case_id, profiles)['schema'].endswith('/1')
    result = tool.snapshot(store.path, scope.subject_id, scope.case_id, profiles, include_handoff=True)
    assert result['schema'].endswith('/2')
    proof = result['case']['handoff']
    assert proof['tables'] == {'claims': 'ABSENT', 'outbox': 'ABSENT', 'queues': 'PRESENT'}
    assert proof['claim'] is None and proof['queue'] is None and proof['notifications'] == []
    source_tables(store, scope, claim=False, sent=False)
    store.handoff_queued(scope)
    proof = tool.snapshot(store.path, scope.subject_id, scope.case_id, profiles, include_handoff=True)['case']['handoff']
    assert proof['tables']['claims'] == proof['tables']['outbox'] == 'PRESENT'
    assert proof['queue']['queued_at'] == 101 and proof['claim'] is None


def test_provider_accepted_and_named_claim_remain_distinct_and_private_text_never_escapes(tmp_path):
    store, scope, profiles = prepared(tmp_path)
    source_tables(store, scope)
    result = exporter().snapshot(store.path, scope.subject_id, scope.case_id, profiles, include_handoff=True)
    proof = result['case']['handoff']
    assert proof['claim']['binding'] == 'CASE_ONLY'
    assert proof['notifications'][0]['state'] == 'SENT'
    assert proof['queue'] is None
    assert proof['assertions'] == {'verified_human_identity': False, 'independent_quality': False}
    assert 'PRIVATE_' not in json.dumps(result)


@pytest.mark.parametrize('fault', ['scope', 'counter', 'revision', 'time'])
def test_corrupt_final_source_facts_are_rejected_not_counted(tmp_path, fault):
    store, scope, profiles = prepared(tmp_path); source_tables(store, scope)
    with sqlite3.connect(store.path) as conn:
        raw = json.loads(conn.execute('SELECT payload FROM fleet_notification_outbox').fetchone()[0])
        if fault == 'scope': raw['scope_json'] = '{}'
        if fault == 'counter': raw['spent_micros'] = 1
        if fault == 'revision': raw['observation_revision'] = 'foreign-revision'
        if fault == 'time': raw['observed_at'] = 99
        conn.execute('UPDATE fleet_notification_outbox SET payload=?', (json.dumps(raw),))
    with pytest.raises(ValueError):
        exporter().snapshot(store.path, scope.subject_id, scope.case_id, profiles, include_handoff=True)


def test_actual_final_queue_provider_acceptance_and_claim_producers_bind_to_export(tmp_path):
    import hashlib
    import httpx
    from fleet.incidents.automation.store import CaseBudget, CaseScope, IncidentCaseStore
    from test_judgment_profiles import profile
    from test_notifications import _setup, observe, run
    now, log, board, channels = _setup(tmp_path)
    observe(board, 100)
    models = (profile(profile_id='primary'), profile(profile_id='reviewer', role='reviewer'))
    profiles = [asdict(p) for p in models]
    profile_hash = hashlib.sha256(json.dumps(profiles, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    scope = CaseScope('pinky', 'case-1', 'core', profile_hash, board.judgment_view('pinky')['policy_revision'])
    store = IncidentCaseStore(log.path, clock=lambda: now[0])
    revision = board.judgment_view('pinky')['request']['revision']
    store.begin_case(scope, CaseBudget(100, 130, 0, 0, 0), initial_revision=revision)
    store.close_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
    assert log.notifications.enqueue_final(scope, store.final_summary(scope), now=101)
    store.handoff_queued(scope)
    run(log, board, channels, 101, lambda request: httpx.Response(200, json={'id': '7'}))
    log.handoff.claim(scope.subject_id, scope.case_id, board.judgment_view('pinky'), 'private-principal', now=102)
    proof = exporter().snapshot(log.path, scope.subject_id, scope.case_id, profiles, include_handoff=True)['case']['handoff']
    assert proof['queue']['queued_at'] == 100
    assert proof['notifications'][0]['state'] == 'SENT' and proof['claim']['claimed_at'] == 102
    assert 'private-' not in json.dumps(proof)


def test_cli_handoff_switch_produces_new_schema_without_overwriting(tmp_path):
    import subprocess
    import sys
    from test_incident_feedback_export import TOOL
    store, scope, profiles = prepared(tmp_path)
    path = tmp_path / 'profiles.json'; path.write_text(json.dumps(profiles))
    output = tmp_path / 'handoff.json'
    args = [sys.executable, str(TOOL), str(store.path), '--subject', scope.subject_id,
            '--case', scope.case_id, '--profiles', str(path), '--out', str(output), '--include-handoff']
    assert subprocess.run(args, capture_output=True).returncode == 0
    assert json.loads(output.read_text())['schema'] == 'rosy.incident.model_feedback/2'
    before = output.read_bytes()
    assert subprocess.run(args, capture_output=True).returncode == 1 and output.read_bytes() == before


@pytest.mark.parametrize('field,value', [('last_code', 'PROVIDER_REFUSED'), ('last_attempt_at', None), ('last_attempt_at', 103)])
def test_sent_state_alone_cannot_fabricate_provider_acceptance(tmp_path, field, value):
    store, scope, profiles = prepared(tmp_path); source_tables(store, scope)
    with sqlite3.connect(store.path) as conn:
        conn.execute(f'UPDATE fleet_notification_outbox SET {field}=?', (value,))
    with pytest.raises(ValueError):
        exporter().snapshot(store.path, scope.subject_id, scope.case_id, profiles, include_handoff=True)
