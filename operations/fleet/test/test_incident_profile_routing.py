"""Local selection and case ownership share the existing SQLite transaction."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading

import pytest

from fleet.incidents.automation.store import CaseScope
from fleet.incidents.automation.routing import IncidentProfileRoutes
from fleet.incidents.automation.worker import IncidentCaseWorker
from test_incident_case_store import store, budget
from test_incident_case_worker import make_incident_worker, settled


def scope(profile='a', case='case'):
    return CaseScope('pinky', case, 'core', profile * 64, 'policy-1')


def test_selection_cas_restart_rollback_and_aba_revision(tmp_path):
    first = IncidentProfileRoutes(store(tmp_path))
    assert first.profile_route('core', 'policy-1') is None
    a = first.select_profile('core', 'policy-1', 'a' * 64, expected_revision=0)
    assert a == dict(current='a' * 64, previous=None, revision=1)
    second = IncidentProfileRoutes(store(tmp_path))
    b = second.select_profile('core', 'policy-1', 'b' * 64, expected_revision=1)
    with pytest.raises(ValueError, match='PROFILE_ROUTE_CHANGED'):
        first.select_profile('core', 'policy-1', 'c' * 64, expected_revision=1)
    assert first.profile_route('core', 'policy-1') == b
    back = second.rollback_profile('core', 'policy-1', expected_revision=2)
    assert back == dict(current='a' * 64, previous='b' * 64, revision=3)
    with pytest.raises(ValueError, match='PROFILE_ROUTE_CHANGED'):
        first.select_profile('core', 'policy-1', 'c' * 64, expected_revision=1)
    assert IncidentProfileRoutes(store(tmp_path)).profile_route('core', 'policy-1') == back


def test_competing_selections_have_one_winner_and_missing_previous_refuses_rollback(tmp_path):
    routes = IncidentProfileRoutes(store(tmp_path))
    with pytest.raises(ValueError, match='PREVIOUS_PROFILE_REQUIRED'):
        routes.rollback_profile('core', 'policy-1', expected_revision=0)
    def select(target):
        try: return IncidentProfileRoutes(store(tmp_path)).select_profile('core', 'policy-1', target * 64,
                                                                          expected_revision=0)['revision']
        except ValueError as error: return str(error)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(select, ('a', 'b')))
    assert results.count(1) == 1 and results.count('PROFILE_ROUTE_CHANGED') == 1
    assert routes.profile_route('core', 'policy-1')['previous'] is None
    with pytest.raises(ValueError, match='PREVIOUS_PROFILE_REQUIRED'):
        routes.rollback_profile('core', 'policy-1', expected_revision=1)


@pytest.mark.parametrize('revision,target', [(True, 'a' * 64), (-1, 'a' * 64), (0, 'short')])
def test_invalid_selection_cannot_mutate_current(tmp_path, revision, target):
    routes = IncidentProfileRoutes(store(tmp_path))
    with pytest.raises(ValueError):
        routes.select_profile('core', 'policy-1', target, expected_revision=revision)
    assert routes.profile_route('core', 'policy-1') is None


def test_case_assignment_keeps_original_revision_budget_and_scope(tmp_path):
    ledger = store(tmp_path)
    routes = IncidentProfileRoutes(ledger)
    with pytest.raises(ValueError, match='CASE_PROFILE_NOT_SELECTED'):
        ledger.begin_case(scope(), budget(), routed=True)
    routes.select_profile('core', 'policy-1', 'a' * 64, expected_revision=0)
    ledger.begin_case(scope(), budget(), routed=True)
    routes.select_profile('core', 'policy-1', 'b' * 64, expected_revision=1)
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
    IncidentProfileRoutes(ledger).select_profile('core', 'policy-1', 'a' * 64, expected_revision=0)
    entered, release, switching = threading.Event(), threading.Event(), threading.Event()
    original = ledger._begin_case
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    ledger._begin_case = paused
    def switch():
        switching.set()
        return IncidentProfileRoutes(store(tmp_path)).select_profile('core', 'policy-1', 'b' * 64, expected_revision=1)
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
        routes = IncidentProfileRoutes(ledger)
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
            routes.select_profile('core', board.intervention_assessment('pinky').policy_revision,
                                  worker.profile_sha256, expected_revision=0)
            if receipt_first:
                with ledger._transaction() as connection:
                    assert worker.prepare_receipt(connection, board.judgment_view('pinky')) is True
            worker.feed(snapshot); await settled(worker)
            assigned = ledger.active_scopes()[0]
            assert ledger.assignment(assigned) == 1 and len(calls) == 1
            original = ledger.case(assigned)['budget_json']
            routes.select_profile('core', assigned.policy_revision, 'b' * 64, expected_revision=1)
            now[0] += 1
            worker.feed(poll(2)); await settled(worker)
            assert len(calls) == 2 and ledger.case(assigned)['budget_json'] == original
            old_row = poll(2)['robots'][0]
            new_row = poll(3, case='other')['robots'][0]; new_row['robot_id'] = 'rosy'
            snapshot = {'robots': [old_row, new_row]}
            board.observe(snapshot['robots']); board.flush()
            worker.feed(snapshot); await settled(worker)
            assert len(calls) == 2 and len(ledger.active_scopes()) == 1
        finally: await worker.aclose()
    asyncio.run(run())


def test_actual_app_factory_requires_selection_for_routed_config(tmp_path):
    from test_incident_runtime import app, settings, poll
    async def run():
        config, calls = settings(enabled=True)
        application = app(tmp_path, {**config, 'routed': True})
        worker = application.state.stuck_resolver.incident_worker
        try:
            worker.feed(poll(application)); await settled(worker)
            assert calls == [] and not worker.store.active_scopes()
            routes = IncidentProfileRoutes(worker.store)
            request = application.state.line_stuck.intervention_assessment('pinky')
            scope = worker._scope(worker._problem(request))
            routes.select_profile('core', request.policy_revision, worker.profile_sha256, expected_revision=0)
            worker.feed(poll(application)); await settled(worker)
            assert calls == ['case-1']
            assert worker.store.assignment(scope) == 1
        finally: await worker.aclose()
    asyncio.run(run())
