"""Existing Fleet runtime routes pinned cases and new cases through one owner."""
import asyncio
from dataclasses import replace

import pytest

from fleet.incidents.automation.dispatcher import IncidentProfileDispatcher
from fleet.incidents.automation.worker import IncidentCaseWorker
from fleet.incidents.automation.routing import IncidentProfileRoutes
from test_incident_case_worker import make_incident_worker, settled
from test_incident_runtime import app, settings, poll as app_poll


def configured(base, profiles=None):
    profiles = profiles or base.profiles
    return dict(profiles=profiles, providers=base.providers, admission=base.admission,
        current_profiles=lambda: profiles, human_owned=base.human_owned, budget=base.budget,
        final_handoff=base.final_handoff, clock=base.clock, enabled=True, routed=True)


def test_original_case_continues_new_case_selects_new_worker_then_rollback(tmp_path):
    async def run():
        now, calls_a, _, _, board, store, base_a, poll, _ = make_incident_worker(tmp_path)
        await base_a.aclose()
        _, calls_b, _, _, _, _, base_b, _, _ = make_incident_worker(tmp_path)
        await base_b.aclose()
        profiles = tuple(replace(p, model_id='replacement') for p in base_b.profiles)
        for provider, profile in zip(base_b.providers, profiles):
            provider.profile = profile; provider.adapter = replace(provider.adapter, model_id='replacement')
        first = IncidentCaseWorker(store, base_a.observation, board, **configured(base_a))
        config_b = configured(base_b, profiles); config_b['clock'] = base_a.clock
        second = IncidentCaseWorker(store, base_a.observation, board, **config_b)
        dispatcher = IncidentProfileDispatcher((first, second))
        routes = IncidentProfileRoutes(store)
        try:
            snapshot = poll()
            request = board.intervention_assessment('pinky')
            routes.select_profile('core', request.policy_revision, first.profile_sha256, expected_revision=0)
            dispatcher.feed(snapshot); await settled(dispatcher)
            original_scope = store.active_scopes()[0]
            original = store.case(original_scope)
            routes.select_profile('core', request.policy_revision, second.profile_sha256, expected_revision=1)
            now[0] += 1
            old = poll(2)['robots'][0]
            new = poll(1, case='new')['robots'][0]; new['robot_id'] = 'rosy'
            snapshot = {'robots': [old, new]}; board.observe(snapshot['robots']); board.flush()
            with store._transaction() as conn:
                assert dispatcher.prepare_receipt(conn, board.judgment_view('rosy')) is True
                assert dispatcher.prepare_receipt(conn, board.judgment_view('pinky')) is True
            dispatcher.feed(snapshot); await settled(dispatcher)
            scopes = {s.subject_id: s for s in store.active_scopes()}
            assert scopes['pinky'] == original_scope and scopes['rosy'].profile_sha256 == second.profile_sha256
            assert store.assignment(scopes['rosy']) == 2 and store.assignment(original_scope) == 1
            assert store.case(original_scope)['budget_json'] == original['budget_json']
            assert [c[0].subject_id for c in calls_a] == ['pinky', 'pinky']
            assert [c[0].subject_id for c in calls_b] == ['rosy']
            routes.rollback_profile('core', request.policy_revision, expected_revision=2)
            third = poll(1, case='after-rollback')['robots'][0]; third['robot_id'] = 'third'
            snapshot['robots'].append(third); board.observe(snapshot['robots']); board.flush()
            dispatcher.feed(snapshot); await settled(dispatcher)
            assert calls_a[-1][0].subject_id == 'third' and len(calls_b) == 1
            scope = next(s for s in store.active_scopes() if s.subject_id == 'third')
            assert store.assignment(scope) == 3
        finally: await dispatcher.aclose()
    asyncio.run(run())


