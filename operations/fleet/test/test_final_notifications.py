import asyncio
import json
from contextlib import closing
from dataclasses import replace

import httpx
import pytest

from fleet.incidents.automation.contract import CaseBudget, CaseScope
from fleet.incidents.automation.store import IncidentCaseStore
from fleet.incidents.notifications import NotificationWorker
from test_notifications import _setup, observe, run


def managed(tmp_path, *, config=True):
    now, log, board, channels = _setup(tmp_path)
    if not config: log.notifications.config = None
    store = IncidentCaseStore(log.path, clock=lambda: now[0])
    scope = CaseScope('pinky', 'case-1', 'core', 'a' * 64, 'line-follow-shadow-v1')
    store.begin_case(scope, CaseBudget(100, 130, 2, 2, 0))
    observe(board, 100)
    revision = board.judgment_view('pinky')['request']['revision']
    summary = dict(reason='REOBSERVE_FAILED', calls=0, observations=0, spent_micros=0,
                   reserved_micros=0, profile_sha256=scope.profile_sha256, observation_revision=revision)
    return now, log, board, channels, store, scope, summary


def test_opt_in_prepare_uses_judgment_transaction_and_suppresses_initial_open(tmp_path):
    _, log, board, _ = _setup(tmp_path)
    seen = []
    def prepare(connection, receipt):
        seen.append(receipt['request']['case_id'])
        connection.execute('CREATE TABLE prepared_marker(value TEXT)')
        connection.execute('INSERT INTO prepared_marker VALUES (?)', ('same-transaction',))
        return True
    log.notifications.set_automation(prepare)
    observe(board, 100)
    assert seen == ['case-1'] and log.notifications.rows() == []
    with closing(log._connect()) as connection:
        assert connection.execute('SELECT value FROM prepared_marker').fetchone()[0] == 'same-transaction'


def test_managed_hold_suppresses_historical_open_and_final_is_once_without_claim(tmp_path):
    now, log, board, channels = _setup(tmp_path)
    observe(board, 100)
    store = IncidentCaseStore(log.path, clock=lambda: now[0])
    scope = CaseScope('pinky', 'case-1', 'core', 'a' * 64, 'line-follow-shadow-v1')
    store.begin_case(scope, CaseBudget(100, 130, 2, 2, 0))
    store.close_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
    summary = dict(reason='REOBSERVE_FAILED', calls=0, observations=0, spent_micros=0,
                   reserved_micros=0, profile_sha256=scope.profile_sha256,
                   observation_revision=board.judgment_view('pinky')['request']['revision'])
    for _ in range(2): log.notifications.enqueue_final(scope, summary, now=100)
    assert [row['kind'] for row in log.notifications.rows()].count('FINAL_REVIEW') == 1
    sent = []
    run(log, board, channels, 100, lambda request: sent.append(json.loads(request.content)) or httpx.Response(200, json={'id': '7'}))
    assert len(sent) == 1 and 'FINAL_REVIEW' in sent[0]['content']
    assert log.handoff.active() == []
    assert next(row for row in log.notifications.rows() if row['kind'] == 'OPEN')['state'] == 'SUPERSEDED'


@pytest.mark.parametrize('fault', ['active', 'scope', 'counter', 'reason', 'revision', 'config'])
def test_final_enqueue_validates_hold_scope_summary_and_configuration(tmp_path, fault):
    _, log, _, _, store, scope, summary = managed(tmp_path, config=fault != 'config')
    if fault != 'active': store.close_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
    if fault == 'scope': scope = replace(scope, profile_sha256='b' * 64)
    elif fault == 'counter': summary['reserved_micros'] = 1
    elif fault == 'reason': summary['reason'] = 'OTHER'
    elif fault == 'revision': summary['observation_revision'] = 'foreign'
    if fault == 'config': assert log.notifications.enqueue_final(scope, summary, now=100) is False
    else:
        with pytest.raises(ValueError): log.notifications.enqueue_final(scope, summary, now=100)
    assert all(row['kind'] != 'FINAL_REVIEW' for row in log.notifications.rows())


@pytest.mark.parametrize('change', ['replaced', 'closed', 'claimed', 'expired', 'fresh_revision', 'parent_changed'])
def test_final_pending_rechecks_case_owner_freshness_and_parent(tmp_path, change):
    now, log, board, channels, store, scope, summary = managed(tmp_path)
    store.close_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
    log.notifications.enqueue_final(scope, summary, now=100)
    if change == 'replaced': observe(board, 100, 'case-2')
    elif change == 'closed': observe(board, 100, None)
    elif change == 'claimed': log.handoff.claim('pinky', 'case-1', board.judgment_view('pinky'), 'alice', now=100)
    elif change == 'expired': now[0] = 701
    elif change == 'fresh_revision': now[0] = 101; observe(board, 101)
    else:
        with closing(log._connect()) as connection, connection:
            connection.execute("UPDATE fleet_incident_v2_cases SET state='NOT_NEEDED'")
    sent = []
    run(log, board, channels, now[0], lambda request: sent.append(json.loads(request.content)) or httpx.Response(200, json={'id': '7'}))
    assert bool([body for body in sent if 'FINAL_REVIEW' in body['content']]) == (change == 'fresh_revision')


