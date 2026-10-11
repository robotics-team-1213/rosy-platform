from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading

import pytest

from fleet.incidents.automation.store import CaseBudget, CaseScope, IncidentCaseStore


def scope():
    return CaseScope('pinky', 'case', 'fleet', 'a' * 64, 'policy-1')


def budget(**changes):
    return CaseBudget(**{**dict(started_at=100, deadline=200, max_calls=2, max_observations=2,
                               max_cost_usd=.3), **changes})


def store(tmp_path, now=101):
    return IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: now)


def test_role_caps_survive_restart_but_allow_primary_and_reviewer_once(tmp_path):
    s = store(tmp_path)
    s.begin_case(scope(), budget(max_calls=2, role_limits=(('primary', 1), ('reviewer', 1))))
    s.reserve(scope(), attempt_id='primary-1', input_hash='b' * 64, observation_revision='r1',
              kind='model', max_cost_usd=.1, worker_id='w1', role='primary')
    finish(s, 'primary-1')
    s = store(tmp_path)
    with pytest.raises(ValueError, match='CASE_ROLE_BUDGET_EXHAUSTED'):
        s.reserve(scope(), attempt_id='primary-2', input_hash='c' * 64, observation_revision='r2',
                  kind='model', max_cost_usd=.1, worker_id='w2', role='primary')
    s.reserve(scope(), attempt_id='reviewer-1', input_hash='b' * 64, observation_revision='r1',
              kind='model', max_cost_usd=.1, worker_id='w1', role='reviewer')
    assert s.case(scope())['calls'] == 2


def test_atomic_role_reservation_prevents_concurrent_primary_overspend(tmp_path):
    s = store(tmp_path)
    s.begin_case(scope(), budget(role_limits=(('primary', 1), ('reviewer', 1))))
    def attempt(worker):
        try:
            s.reserve(scope(), attempt_id=worker, input_hash='b' * 64, observation_revision='r1',
                      kind='model', max_cost_usd=.1, worker_id=worker, role='primary')
            return 'reserved'
        except ValueError as error: return str(error)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, ('w1', 'w2')))
    assert sorted(results) == ['CASE_ROLE_BUDGET_EXHAUSTED', 'reserved']
    assert s.case(scope())['calls'] == 1


def reserve(s, attempt='a1', kind='model', cost=.1, worker='w1', revision='r1'):
    return s.reserve(scope(), attempt_id=attempt, input_hash='b' * 64, observation_revision=revision,
                     kind=kind, max_cost_usd=cost, worker_id=worker)


def finish(s, attempt='a1', cost=.1):
    s.mark_submitting(scope(), attempt, worker_id='w1')
    return s.complete(scope(), attempt, worker_id='w1', state='COMPLETED',
                      actual_cost_usd=cost, summary={'reason': 'RESPONSE_CHECKED'})


def test_restart_and_new_observation_do_not_reset_aggregate_budget(tmp_path):
    s = store(tmp_path)
    s.begin_case(scope(), budget())
    reserve(s)
    finish(s)
    reopened = store(tmp_path)
    reopened.begin_case(scope(), budget())
    reserve(reopened, 'a2', revision='r2')
    finish(reopened, 'a2')
    with pytest.raises(ValueError, match='BUDGET'):
        reserve(reopened, 'a3', cost=0, revision='r3')
    reserve(reopened, 'read1', kind='observation', cost=0, revision='r4')
    finish(reopened, 'read1', cost=0)
    row = reopened.case(scope())
    assert (row['calls'], row['observations'], row['spent_micros'], row['reserved_micros']) == (2, 1, 200000, 0)


@pytest.mark.parametrize('change', [dict(owner_id='human'), dict(profile_sha256='c' * 64),
                                  dict(policy_revision='policy-2')])
def test_existing_case_scope_or_budget_cannot_be_replaced(tmp_path, change):
    s = store(tmp_path)
    s.begin_case(scope(), budget())
    with pytest.raises(ValueError):
        s.begin_case(replace(scope(), **change), budget())
    with pytest.raises(ValueError):
        s.begin_case(scope(), budget(deadline=210))
    with pytest.raises(ValueError):
        s.reserve(replace(scope(), **change), attempt_id='changed', input_hash='b' * 64,
                  observation_revision='r2', kind='model', max_cost_usd=0, worker_id='w1')


def test_atomic_reservation_and_submission_prevent_concurrent_overspend(tmp_path):
    s = store(tmp_path)
    s.begin_case(scope(), budget(max_cost_usd=.1))
    barrier = threading.Barrier(2)
    def compete(index):
        contender = store(tmp_path)
        barrier.wait()
        try:
            reserve(contender, f'a{index}')
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(2) as workers:
        assert sum(workers.map(compete, (1, 2))) == 1
    row = s.case(scope())
    assert row['calls'] == 1 and row['reserved_micros'] == 100000


