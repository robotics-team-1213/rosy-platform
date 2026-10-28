"""Real versioned provider codecs; synthetic launchers confer no runtime admission."""
import asyncio
from dataclasses import replace
import json

import pytest

from fleet.incidents.automation.worker import IncidentCaseWorker
from rosy.decision.deliberation.local import VersionedLocalProvider
from rosy.decision.deliberation.versioned_cli import VersionedCliProvider
from test_incident_case_worker import make_incident_worker, settled
from test_judgment_profiles import adapter


@pytest.mark.parametrize('kind', ['local', 'claude', 'opencode'])
@pytest.mark.parametrize('fault', ['malformed', 'malformed_text', 'unsafe', 'unknown_cost', 'provenance'])
def test_real_provider_known_cost_rejection_reviews_only_the_original_case(tmp_path, kind, fault):
    async def run():
        now, reviews, handoffs, _, board, store, old, poll, current = make_incident_worker(tmp_path, provider_cost=.01)
        await old.aclose()
        primary = replace(old.profiles[0], provider_kind=kind, model_id='provider/model', adapter='versioned-fixture')
        descriptor = adapter(provider_kind=kind, model_id=primary.model_id, adapter=primary.adapter)
        profiles = (primary, old.profiles[1])
        current[0] = profiles
        requests = []

        async def launch(*args):
            body = json.loads(args[0] if kind == 'local' else args[1])
            requests.append(body)
            # The rejected model text cannot become a current-case prior, receipt or evidence.
            rejected = '{broken-json' if fault == 'malformed_text' else {'case_id': 'foreign', 'input_hash': '0' * 64}
            if fault == 'unsafe': rejected['objections'] = ['unsafe']
            cost = None if fault == 'unknown_cost' else 0 if kind == 'local' else .01
            if kind == 'local':
                result = dict(model_id='foreign' if fault == 'provenance' else primary.model_id,
                    model_revision=primary.model_revision, cost_usd=cost,
                    usage=dict(input_tokens=10, output_tokens=20), judgment=rejected)
                return 0, json.dumps(result).encode()
            if kind == 'claude':
                return 0, json.dumps(dict(is_error=False, structured_output=rejected, total_cost_usd=cost)).encode()
            return 0, ('\n'.join(json.dumps(row) for row in (
                dict(type='text', part=dict(text=rejected if fault == 'malformed_text' else json.dumps(rejected))),
                dict(type='step_finish', part=dict(cost=cost))))).encode()

        launch.adapter_capabilities, launch.schema_versions, launch.cost_verified = descriptor, (2,), True
        if fault == 'provenance' and kind != 'local':
            launch.billing_receipt = {'basis': 'unverified-model-authored-cost'}
        provider = (VersionedLocalProvider(profile=primary, adapter=descriptor, launch=launch) if kind == 'local'
                    else VersionedCliProvider(profile=primary, adapter=descriptor, launch=launch, cli_version='1.18.35'))
        worker = IncidentCaseWorker(store, old.observation, board, profiles=profiles,
            providers=(provider, old.providers[1]), admission=old.admission, current_profiles=old.current_profiles,
            human_owned=old.human_owned, budget=old.budget, final_handoff=old.final_handoff,
            clock=lambda: now[0], enabled=True)
        snapshot = poll()
        problem = worker._problem(board.intervention_assessment('pinky'))
        scope = worker._scope(problem)
        worker.feed(snapshot)
        await settled(worker)
        case = store.case(scope)
        with store._transaction() as connection:
            attempts = [dict(row) for row in connection.execute(
                'SELECT * FROM fleet_incident_v2_attempts ORDER BY rowid')]
            traces = connection.execute('SELECT attempt_id FROM fleet_incident_v2_model_receipts').fetchall()
        assert len(requests) == 1 and requests[0]['problem']['input_hash'] == problem.digest
        assert requests[0]['problem']['case_id'] == scope.case_id
        if fault in {'malformed', 'malformed_text'}:
            assert case['calls'] == 2 and len(reviews) == 1 and not handoffs
            assert reviews[0][0].digest == problem.digest and reviews[0][2] == ()
            assert attempts[0]['state'] == 'REJECTED'
            assert attempts[0]['actual_micros'] == (0 if kind == 'local' else 10000)
            assert attempts[0]['input_hash'] == problem.digest
            assert all(row[0] != attempts[0]['attempt_id'] for row in traces)
        elif fault == 'unsafe':
            assert case['calls'] == 1 and reviews == [] and len(handoffs) == 1
            assert attempts[0]['state'] == 'REJECTED'
            assert attempts[0]['actual_micros'] == (0 if kind == 'local' else 10000)
            assert traces == [] and case['reason'] == 'MODEL_UNSAFE_REJECTION'
        else:
            assert case['calls'] == 1 and reviews == [] and len(handoffs) == 1
            assert attempts[0]['state'] == 'UNKNOWN' and attempts[0]['actual_micros'] is None
            assert traces == [] and case['state'] == 'HOLD'
        worker.feed(snapshot)
        await settled(worker)
        assert len(requests) == 1
        await worker.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['local', 'claude', 'opencode'])