def test_unknown_cost_preserves_reservation_and_reports_unknown(tmp_path):
    now, log, board, channels = _setup(tmp_path)
    store = IncidentCaseStore(log.path, clock=lambda: now[0])
    scope = CaseScope('pinky', 'case-1', 'core', 'a' * 64, 'line-follow-shadow-v1')
    store.begin_case(scope, CaseBudget(100, 130, 2, 2, 1))
    observe(board, 100)
    revision = board.judgment_view('pinky')['request']['revision']
    store.reserve(scope, attempt_id='call-1', input_hash='b' * 64, observation_revision=revision,
                  kind='model', max_cost_usd=.25, worker_id='worker-1')
    store.mark_submitting(scope, 'call-1', worker_id='worker-1')
    store.complete(scope, 'call-1', worker_id='worker-1', state='UNKNOWN', actual_cost_usd=None,
                   summary={'reason': 'PROVIDER_OUTCOME_UNKNOWN'})
    summary = dict(reason='PROVIDER_OUTCOME_UNKNOWN', calls=1, observations=0, spent_micros=0,
                   reserved_micros=250000, profile_sha256=scope.profile_sha256, observation_revision=revision)
    log.notifications.enqueue_final(scope, summary, now=100)
    sent = []
    run(log, board, channels, 100, lambda request: sent.append(json.loads(request.content)) or httpx.Response(200, json={'id': '7'}))
    assert len(sent) == 1 and 'UNKNOWN' in sent[0]['content'] and '250000' in sent[0]['content']
    assert store.case(scope)['reserved_micros'] == 250000


@pytest.mark.parametrize('change', ['parent', 'human'])
def test_final_checks_again_after_dequeue_before_http(tmp_path, change):
    _, log, board, channels, store, scope, summary = managed(tmp_path)
    store.close_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
    log.notifications.enqueue_final(scope, summary, now=100)
    original = log.notifications.claim_due
    def claim(now, config):
        result = original(now, config)
        if result:
            if change == 'parent':
                with closing(log._connect()) as connection, connection:
                    connection.execute("UPDATE fleet_incident_v2_cases SET state='NOT_NEEDED'")
            else:
                log.handoff.claim('pinky', 'case-1', board.judgment_view('pinky'), 'alice', now=100)
        return result
    log.notifications.claim_due = claim
    run(log, board, channels, 100, lambda _: pytest.fail('stale final review reached HTTP'))
    assert next(row for row in log.notifications.rows() if row['kind'] == 'FINAL_REVIEW')['state'] == 'SUPERSEDED'


def test_prepare_still_runs_without_channel_and_failure_rolls_back(tmp_path):
    _, log, board, _ = _setup(tmp_path)
    log.notifications.config = None
    def prepare(connection, receipt):
        connection.execute('CREATE TABLE attempted_prepare(value TEXT)')
        raise ValueError('PREPARATION_FAILED')
    log.notifications.set_automation(prepare)
    board.observe([__import__('test_judgment_receipts').row(stuck_id='case-1')])
    with pytest.raises(ValueError, match='PREPARATION_FAILED'):
        log.record_judgment(board.judgment_view('pinky'))
    with closing(log._connect()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM fleet_judgment_current').fetchone()[0] == 0
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='attempted_prepare'").fetchone()


def test_final_enqueue_accepts_original_durable_revision_after_next_poll(tmp_path):
    now, log, board, _, store, scope, summary = managed(tmp_path)
    store.close_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
    original = summary['observation_revision']
    now[0] = 101
    observe(board, 101)
    assert original != board.judgment_view('pinky')['request']['revision']
    assert log.notifications.enqueue_final(scope, summary, now=101)
    with closing(log._connect()) as connection:
        payload = json.loads(connection.execute("SELECT payload FROM fleet_notification_outbox WHERE kind='FINAL_REVIEW'").fetchone()[0])
    assert payload['observation_revision'] == original


def test_final_waits_through_stale_poll_and_delivers_after_fresh_same_case(tmp_path):
    now, log, board, channels, store, scope, summary = managed(tmp_path)
    store.close_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
    log.notifications.enqueue_final(scope, summary, now=100)
    now[0] = 104
    run(log, board, channels, 104, lambda _: pytest.fail('stale final reached HTTP'))
    assert next(row for row in log.notifications.rows() if row['kind'] == 'FINAL_REVIEW')['state'] == 'PENDING'
    now[0] = 105
    observe(board, 105)
    sent = []
    run(log, board, channels, 105, lambda request: sent.append(request) or httpx.Response(200, json={'id': '7'}))
    assert len(sent) == 1


def test_stale_after_dequeue_defers_without_consuming_http_attempt(tmp_path):
    now, log, board, channels, store, scope, summary = managed(tmp_path)
    store.close_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
    log.notifications.enqueue_final(scope, summary, now=100)
    original = log.notifications.claim_due
    def claim(at, config):
        result = original(at, config)
        now[0] = 104
        return result
    log.notifications.claim_due = claim
    async def deliver():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail('stale final reached HTTP'))) as http:
            await NotificationWorker(log.notifications, channels, http, board=board, clock=lambda: now[0]).run_once()
    asyncio.run(deliver())
    final = next(row for row in log.notifications.rows() if row['kind'] == 'FINAL_REVIEW')
    assert final['state'] == 'PENDING' and final['attempts'] == 0


