from dataclasses import asdict, replace
import hashlib
import json

import pytest

from fleet.incidents.automation.contract import CaseScope
from fleet.incidents.automation.store import IncidentCaseStore, CaseBudget
from fleet.incidents.automation.ledger.receipt import ModelReceipt, model_receipt, checked_receipt
from rosy.decision.deliberation import canonical
from rosy.decision.deliberation.judgment import Judgment, judgment
from rosy.decision.deliberation.profiles import BoundProfile
from test_judgment_profiles import adapter, bind_profile, problem, profile
from test_model_judgment import payload


def fixture():
    p = problem()
    profiles = (profile(), profile(profile_id='reviewer', role='reviewer'))
    bound = bind_profile(p, profiles[0], adapter(), required_modalities=('text',))
    scope = CaseScope(p.subject_id, p.case_id, 'core',
        hashlib.sha256(canonical([asdict(v) for v in profiles]).encode()).hexdigest(), 'policy-1')
    checked = judgment(p, bound, payload(p))
    attempt = dict(input_hash=p.digest, observation_revision=p.generation, kind='model', role='primary',
                   state='COMPLETED', actual_micros=0)
    return scope, p, profiles, bound, checked, attempt


def test_receipt_preserves_probabilities_exact_inputs_and_frozen_profile_without_raw_response():
    scope, p, profiles, bound, checked, attempt = fixture()
    receipt = model_receipt(scope, p, bound, checked, profiles=profiles)
    value = checked_receipt(scope, attempt, receipt)
    assert value['problem']['generation'] == p.generation and value['problem']['facts_json'] == p.facts_json
    assert value['judgment']['alternatives'] == checked.payload['alternatives']
    assert value['profiles'][0]['model_revision'] == bound.profile.model_revision
    assert value['role'] == 'primary' and len(receipt.payload_json.encode()) <= 16384
    assert 'raw_response' not in value and 'cost' not in value
    value['judgment']['alternatives'][0]['probability'] = .8
    assert checked_receipt(scope, attempt, receipt)['judgment']['alternatives'][0]['probability'] == .1


@pytest.mark.parametrize('fault', ['parent', 'role', 'input', 'generation', 'forged', 'extra', 'manifest'])
def test_foreign_or_unvalidated_receipts_cannot_be_independent_replay_evidence(fault):
    scope, p, profiles, bound, checked, attempt = fixture()
    receipt = model_receipt(scope, p, bound, checked, profiles=profiles)
    if fault == 'parent': scope = replace(scope, profile_sha256='b' * 64)
    elif fault == 'role': attempt['role'] = 'reviewer'
    elif fault == 'input': attempt['input_hash'] = 'c' * 64
    elif fault == 'generation': attempt['observation_revision'] = 'other'
    else:
        import json
        raw = json.loads(receipt.payload_json)
        if fault == 'forged': raw['judgment']['alternatives'][0]['probability'] = True
        elif fault == 'extra': raw['raw_response'] = 'private'
        else: raw['profiles'][0]['model_revision'] = 'other'
        receipt = ModelReceipt(canonical(raw))
    with pytest.raises(ValueError): checked_receipt(scope, attempt, receipt)


def test_builder_revalidates_typed_judgment_and_stale_checked_evidence_still_replays():
    scope, p, profiles, bound, checked, attempt = fixture()
    forged = Judgment(canonical({**checked.payload, 'case_id': 'foreign'}), checked.choice)
    with pytest.raises(ValueError): model_receipt(scope, p, bound, forged, profiles=profiles)
    receipt = model_receipt(scope, p, bound, checked, profiles=profiles)
    attempt.update(state='REJECTED', actual_micros=50000)
    assert checked_receipt(scope, attempt, receipt)['judgment']['input_hash'] == p.digest


@pytest.mark.parametrize('domains', [('door',), ('fleet_status',)])
def test_profile_without_incident_domain_cannot_be_historical_admission_evidence(domains):
    scope, p, profiles, bound, checked, attempt = fixture()
    raw = json.loads(model_receipt(scope, p, bound, checked, profiles=profiles).payload_json)
    profiles = (replace(profiles[0], domains=domains), profiles[1])
    scope = replace(scope, profile_sha256=hashlib.sha256(canonical([asdict(v) for v in profiles]).encode()).hexdigest())
    raw['profiles'] = [asdict(v) for v in profiles]
    with pytest.raises(ValueError, match='MODEL_RECEIPT_CASE_OR_ROLE_CHANGED'):
        checked_receipt(scope, attempt, ModelReceipt(canonical(raw)))
    with pytest.raises(ValueError):
        model_receipt(scope, p, BoundProfile(profiles[0], p.digest), checked, profiles=profiles)


