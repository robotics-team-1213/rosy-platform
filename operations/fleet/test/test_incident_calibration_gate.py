"""Explicit approved calibration controls review; read-only work grants no device authority."""
import asyncio
from dataclasses import asdict, replace
import importlib

import pytest
from test_incident_case_worker import make_incident_worker, settled
from test_judgment_calibration import rows, manifest, limits, digest
from rosy.decision.deliberation.calibration import evaluate_calibration
from fleet.incidents.automation.worker import IncidentCaseWorker


async def setup(tmp_path, *, approved=True, broken=False):
    now, seen, handoffs, log, board, store, old, poll, current = make_incident_worker(tmp_path)
    await old.aclose()
    profiles = tuple(replace(p, calibration_revision='cal-1') for p in old.profiles)
    current[0] = profiles
    for provider, profile in zip(old.providers, profiles): provider.profile = profile
    artifacts = {}
    for profile in profiles:
        identity = dict(profile_revision=profile.profile_revision, model_revision=profile.model_revision,
                        calibration_revision=profile.calibration_revision, domain='line_follow',
                        full_profile_sha256=digest(asdict(profile)))
        fit, evaluation = rows('fit'), rows('evaluation')
        for row in (*fit, *evaluation): row.update(identity)
        frozen = dict(**identity, choices=['reobserve', 'human'], reviewed_by='fixture-reviewer',
            fit_sha256=digest(fit), evaluation_sha256=digest(evaluation), training_sha256=digest(manifest()), limits=limits())
        artifacts[profile.profile_id] = evaluate_calibration(fit, evaluation, training=manifest(), reviewed_profile=frozen)
    def artifact(profile):
        if broken: raise broken('private approval source unavailable')
        return artifacts[profile.profile_id]
    def approval():
        # Same revision in two profiles intentionally cannot certify both different full hashes.
        return {'cal-1': artifacts[profiles[0].profile_id].digest if approved else '0'*64}
    worker = IncidentCaseWorker(store, old.observation, board, profiles=profiles, providers=old.providers,
        admission=old.admission, current_profiles=old.current_profiles, human_owned=old.human_owned,
        budget=old.budget, final_handoff=old.final_handoff, clock=old.clock, enabled=True,
        calibration_artifacts=artifact, approved_artifacts=approval)
    return worker, now, seen, handoffs, store, poll


@pytest.mark.parametrize('approved,broken,calls', [(True, False, 1), (False, False, 2),
                                                (True, OSError, 2), (True, RuntimeError, 2)])
def test_actual_worker_uses_approved_full_profile_calibration_for_review(tmp_path, approved, broken, calls):
    async def run():
        worker, _, seen, handoffs, store, poll = await setup(tmp_path, approved=approved, broken=broken)
        worker.feed(poll(normal=True)); await settled(worker)
        assert not seen
        worker.feed(poll()); await settled(worker)
        assert len(seen) == calls and not handoffs
        if calls == 2:
            assert seen[1][1].profile.role == 'reviewer' and len(seen[1][2]) == 1
            assert seen[1][2][0][0].profile.role == 'primary'
        assert store.case(store.active_scopes()[0])['calls'] == calls
        assert worker._waiting
        await worker.aclose()
    asyncio.run(run())


def test_public_worker_import_keeps_canonical_execution_class_identity():
    execution = importlib.import_module('fleet.incidents.automation.execution.worker')
    assert IncidentCaseWorker is execution.IncidentCaseWorker