@pytest.mark.parametrize('original_case', ['case-1', 'foreign'])
def test_zero_attempt_origin_binds_revision_after_audit_rotation(tmp_path, original_case):
    now, log, board, _, store, scope, summary = managed(tmp_path)
    store.close_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
    now[0] = 101
    observe(board, 101)
    if original_case != scope.case_id:
        store.begin_case(replace(scope, case_id=original_case), CaseBudget(100, 130, 2, 2, 0))
    with closing(log._connect()) as connection, connection:
        connection.execute('DELETE FROM fleet_judgment_records')
        connection.execute('CREATE TABLE IF NOT EXISTS fleet_incident_v2_origins '
                           '(subject_id TEXT, case_id TEXT, observation_revision TEXT, PRIMARY KEY(subject_id,case_id))')
        connection.execute('INSERT INTO fleet_incident_v2_origins VALUES (?,?,?)',
                           (scope.subject_id, original_case, summary['observation_revision']))
    if original_case == scope.case_id:
        assert log.notifications.enqueue_final(scope, summary, now=101)
    else:
        with pytest.raises(ValueError): log.notifications.enqueue_final(scope, summary, now=101)


@pytest.mark.parametrize('reason,current_policy', [('POLICY_CHANGED', 'line-follow-shadow-v1'),
                                                  ('OTHER_FAILURE', 'line-follow-shadow-v1'),
                                                  ('POLICY_CHANGED', 'foreign-policy')])
def test_changed_policy_final_is_diagnostic_only_and_requires_current_trusted_policy(tmp_path, reason, current_policy):
    _, log, board, channels = _setup(tmp_path)
    store = IncidentCaseStore(log.path, clock=lambda: 100)
    scope = CaseScope('pinky', 'case-1', 'core', 'a' * 64, 'old-policy')
    store.begin_case(scope, CaseBudget(100, 130, 2, 2, 0))
    observe(board, 100)
    revision = board.judgment_view('pinky')['request']['revision']
    store.close_case(scope, state='HOLD', reason=reason)
    with closing(log._connect()) as connection, connection:
        connection.execute('CREATE TABLE IF NOT EXISTS fleet_incident_v2_origins '
                           '(subject_id TEXT,case_id TEXT,observation_revision TEXT,PRIMARY KEY(subject_id,case_id))')
        connection.execute('INSERT INTO fleet_incident_v2_origins VALUES (?,?,?)', (scope.subject_id, scope.case_id, revision))
        receipt = json.loads(connection.execute('SELECT assessment FROM fleet_judgment_current').fetchone()[0])
        receipt['policy_revision'] = current_policy
        connection.execute('UPDATE fleet_judgment_current SET assessment=?', (json.dumps(receipt),))
    summary = dict(reason=reason, calls=0, observations=0, spent_micros=0, reserved_micros=0,
                   profile_sha256=scope.profile_sha256, observation_revision=revision)
    if reason == 'POLICY_CHANGED' and current_policy == 'line-follow-shadow-v1':
        assert log.notifications.enqueue_final(scope, summary, now=100)
        sent = []
        run(log, board, channels, 100, lambda request: sent.append(json.loads(request.content)) or httpx.Response(200, json={'id': '7'}))
        assert len(sent) == 1 and 'old-policy' in sent[0]['content'] and current_policy in sent[0]['content']
        assert log.handoff.active() == []
    else:
        with pytest.raises(ValueError): log.notifications.enqueue_final(scope, summary, now=100)