@pytest.mark.parametrize('forged', [False, True])
def test_completion_atomically_keeps_verified_cost_with_valid_trace_or_trace_rejection(tmp_path, forged):
    scope, p, profiles, bound, checked, _ = fixture()
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: 101)
    store.begin_case(scope, CaseBudget(100, 130, 2, 2, .3))
    store.reserve(scope, attempt_id='model-1', input_hash=p.digest, observation_revision=p.generation,
                  kind='model', max_cost_usd=.1, worker_id='worker', role='primary')
    store.mark_submitting(scope, 'model-1', worker_id='worker')
    receipt = model_receipt(scope, p, bound, checked, profiles=profiles)
    if forged: receipt = ModelReceipt('{"raw_response":"private"}')
    result = store.complete(scope, 'model-1', worker_id='worker', state='COMPLETED',
                            actual_cost_usd=.05, summary={'reason': 'MODEL_CHECKED'}, model_receipt=receipt)
    assert result['state'] == ('REJECTED' if forged else 'COMPLETED')
    assert store.case(scope)['spent_micros'] == 50000 and store.case(scope)['reserved_micros'] == 0
    with store._transaction() as conn:
        rows = conn.execute('SELECT receipt_json FROM fleet_incident_v2_model_receipts').fetchall()
        assert len(rows) == (0 if forged else 1)
        if rows: assert rows[0][0] == receipt.payload_json


@pytest.mark.parametrize('fault', ['depth', 'probability', 'observation_time'])
def test_malformed_numeric_or_nested_receipt_preserves_known_cost(tmp_path, fault):
    scope, p, models, bound, checked, _ = fixture()
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: 101)
    store.begin_case(scope, CaseBudget(100, 130, 1, 0, .1))
    store.reserve(scope, attempt_id='model-1', input_hash=p.digest, observation_revision=p.generation,
                  kind='model', max_cost_usd=.1, worker_id='worker', role='primary')
    store.mark_submitting(scope, 'model-1', worker_id='worker')
    if fault == 'depth':
        forged = ModelReceipt('[' * 5000 + '0' + ']' * 5000)
    else:
        raw = json.loads(model_receipt(scope, p, bound, checked, profiles=models).payload_json)
        if fault == 'probability': raw['judgment']['alternatives'][0]['probability'] = 10**400
        else: raw['problem']['observed_at'] = 10**400
        forged = ModelReceipt(canonical(raw))
    result = store.complete(scope, 'model-1', worker_id='worker', state='COMPLETED',
                            actual_cost_usd=.05, summary={'reason': 'MODEL_CHECKED'}, model_receipt=forged)
    assert result['state'] == 'REJECTED'
    assert store.case(scope)['spent_micros'] == 50000 and store.case(scope)['reserved_micros'] == 0
    with store._transaction() as conn:
        assert conn.execute('SELECT COUNT(*) FROM fleet_incident_v2_model_receipts').fetchone()[0] == 0


@pytest.mark.parametrize('failure', ['none', 'builder', 'store'])
def test_actual_worker_links_checked_output_and_preserves_billing_on_trace_failure(tmp_path, monkeypatch, failure):
    import asyncio
    from test_incident_case_worker import make_incident_worker, settled
    builder_rejected = failure != 'none'
    if builder_rejected:
        def reject(*args, **kwargs): raise ValueError('TRACE_SCOPE_CHANGED')
        monkeypatch.setattr('fleet.incidents.automation.ledger.store.checked_receipt'
                           if failure == 'store' else 'fleet.incidents.automation.execution.worker.model_receipt', reject)
    async def run():
        _, seen, _, _, _, store, worker, poll, _ = make_incident_worker(tmp_path, provider_cost=.05)
        worker.feed(poll()); await settled(worker)
        scope = worker._scope(seen[0][0])
        with store._transaction() as conn:
            attempt = dict(conn.execute('SELECT * FROM fleet_incident_v2_attempts').fetchone())
            rows = conn.execute('SELECT receipt_json FROM fleet_incident_v2_model_receipts').fetchall()
            assert attempt['actual_micros'] == 50000
            assert len(rows) == (0 if builder_rejected else 1)
            if rows:
                raw = checked_receipt(scope, attempt, ModelReceipt(rows[0][0]))
                assert raw['judgment']['input_hash'] == seen[0][0].digest
            else: assert attempt['state'] == 'REJECTED'
        assert store.case(scope)['spent_micros'] == 50000
        if builder_rejected:
            assert store.case(scope)['state'] == 'HOLD' and store.case(scope)['reason'] == 'MODEL_TRACE_REJECTED'
            worker.feed(poll(2)); await settled(worker)
            assert len(seen) == 1 and store.case(scope)['observations'] == 0
        await worker.aclose()
    asyncio.run(run())
