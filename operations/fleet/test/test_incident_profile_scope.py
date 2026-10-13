"""A foreign profile worker must never close, reset or hand off another owned case."""
import asyncio
from dataclasses import replace

import pytest

from test_incident_case_worker import make_incident_worker, settled
from fleet.incidents.automation.worker import IncidentCaseWorker
from fleet.incidents.automation.contract import CaseScope


@pytest.mark.parametrize('state', ['active', 'pending_handoff'])
def test_two_profiles_share_db_without_closing_or_handing_off_the_other_case(tmp_path, state):
    async def run():
        _, seen_a, handoffs_a, _, _, store, first, poll_a, _ = make_incident_worker(tmp_path)
        first.feed(poll_a()); await settled(first)
        scope = store.active_scopes()[0]
        if state == 'pending_handoff': store.close_case(scope, state='HOLD', reason='READ_OR_PROVIDER_UNAVAILABLE')
        before = store.case(scope)
        _, seen_b, handoffs_b, _, _, _, base, poll_b, current = make_incident_worker(tmp_path)
        await base.aclose()
        profiles = tuple(replace(p, profile_revision='other-revision') for p in base.profiles)
        current[0] = profiles
        for provider, profile in zip(base.providers, profiles): provider.profile = profile
        second = IncidentCaseWorker(store, base.observation, base.board, profiles=profiles,
            providers=base.providers, admission=base.admission, current_profiles=base.current_profiles,
            human_owned=base.human_owned, budget=base.budget, final_handoff=base.final_handoff,
            clock=base.clock, enabled=True)
        try:
            second.feed(poll_b()); await settled(second)
            assert not seen_b and not handoffs_b
            assert store.case(scope) == before
            assert len(seen_a) == 1 and not handoffs_a
            if state == 'pending_handoff':
                assert store.pending_handoffs() == (scope,)
                first.feed(poll_a()); await settled(first)
                assert handoffs_a[0][0] == scope and store.pending_handoffs() == ()
        finally:
            await second.aclose(); await first.aclose()
    asyncio.run(run())


def test_same_profile_worker_does_not_close_another_execution_owner(tmp_path):
    async def run():
        _, seen, handoffs, _, _, store, worker, poll, _ = make_incident_worker(tmp_path)
        scope = CaseScope('pinky', 'joint-case', 'arm', worker.profile_sha256, 'policy-1')
        store.begin_case(scope, worker.budget(scope))
        before = store.case(scope)
        try:
            worker.feed(poll(case='joint-case')); await settled(worker)
            assert store.case(scope) == before and not seen and not handoffs
        finally: await worker.aclose()
    asyncio.run(run())