def test_factory_unknown_current_has_no_calls_then_selected_provider_only(tmp_path):
    async def run():
        first, calls_a = settings(enabled=True)
        second, calls_b = settings(enabled=True)
        second['profiles'] = tuple(replace(p, model_id='replacement') for p in second['profiles'])
        second['current_profiles'] = lambda: second['profiles']
        for provider, profile in zip(second['providers'], second['profiles']):
            provider.profile = profile; provider.adapter = replace(provider.adapter, model_id='replacement')
        clock = first.pop('clock'); second.pop('clock')
        application = app(tmp_path, dict(profile_workers=(first, second), clock=clock))
        dispatcher = application.state.stuck_resolver.incident_worker
        try:
            snapshot = app_poll(application)
            request = application.state.line_stuck.intervention_assessment('pinky')
            routes = IncidentProfileRoutes(dispatcher.store)
            routes.select_profile('core', request.policy_revision, 'f' * 64, expected_revision=0)
            dispatcher.feed(snapshot); await settled(dispatcher)
            assert not calls_a and not calls_b and not dispatcher.store.active_scopes()
            routes.select_profile('core', request.policy_revision, dispatcher.workers[1].profile_sha256,
                                  expected_revision=1)
            dispatcher.feed(snapshot); await settled(dispatcher)
            assert calls_a == [] and calls_b == ['case-1']
            dispatcher.feed(snapshot); await settled(dispatcher)
            assert calls_b == ['case-1']  # UNKNOWN is never submitted again.
            assert application.state.line_stuck._log.notifications._prepare_receipt.__self__ is dispatcher
        finally: await dispatcher.aclose()
    asyncio.run(run())


def test_selected_normal_has_no_calls_and_shutdown_reaps_inflight_once(tmp_path):
    async def run():
        started = asyncio.Event()
        async def blocked(_):
            started.set()
            await asyncio.Event().wait()
        _, calls, _, _, board, store, base, poll, _ = make_incident_worker(tmp_path, provider_hook=blocked)
        await base.aclose()
        worker = IncidentCaseWorker(store, base.observation, board, **configured(base))
        dispatcher = IncidentProfileDispatcher((worker,))
        routes = IncidentProfileRoutes(store)
        snapshot = poll()
        request = board.intervention_assessment('pinky')
        routes.select_profile('core', request.policy_revision, worker.profile_sha256, expected_revision=0)
        try:
            dispatcher.feed(poll(2, normal=True)); await settled(dispatcher)
            assert calls == [] and store.active_scopes() == ()
            dispatcher.feed(poll(3))
            await asyncio.wait_for(started.wait(), 2)
            scope = store.active_scopes()[0]
            await asyncio.wait_for(dispatcher.aclose(), 2)
            assert store.case(scope)['state'] == 'HOLD' and len(calls) == 1
            with store._transaction() as conn:
                assert conn.execute('SELECT state FROM fleet_incident_v2_attempts').fetchone()[0] == 'UNKNOWN'
            dispatcher.feed(snapshot); await settled(dispatcher)
            assert len(calls) == 1
            with store._transaction() as conn:
                assert dispatcher.prepare_receipt(conn, board.judgment_view('pinky')) is False
        finally: await dispatcher.aclose()
    asyncio.run(run())


def test_dispatcher_rejects_duplicate_profile_or_unrouted_worker(tmp_path):
    async def run():
        _, _, _, _, _, _, worker, _, _ = make_incident_worker(tmp_path)
        try:
            with pytest.raises(ValueError): IncidentProfileDispatcher((worker,))
            worker.routed = True
            with pytest.raises(ValueError): IncidentProfileDispatcher((worker, worker))
        finally: await worker.aclose()
    asyncio.run(run())


def test_shutdown_waits_for_every_worker_before_reporting_cleanup_error(tmp_path):
    async def run():
        first, _ = settings(enabled=True)
        second, _ = settings(enabled=True)
        second['profiles'] = tuple(replace(p, model_id='replacement') for p in second['profiles'])
        second['current_profiles'] = lambda: second['profiles']
        for provider, profile in zip(second['providers'], second['profiles']):
            provider.profile = profile; provider.adapter = replace(provider.adapter, model_id='replacement')
        clock = first.pop('clock'); second.pop('clock')
        application = app(tmp_path, dict(profile_workers=(first, second), clock=clock))
        dispatcher = application.state.stuck_resolver.incident_worker
        started, release = asyncio.Event(), asyncio.Event()
        async def failed(): raise RuntimeError('synthetic cleanup failure')
        async def blocked():
            started.set()
            await release.wait()
        closers = tuple(w.aclose for w in dispatcher.workers)
        dispatcher.workers[0].aclose = failed; dispatcher.workers[1].aclose = blocked
        closing = asyncio.create_task(dispatcher.aclose())
        try:
            await asyncio.wait_for(started.wait(), 2)
            await asyncio.sleep(.01)
            assert not closing.done()
            release.set()
            with pytest.raises(RuntimeError, match='synthetic cleanup failure'):
                await closing
        finally:
            release.set()
            await asyncio.gather(closing, return_exceptions=True)
            for closer in closers: await closer()
    asyncio.run(run())
