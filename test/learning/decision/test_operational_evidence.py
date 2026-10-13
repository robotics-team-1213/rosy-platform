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
    spec = importlib.util.spec_from_file_location('learning.evaluation.decision.operational_evidence', path)
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
    assert 'rosy.calibration.feedback_input/1' not in report['supported_original_contracts']
    assert 'feedback_prediction_export_lineage_admission' in report['unsupported']


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


def truth_row():
    return dict(id='evaluation-case', subject_id='robot-fixture', case_id='case-1', session_id='session-1',
        recording_id='recording-1', session_sha256='1' * 64, recording_sha256='2' * 64,
        start=99, end=101, expected='BACK_AND_RETRY', actor='model', resolved=None, recurrence=None,
        result_source_sha256=None, recurrence_source_sha256=None, latency_source_sha256=None, latency_ms=None,
        missing_evidence_error=False, risk_omission=False, wrong_case=False, unnecessary_intervention=False)


def test_unknown_physical_outcome_and_recurrence_remain_null_in_independent_metrics():
    module = evaluator()
    metrics, missing = module.measure_truth([truth_row()])
    assert metrics['case_count'] == 1 and metrics['unknown_outcomes'] == 1
    assert metrics['resolved_rate'] is None and metrics['recurrence_rate'] is None
    assert metrics['p95_latency_ms'] is None
    assert {'outcome_originals', 'recurrence_originals', 'latency_originals'} <= set(missing)


@pytest.mark.parametrize('field,value', [('actor', 'qwen'), ('resolved', 1), ('recurrence', 'no'),
    ('latency_ms', -1), ('risk_omission', None), ('expected', 'raw-command'), ('result_source_sha256', 'fake')])
def test_truth_schema_does_not_infer_or_coerce_final_review_values(field, value):
    module = evaluator(); row = truth_row(); row[field] = value
    with pytest.raises(ValueError): module.measure_truth([row])


def test_flags_only_raw_and_capture_reports_do_not_close_original_coverage():
    module = evaluator(); data = incomplete()
    originals = dict(raw_recordings=[], observation_windows=[],
                     coverage_scope='raw_sidecar_and_retained_observations_only')
    result = module.compile_evidence(data, trusted={}, now=100, originals=originals)
    assert 'verified_original_sources' in result['missing']
    assert 'physical_actor_credit' in result['unsupported']
    assert result['state'] == 'HOLD' and result['metrics'] is None


def test_an_unsupported_profile_domain_is_explicit_hold():
    module = evaluator(); data = incomplete()
    data['profile']['domains'] = ['door']; data['profiles'] = [data['profile']]
    result = module.compile_evidence(data, trusted={}, now=100)
    assert 'domain_backend_not_supported' in result['missing']
    assert result['state'] == 'HOLD' and result['metrics'] is None


def test_direct_compiler_does_not_claim_unrecomputed_profile_or_calibration():
    module = evaluator(); data = incomplete()
    data['calibration_input'] = {'fit': [], 'evaluation': [], 'training': {}, 'reviewed_profile': {}}
    result = module.compile_evidence(data, trusted={}, now=100)
    assert result['state'] == 'HOLD'
    assert result['profile_set_sha256'] is None and result['full_profile_sha256'] is None
    assert result['calibration_sha256'] is None
    assert result['profile_calibration_scope'] == 'not_recomputed'
    assert 'root_profile_calibration_not_recomputed' in result['missing']


@pytest.mark.parametrize('fault', ['unbound', 'pass_flag', 'unknown_calibration'])
def test_compiler_accepts_only_closed_bundle_bound_diagnostic_shape(fault):
    module = evaluator(); data = incomplete()
    diagnostic = dict(bundle_sha256=module.digest(data), profile_set_sha256='1' * 64,
        full_profile_sha256='2' * 64, calibration_sha256=None, calibration_state=None,
        domains=['line_follow'])
    if fault == 'unbound': diagnostic['bundle_sha256'] = '0' * 64
    elif fault == 'pass_flag': diagnostic['field_accepted'] = True
    else: diagnostic['calibration_state'] = 'PASS_FOR_OPERATION'
    with pytest.raises(ValueError):
        module.compile_evidence(data, trusted={}, now=100, profile_calibration=diagnostic)


def test_supplied_diagnostics_do_not_become_original_calibration_proof():
    module = evaluator(); data = incomplete()
    diagnostic = dict(bundle_sha256=module.digest(data), profile_set_sha256='1' * 64,
        full_profile_sha256='2' * 64, calibration_sha256=None, calibration_state=None,
        domains=['line_follow'])
    result = module.compile_evidence(data, trusted={}, now=100, profile_calibration=diagnostic)
    assert result['state'] == 'HOLD' and result['truth_admitted'] is False
    assert result['profile_calibration_scope'] == 'caller_supplied_diagnostics_only'
    assert result['calibration_sha256'] is None and 'calibration' in result['missing']
