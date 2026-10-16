"""D-782 Prediction contract: a result can support stopping only, and the artifact rule is digest-bound."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'contracts/learning/src'))
from rosy.contracts.learning import prediction as contract


def ref(**kwargs):
    fields = dict(sample_id='s/c/0', observed_at_ns=10, rig_revision='rig-1', calibration_revision='cal-1')
    fields.update(kwargs)
    return contract.StateRef(**fields)


def request(**kwargs):
    fields = dict(state_ref=ref(), state=(0.,)*6, action=((1.,)*6,), step_s=.1, action_source='policy:r1')
    fields.update(kwargs)
    return contract.PredictionRequest(**fields)


def result(**kwargs):
    fields = dict(request_digest='a'*64, verdict='NO_OBJECTION', reason='none', predicted_states=((0.,)*6,),
                  uncertainty=((0.,)*6,), object_result=None, model_digest='b'*64,
                  dataset_manifest_sha256='c'*64, produced_at_ns=1, expires_at_ns=2)
    fields.update(kwargs)
    return contract.PredictionResult(**fields)


@pytest.mark.parametrize('bad', [dict(state=(0.,)*5), dict(action=()), dict(action=((1.,)*6,)*11),
                                 dict(state=(float('nan'),)*6), dict(step_s=0), dict(action_source=' x')])
def test_request_shape_is_explicit(bad):
    with pytest.raises(ValueError):
        request(**bad)


def test_request_digest_covers_state_action_and_revisions():
    base = request().digest()
    assert base == request().digest()
    assert base != request(action=((2.,)*6,)).digest()
    assert base != request(state_ref=ref(calibration_revision='cal-2')).digest()


def test_only_hold_and_reject_block_and_nothing_permits():
    assert [result(verdict=v).blocks for v in ('NO_OBJECTION', 'HOLD', 'REJECT')] == [False, True, True]
    abstained = result(verdict='ABSTAIN', predicted_states=(), uncertainty=())
    assert abstained.blocks is False
    assert not hasattr(abstained, 'permits') and not hasattr(abstained, 'grant')


@pytest.mark.parametrize('bad', [dict(verdict='ALLOW'), dict(verdict='ABSTAIN'), dict(expires_at_ns=1),
                                 dict(uncertainty=((-1.,)*6,)), dict(model_digest='x'),
                                 dict(object_result={'dropped': 1.0})])
def test_result_invariants(bad):
    with pytest.raises(ValueError):
        result(**bad)


def test_object_result_labels_match_human_review():
    spec = importlib.util.spec_from_file_location('native_review', ROOT/'learning/curation/omx/native_review.py')
    review = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review)
    assert review.OBJECT_RESULTS == contract.OBJECT_RESULTS
    distribution = {k: 0.0 for k in contract.OBJECT_RESULTS}
    distribution['dropped'] = 1.0
    assert result(object_result=distribution).object_result['dropped'] == 1.0


def artifact():
    weights = [[0.0]*6 for _ in range(12)]
    for i in range(6):
        weights[i][i], weights[6+i][i] = -0.5, 0.5
    document = dict(schema=contract.ARTIFACT_SCHEMA, kind='m1_linear_ensemble', horizon=1, step_s=.1,
                    rig_revision='rig-1', calibration_revision='cal-1', dataset_manifest_sha256='d'*64,
                    feature_mean=[0.0]*12, feature_std=[1.0]*12, state_min=[0.0]*6, state_max=[1.0]*6,
                    action_min=[0.0]*6, action_max=[1.0]*6,
                    members=[dict(bias=[1.0]*6, weights=weights), dict(bias=[-1.0]*6, weights=weights)])
    document['digest'] = contract.artifact_digest(document)
    return document


def test_forward_is_the_ensemble_mean_and_spread():
    states, sigma = contract.forward(contract.validate_artifact(artifact()), (0.,)*6, ((10.,)*6,))
    assert states == ((5.,)*6,) and sigma == ((1.,)*6,)
    with pytest.raises(ValueError, match='horizon'):
        contract.forward(artifact(), (0.,)*6, ((10.,)*6,)*2)


@pytest.mark.parametrize('fault', ['digest', 'members', 'scale', 'range', 'approved'])
def test_artifact_must_be_complete_unaltered_and_approved(fault):
    document = artifact()
    expected = None
    if fault == 'digest': document['members'][0]['bias'][0] = 2.0
    if fault == 'members': document['members'] = document['members'][:1]
    if fault == 'scale': document['feature_std'][0] = 0.0
    if fault == 'range': document['state_min'][0] = 2.0
    if fault == 'approved': expected = 'e'*64
    if fault != 'digest' and fault != 'approved':
        document['digest'] = contract.artifact_digest(document)
    with pytest.raises(ValueError):
        contract.validate_artifact(document, expected)
