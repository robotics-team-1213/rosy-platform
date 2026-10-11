from dataclasses import asdict, replace
import hashlib

import pytest

from fleet.incidents.automation.contract import CaseScope
from fleet.incidents.automation.ledger.receipt import ModelReceipt, model_receipt, checked_receipt
from rosy.decision.deliberation import canonical
from rosy.decision.deliberation.judgment import Judgment, judgment
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
