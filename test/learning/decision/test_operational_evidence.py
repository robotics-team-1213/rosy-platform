"""Independent evidence compilation; SOURCE fixtures confer no field acceptance."""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def evaluator():
    path = ROOT / 'learning/evaluation/decision/operational_evidence.py'
    assert path.exists(), 'frozen operational evidence compiler missing'
    spec = importlib.util.spec_from_file_location('operational_evidence', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def incomplete():
    profile = dict(profile_id='primary', profile_revision='r1', role='primary', provider_kind='local',
        model_id='source-fixture', model_revision='model-r1', adapter='local-v2', domains=['line_follow'],
        modalities=['text'], timeout_s=1, max_output_bytes=1024, max_calls=1, max_cost_usd=0,
        calibration_revision='cal-r1', schema_version=2)
    return dict(schema='rosy.incident.operational_evidence/1', profiles=[profile], profile=profile,
        calibration_input=None, cohort=None, exports=[], inventories=[], inventory_digests=[],
        truth=None, limits=None, windows=[], review=None)


def test_missing_originals_produce_hold_and_null_not_fake_acceptance():
    data = incomplete()
    before = copy.deepcopy(data)
    report = evaluator().compile_evidence(data, trusted={}, now=100)
    assert report['state'] == 'HOLD' and report['field_accepted'] is False
    assert report['truth_admitted'] is False
    assert {'calibration', 'cohort', 'truth', 'limits', 'windows', 'review'} <= set(report['missing'])
    assert report['metrics'] is None and data == before


@pytest.mark.parametrize('field,value', [('state', 'PASS_FOR_OPERATION'), ('binding', {}),
    ('field_accepted', True), ('truth_admitted', True), ('report', {'state': 'PASS_FOR_OPERATION'})])
def test_self_reported_pass_or_binding_is_not_an_evidence_input(field, value):
    data = incomplete(); data[field] = value
    with pytest.raises(ValueError): evaluator().compile_evidence(data, trusted={}, now=100)


def test_invented_profile_cannot_be_resealed_as_installed_identity():
    data = incomplete(); data['profile'] = {**data['profile'], 'model_revision': 'other'}
    with pytest.raises(ValueError): evaluator().compile_evidence(data, trusted={}, now=100)


def test_unknown_values_are_not_zero_filled_in_limits():
    data = incomplete(); data['limits'] = {'minimum_cases': None}
    with pytest.raises(ValueError): evaluator().compile_evidence(data, trusted={}, now=100)
