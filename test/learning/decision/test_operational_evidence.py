"""Independent evidence compilation; SOURCE fixtures confer no field acceptance."""
import copy
import importlib.util
import hashlib
import hmac
import json
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


def signed(source, kind, *, principal='independent-reviewer'):
    raw = lambda v: json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    payload = dict(schema='rosy.incident.evidence_attestation/1', kind=kind,
        source_sha256=hashlib.sha256(raw(source)).hexdigest(), valid_from_s=90, expires_s=110)
    key = b'source-only-independent-test-key!!'
    receipt = dict(principal=principal, payload=payload,
        signature=hmac.new(key, raw(payload), hashlib.sha256).hexdigest())
    trust = {principal: dict(key=key, kinds={kind})}
    return receipt, trust


def test_authentic_review_verifier_binds_original_and_independent_kind():
    module = evaluator()
    original = {'truth': 'source-only-review'}
    receipt, trusted = signed(original, 'operational_truth')
    assert module.verify_attestation(receipt, original, trusted=trusted, kind='operational_truth', now=100)
    for source, kind, now in [({'truth': 'changed'}, 'operational_truth', 100),
                              (original, 'operational_limits', 100), (original, 'operational_truth', 111)]:
        with pytest.raises(ValueError):
            module.verify_attestation(receipt, source, trusted=trusted, kind=kind, now=now)


def source_window():
    names = ('observation', 'model', 'command', 'submission', 'result', 'recurrence', 'invoice')
    stream = dict(run_id='source-fixture-run', frames=[
        dict(sequence=1, received_at=99, monotonic_at=1, events=[]),
        dict(sequence=2, received_at=101, monotonic_at=3, events=[])])
    window = dict(schema='rosy.incident.operational_window/1', subject_id='robot-fixture', start=99,
        end=101, streams={name: copy.deepcopy(stream) for name in names})
    receipt, trust = signed(window, 'operational_capture')
    return {**window, 'attestation': receipt}, trust


def test_verified_empty_heartbeat_window_is_still_not_field_acceptance():
    module = evaluator(); window, trusted = source_window()
    checked = module.validate_window(window, trusted=trusted, now=100)
    assert checked['streams']['model']['events'] == []
    assert 'field_accepted' not in checked


@pytest.mark.parametrize('fault', ['sequence', 'boundary', 'clock', 'unsigned', 'invented_complete_flag'])
def test_missing_or_self_reported_window_coverage_is_rejected(fault):
    module = evaluator(); window, trusted = source_window()
    if fault == 'sequence': window['streams']['model']['frames'][1]['sequence'] = 3
    elif fault == 'boundary': window['streams']['model']['frames'][0]['received_at'] = 100
    elif fault == 'clock': window['streams']['command']['frames'][1]['monotonic_at'] = 1
    elif fault == 'unsigned': window['attestation']['signature'] = '0' * 64
    else: window['complete'] = True
    with pytest.raises(ValueError): module.validate_window(window, trusted=trusted, now=100)
