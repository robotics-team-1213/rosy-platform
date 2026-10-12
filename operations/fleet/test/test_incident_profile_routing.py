"""Local selection and case ownership share the existing SQLite transaction."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading

import pytest

from fleet.incidents.automation.store import CaseScope
from fleet.incidents.automation.worker import IncidentCaseWorker
from test_incident_case_store import store, budget
from test_incident_case_worker import make_incident_worker, settled


def scope(profile='a', case='case'):
    return CaseScope('pinky', case, 'core', profile * 64, 'policy-1')


def test_selection_cas_restart_rollback_and_aba_revision(tmp_path):
    first = store(tmp_path)
    assert first.profile_route('core', 'policy-1') is None
    a = first.select_profile('core', 'policy-1', 'a' * 64, expected_revision=0)
    assert a == dict(current='a' * 64, previous=None, revision=1)
    second = store(tmp_path)
    b = second.select_profile('core', 'policy-1', 'b' * 64, expected_revision=1)
    with pytest.raises(ValueError, match='PROFILE_ROUTE_CHANGED'):
        first.select_profile('core', 'policy-1', 'c' * 64, expected_revision=1)
    assert first.profile_route('core', 'policy-1') == b
    back = second.rollback_profile('core', 'policy-1', expected_revision=2)
    assert back == dict(current='a' * 64, previous='b' * 64, revision=3)
    with pytest.raises(ValueError, match='PROFILE_ROUTE_CHANGED'):
        first.select_profile('core', 'policy-1', 'c' * 64, expected_revision=1)
    assert store(tmp_path).profile_route('core', 'policy-1') == back


def test_case_assignment_keeps_original_revision_budget_and_scope(tmp_path):
    ledger = store(tmp_path)
    with pytest.raises(ValueError, match='CASE_PROFILE_NOT_SELECTED'):
        ledger.begin_case(scope(), budget(), routed=True)
    ledger.select_profile('core', 'policy-1', 'a' * 64, expected_revision=0)
    ledger.begin_case(scope(), budget(), routed=True)
    ledger.select_profile('core', 'policy-1', 'b' * 64, expected_revision=1)
    assert ledger.assignment(scope()) == 1
    assert ledger.begin_case(scope(), budget(), routed=True)['calls'] == 0
    for rejected in (scope(case='old-new'), replace(scope('b', 'new'), owner_id='arm'),
                     replace(scope('b', 'new'), policy_revision='other-policy')):
        with pytest.raises(ValueError, match='CASE_PROFILE_NOT_SELECTED'):
            ledger.begin_case(rejected, budget(), routed=True)
    ledger.begin_case(scope('b', 'new'), budget(), routed=True)
    assert ledger.assignment(scope('b', 'new')) == 2
    with pytest.raises(ValueError, match='CASE_SCOPE_OR_BUDGET_CHANGED'):
        ledger.begin_case(scope('b'), budget(), routed=True)
    with pytest.raises(ValueError, match='CASE_SCOPE_OR_BUDGET_CHANGED'):
        ledger.begin_case(scope(), budget(max_calls=3), routed=True)
    assert store(tmp_path).assignment(scope()) == 1


def test_switch_cannot_pass_case_transaction_and_assign_wrong_revision(tmp_path):
    ledger = store(tmp_path)
    ledger.select_profile('core', 'policy-1', 'a' * 64, expected_revision=0)
    entered, release, switching = threading.Event(), threading.Event(), threading.Event()
    original = ledger._begin_case
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    ledger._begin_case = paused
    def switch():
        switching.set()
        return store(tmp_path).select_profile('core', 'policy-1', 'b' * 64, expected_revision=1)
    with ThreadPoolExecutor(2) as pool:
        case = pool.submit(ledger.begin_case, scope(), budget(), routed=True)
        assert entered.wait(5)
        selected = pool.submit(switch)
        assert switching.wait(5)
        try: assert not selected.done()
        finally: release.set()
        assert case.result()['state'] == 'ACTIVE'
        assert selected.result()['revision'] == 2
    assert ledger.assignment(scope()) == 1
    with pytest.raises(ValueError, match='CASE_PROFILE_NOT_SELECTED'):
        ledger.begin_case(scope(case='late'), budget(), routed=True)


@pytest.mark.parametrize('receipt_first', [False, True])
def test_actual_worker_routes_receipt_and_poll_without_stopping_pinned_case(tmp_path, receipt_first):
    async def run():
        now, calls, _, _, board, ledger, base, poll, _ = make_incident_worker(tmp_path)
        await base.aclose()
        worker = IncidentCaseWorker(ledger, base.observation, board, profiles=base.profiles,
            providers=base.providers, admission=base.admission, current_profiles=base.current_profiles,
            human_owned=base.human_owned, budget=base.budget, final_handoff=base.final_handoff,
            clock=base.clock, enabled=True, routed=True)
        try:
            snapshot = poll()
            with ledger._transaction() as connection:
                assert worker.prepare_receipt(connection, board.judgment_view('pinky')) is False
            worker.feed(snapshot); await settled(worker)
            assert not calls and not ledger.active_scopes()
            ledger.select_profile('core', board.intervention_assessment('pinky').policy_revision,
                                  worker.profile_sha256, expected_revision=0)
            if receipt_first:
                with ledger._transaction() as connection:
                    assert worker.prepare_receipt(connection, board.judgment_view('pinky')) is True
            worker.feed(snapshot); await settled(worker)
            assigned = ledger.active_scopes()[0]
            assert ledger.assignment(assigned) == 1 and len(calls) == 1
            original = ledger.case(assigned)['budget_json']
            ledger.select_profile('core', assigned.policy_revision, 'b' * 64, expected_revision=1)
            now[0] += 1
            worker.feed(poll(2)); await settled(worker)
            assert len(calls) == 2 and ledger.case(assigned)['budget_json'] == original
            worker.feed(poll(3, case='other')); await settled(worker)
            assert len(calls) == 2 and len(ledger.active_scopes()) == 1
        finally: await worker.aclose()
    asyncio.run(run())
