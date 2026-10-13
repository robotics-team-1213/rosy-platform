"""The creation fence never replaces pinned execution or original budgets."""
import asyncio
from dataclasses import replace

import pytest

from test_incident_case_worker import make_incident_worker, settled
from fleet.incidents.automation.worker import IncidentCaseWorker


def fenced(base, store, admission):
    return IncidentCaseWorker(store, base.observation, base.board, profiles=base.profiles,
        providers=base.providers, admission=base.admission, current_profiles=base.current_profiles,
        human_owned=base.human_owned, budget=base.budget, final_handoff=base.final_handoff,
        clock=base.clock, enabled=True, new_case_admission=admission)


@pytest.mark.parametrize('answer', [False, None, 1, 'true', 'error'])
def test_unaccepted_new_case_is_not_allocated_or_called_from_poll_or_receipt(tmp_path, answer):
    async def run():
        _, calls, _, _, board, store, base, poll, _ = make_incident_worker(tmp_path)
        await base.aclose()
        def decision(scope):
            if answer == 'error': raise RuntimeError('private routing source unavailable')
            return answer
        worker = fenced(base, store, decision)
        try:
            snapshot = poll()
            receipt = board.judgment_view('pinky')
            with store._transaction() as connection:
                assert worker.prepare_receipt(connection, receipt) is False
            worker.feed(snapshot); await settled(worker)
            assert calls == [] and store.active_scopes() == ()
        finally: await worker.aclose()
    asyncio.run(run())


def test_fenced_old_profile_continues_original_case_while_new_profile_gets_new_case(tmp_path):
    async def run():
        now_a, calls_a, _, _, board_a, store, base_a, poll_a, _ = make_incident_worker(tmp_path)
        await base_a.aclose()
        allowed = [True]
        first = fenced(base_a, store, lambda _: allowed[0])
        first.feed(poll_a()); await settled(first)
        scope_a = store.active_scopes()[0]
        original = store.case(scope_a)
        allowed[0] = False
        now_a[0] += 1
        first.feed(poll_a(2)); await settled(first)
        assert len(calls_a) == 2 and store.case(scope_a)['observations'] == 1
        assert store.case(scope_a)['budget_json'] == original['budget_json']
        with store._transaction() as connection:
            assert first.prepare_receipt(connection, board_a.judgment_view('pinky')) is True
        now_b, calls_b, _, _, board_b, _, base_b, poll_b, current = make_incident_worker(tmp_path)
        await base_b.aclose()
        now_b[0] = now_a[0]
        profiles = tuple(replace(p, model_id='new-model') for p in base_b.profiles)
        base_b.profiles = profiles; current[0] = profiles
        for provider, profile in zip(base_b.providers, profiles):
            provider.profile = profile; provider.adapter = replace(provider.adapter, model_id='new-model')
        second = fenced(base_b, store, lambda _: True)
        new_row = poll_b(case='new-case')['robots'][0]; new_row['robot_id'] = 'rosy'
        old_row = poll_a(2)['robots'][0]
        snapshot = {'robots': [old_row, new_row]}
        try:
            board_a.observe(snapshot['robots']); board_a.flush()
            board_b.observe(snapshot['robots']); board_b.flush()
            first.feed(snapshot); await settled(first)
            assert len(store.active_scopes()) == 1 and len(calls_a) == 2
            second.feed(snapshot); await settled(second)
            scopes = {s.subject_id: s for s in store.active_scopes()}
            assert scopes['pinky'] == scope_a and scopes['rosy'].profile_sha256 == second.profile_sha256
            assert store.case(scope_a)['calls'] == 2 and store.case(scope_a)['budget_json'] == original['budget_json']
            assert len(calls_b) == 1 and calls_b[0][0].subject_id == 'rosy'
        finally:
            await second.aclose(); await first.aclose()
    asyncio.run(run())