def test_attempt_cannot_replay_or_cross_worker_submission(tmp_path):
    s = store(tmp_path)
    s.begin_case(scope(), budget())
    reserve(s)
    with pytest.raises(ValueError): reserve(s)
    with pytest.raises(ValueError): s.mark_submitting(scope(), 'a1', worker_id='other')
    s.mark_submitting(scope(), 'a1', worker_id='w1')
    with pytest.raises(ValueError): s.mark_submitting(scope(), 'a1', worker_id='w1')
    s.complete(scope(), 'a1', worker_id='w1', state='COMPLETED', actual_cost_usd=.01,
               summary={'reason': 'RESPONSE_CHECKED'})
    with pytest.raises(ValueError):
        s.complete(scope(), 'a1', worker_id='w1', state='COMPLETED', actual_cost_usd=.01, summary={})
    with pytest.raises(ValueError): reserve(s)


@pytest.mark.parametrize('submitted', [False, True])
def test_recovery_preserves_unknown_reservation_and_stops_case(tmp_path, submitted):
    s = store(tmp_path)
    s.begin_case(scope(), budget())
    reserve(s)
    if submitted: s.mark_submitting(scope(), 'a1', worker_id='w1')
    reopened = store(tmp_path)
    assert reopened.recover(scope()) == 1
    assert reopened.attempt(scope(), 'a1')['state'] == 'UNKNOWN'
    assert reopened.case(scope())['reserved_micros'] == 100000
    assert reopened.case(scope())['state'] == 'HOLD'
    with pytest.raises(ValueError): reserve(reopened, 'a2', cost=0)
    with pytest.raises(ValueError): reopened.mark_submitting(scope(), 'a1', worker_id='w1')


@pytest.mark.parametrize('cost,expected', [(None, 'UNKNOWN'), (.2, 'COMPLETED')])
def test_unknown_cost_or_overrun_is_recorded_and_holds_case(tmp_path, cost, expected):
    s = store(tmp_path)
    s.begin_case(scope(), budget())
    reserve(s)
    s.mark_submitting(scope(), 'a1', worker_id='w1')
    result = s.complete(scope(), 'a1', worker_id='w1', state='COMPLETED', actual_cost_usd=cost, summary={})
    assert result['state'] == expected
    assert s.case(scope())['state'] == 'HOLD'
    if cost is not None: assert s.case(scope())['spent_micros'] == 200000


@pytest.mark.parametrize('cost,spent,reserved', [(.1, 100000, 0), (.05, 50000, 50000), (.2, 200000, 0)])
def test_unknown_outcome_keeps_known_billing_and_conservative_unused_reservation(tmp_path, cost, spent, reserved):
    s = store(tmp_path)
    s.begin_case(scope(), budget())
    reserve(s)
    s.mark_submitting(scope(), 'a1', worker_id='w1')
    result = s.complete(scope(), 'a1', worker_id='w1', state='UNKNOWN',
                        actual_cost_usd=cost, summary={'reason': 'OUTCOME_UNKNOWN'})
    row = s.case(scope())
    assert result['state'] == 'UNKNOWN' and result['actual_micros'] == spent
    assert (row['spent_micros'], row['reserved_micros'], row['state']) == (spent, reserved, 'HOLD')
    assert s.attempt(scope(), 'a1')['actual_micros'] == spent
    with pytest.raises(ValueError): reserve(s, 'a2', cost=0)


def test_deadline_blocks_new_effect_but_accepts_late_receipt(tmp_path):
    s = store(tmp_path)
    s.begin_case(scope(), budget())
    reserve(s)
    s.mark_submitting(scope(), 'a1', worker_id='w1')
    late = store(tmp_path, now=201)
    late.complete(scope(), 'a1', worker_id='w1', state='COMPLETED', actual_cost_usd=.1, summary={})
    with pytest.raises(ValueError): reserve(late, 'a2')


def test_normal_case_and_summary_do_not_claim_physical_success(tmp_path):
    s = store(tmp_path)
    s.begin_case(scope(), budget(max_calls=0, max_observations=0, max_cost_usd=0))
    assert s.close_case(scope(), state='NOT_NEEDED', reason='NORMAL')['calls'] == 0
    with pytest.raises(ValueError): s.close_case(scope(), state='SUCCESS', reason='MODEL_SAID_SO')


def test_summary_rejects_transcript_and_invalid_budget_bounds(tmp_path):
    for changes in (dict(deadline=221), dict(max_calls=9), dict(max_observations=9), dict(max_cost_usd=True)):
        with pytest.raises(ValueError): budget(**changes)
    s = store(tmp_path)
    s.begin_case(scope(), budget())
    reserve(s)
    s.mark_submitting(scope(), 'a1', worker_id='w1')
    with pytest.raises(ValueError):
        s.complete(scope(), 'a1', worker_id='w1', state='COMPLETED', actual_cost_usd=.1,
                   summary={'transcript': 'untrusted full output'})
    assert s.attempt(scope(), 'a1')['state'] == 'SUBMITTING'