def test_existing_direct_provider_call_keeps_value_error_on_invalid_judgment(kind):
    from test_versioned_local import local_provider
    from test_versioned_cli import make_cli_provider
    from test_judgment_profiles import bind_profile, problem
    if kind == 'local':
        provider, _ = local_provider('scope')
        target = problem()
        bound = bind_profile(target, provider.profile, provider.adapter, required_modalities=('text',))
    else:
        target, bound, transport, provider = make_cli_provider(kind)
        transport.result = {'case_id': 'foreign'}
    with pytest.raises(ValueError):
        asyncio.run(provider(target, bound, (), 1, budget_usd=provider.profile.max_cost_usd))


@pytest.mark.parametrize('fault', ['input', 'profile', 'type', 'cost'])
def test_changed_rejected_cost_context_cannot_authorize_a_reviewer(tmp_path, fault):
    from rosy.decision.deliberation.contracts.billing import RejectedJudgment
    async def run():
        now, reviews, handoffs, _, board, store, old, poll, _ = make_incident_worker(tmp_path, provider_cost=.01)
        await old.aclose()
        primary, descriptor = old.profiles[0], old.providers[0].adapter
        async def launch(*args):
            return 0, json.dumps(dict(model_id=primary.model_id, model_revision=primary.model_revision,
                cost_usd=0, usage=dict(input_tokens=1, output_tokens=1), judgment={})).encode()
        launch.adapter_capabilities, launch.schema_versions, launch.cost_verified = descriptor, (2,), True
        codec = VersionedLocalProvider(profile=primary, adapter=descriptor, launch=launch)
        async def altered(*args, **kwargs):
            try: return await codec(*args, **kwargs)
            except RejectedJudgment as error:
                if fault == 'input': error.bound = replace(error.bound, input_hash='0' * 64)
                elif fault == 'profile': error.bound = replace(error.bound, profile=replace(primary, model_revision='other'))
                elif fault == 'cost': error.cost_usd = primary.max_cost_usd + .01
                else:
                    class ForeignError(RejectedJudgment): pass
                    error = ForeignError(error.bound, error.cost_usd)
                raise error from None
        altered.profile, altered.adapter = primary, descriptor
        worker = IncidentCaseWorker(store, old.observation, board, profiles=old.profiles,
            providers=(altered, old.providers[1]), admission=old.admission, current_profiles=old.current_profiles,
            human_owned=old.human_owned, budget=old.budget, final_handoff=old.final_handoff,
            clock=lambda: now[0], enabled=True)
        snapshot = poll()
        scope = worker._scope(worker._problem(board.intervention_assessment('pinky')))
        worker.feed(snapshot); await settled(worker)
        case = store.case(scope)
        with store._transaction() as connection:
            attempt = dict(connection.execute('SELECT * FROM fleet_incident_v2_attempts').fetchone())
            assert connection.execute('SELECT COUNT(*) FROM fleet_incident_v2_model_receipts').fetchone()[0] == 0
        assert case['calls'] == 1 and case['state'] == 'HOLD' and reviews == [] and len(handoffs) == 1
        assert attempt['state'] == 'UNKNOWN' and attempt['actual_micros'] is None
        await worker.aclose()
    asyncio.run(run())
