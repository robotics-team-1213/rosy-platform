"""Single-primary execution creates its own manifest evidence, never a paired baseline clone."""
import asyncio
from dataclasses import asdict
import hashlib
import json

import pytest

from fleet.incidents.automation.contract import CaseBudget
from fleet.incidents.automation.worker import IncidentCaseWorker
from test_incident_case_worker import setup, settled
from test_incident_feedback_export import exporter


async def primary_setup(tmp_path, change=None):
    now, seen, handoffs, log, board, store, old, poll, current = setup(tmp_path, change=change)
    await old.aclose()
    profiles = old.profiles[:1]
    current[0] = profiles
    worker = IncidentCaseWorker(store, old.observation, board,
        profiles=profiles, providers=old.providers[:1], admission=old.admission,
        current_profiles=old.current_profiles, human_owned=old.human_owned,
        budget=lambda _: CaseBudget(now[0], now[0] + 30, 2, 2, 0, (('primary', profiles[0].max_calls),)),
        final_handoff=old.final_handoff, clock=old.clock, enabled=True)
    return worker, now, seen, handoffs, store, poll, profiles


def test_primary_only_has_no_normal_calls_and_exports_real_single_role_receipt(tmp_path):
    async def run():
        worker, now, seen, handoffs, store, poll, profiles = await primary_setup(tmp_path)
        worker.feed(poll(normal=True)); await settled(worker)
        assert not seen and not store.active_scopes()
        worker.feed(poll(2)); await settled(worker)
        assert len(seen) == 1 and seen[0][1].profile.role == 'primary'
        scope = store.active_scopes()[0]
        now[0] += 1
        worker.feed(poll(3, normal=True)); await settled(worker)
        exported = exporter().snapshot(store.path, scope.subject_id, scope.case_id, [asdict(profiles[0])])
        assert exported['schema'] == 'rosy.incident.model_feedback/3'
        assert exported['case']['outcome'] == 'RESOLVED_OBSERVED'
        assert exported['case']['attempts'][0]['model_receipt']['schema'] == 'rosy.incident.model_receipt/3'
        assert exported['case']['calls'] == 1 and not handoffs
        assert scope.profile_sha256 == hashlib.sha256(json.dumps([asdict(profiles[0])], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        await worker.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('change', ['conflict', 'invalid'])
def test_primary_needing_review_hands_off_without_unconfigured_second_call(tmp_path, change):
    async def run():
        worker, _, seen, handoffs, store, poll, profiles = await primary_setup(tmp_path, change)
        worker.feed(poll()); await settled(worker)
        assert len(seen) == 1 and len(handoffs) == 1
        scope, summary = handoffs[0]
        assert summary['reason'] == 'REVIEW_PROVIDER_NOT_CONFIGURED'
        exported = exporter().snapshot(store.path, scope.subject_id, scope.case_id,
                                       [asdict(profiles[0])], include_handoff=True)
        assert exported['schema'].endswith('/3') and 'handoff' in exported['case']
        assert exported['case']['calls'] == 1 and exported['field_accepted'] is False
        await worker.aclose()
    asyncio.run(run())
