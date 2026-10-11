import json
from contextlib import closing
from dataclasses import asdict, replace

import httpx
import pytest

from fleet.incidents.automation.contract import CaseBudget, CaseScope
from fleet.incidents.automation.store import IncidentCaseStore
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
    store.finish_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
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
    if fault != 'active': store.finish_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
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
    store.finish_case(scope, state='HOLD', reason='REOBSERVE_FAILED')
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
