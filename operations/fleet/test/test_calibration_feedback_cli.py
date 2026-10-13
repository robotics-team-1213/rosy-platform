"""Real retained predictions bind to separately reviewed, externally frozen labels."""
import copy
from dataclasses import asdict, replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from test_incident_model_receipt import fixture
from test_incident_feedback_export import exporter
from test_model_judgment import payload
from test_judgment_calibration import digest, manifest
from fleet.incidents.automation.store import IncidentCaseStore, CaseBudget
from fleet.incidents.automation.ledger.receipt import model_receipt
from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation.profiles import BoundProfile

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / 'tools/decision_calibration.py'


def subject():
    spec = importlib.util.spec_from_file_location('feedback_calibration', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def data(tmp_path, model_revision='digest-1', primary_only=False, cost_evidence=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    exports, labels, transformed = [], {}, {}
    for split in ('fit', 'evaluation'):
        scope, problem, models, _, _, _ = fixture()
        problem = replace(problem, case_id=split)
        models = tuple(replace(p, calibration_revision='cal-1', model_revision=model_revision) for p in models)
        if primary_only: models = models[:1]
        scope = replace(scope, case_id=split, profile_sha256=digest([asdict(p) for p in models]))
        bound = BoundProfile(models[0], problem.digest)
        checked = judgment(problem, bound, payload(problem))
        cost = None
        if cost_evidence:
            from rosy.decision.deliberation.contracts.billing import CostEvidence
            from rosy.decision.deliberation import canonical
            cost = CostEvidence(canonical(dict(schema='rosy.model.cost_evidence/1',
                input_hash=problem.digest, job_sha256=digest({}), profile_sha256=digest(asdict(models[0])),
                judgment_sha256=digest(checked.payload), basis='local_free', policy_revision='cost-policy',
                evidence_sha256='e'*64, credential_sha256=None, provider_request_id=None, provider_response_id=None,
                usage=dict(input_tokens=0, output_tokens=1, total_tokens=1),
                marginal_cash_usd=0, observed_usd_charge=None)))
        receipt = model_receipt(scope, problem, bound, checked, profiles=models, cost_evidence=cost)
        store = IncidentCaseStore(tmp_path / (split+'.db'), clock=lambda: 101)
        store.begin_case(scope, CaseBudget(100, 200, 1, 0, 0,
                                         role_limits=(('primary', 2),) if primary_only else ()))
        store.reserve(scope, attempt_id='attempt', input_hash=problem.digest, observation_revision=problem.generation,
                      kind='model', role='primary', max_cost_usd=0, worker_id='worker')
        store.mark_submitting(scope, 'attempt', worker_id='worker')
        store.complete(scope, 'attempt', worker_id='worker', state='COMPLETED', actual_cost_usd=0,
                       summary={'reason': 'MODEL_CHECKED'}, model_receipt=receipt)
        exported = exporter().snapshot(store.path, scope.subject_id, scope.case_id, [asdict(p) for p in models])
        exports.append(exported)
        label = dict(id=split, session_id=split, recording_id=split,
                     session_sha256=digest(split), recording_sha256=digest(split+'-recording'),
                     reviewed_by='fixture-reviewer', expected='reobserve', latency_ms=10,
                     unsafe_error=False, binding_error=False, unnecessary_effect=False, required_abstain_error=False,
                     export_digest=exported['digest'], subject_id=scope.subject_id, case_id=scope.case_id,
                     attempt_id='attempt', receipt_sha256=digest(json.loads(receipt.payload_json)),
                     latency_source_sha256=digest(split+'-timing'))
        labels[split] = [label]
        binding = dict(export_digest=label['export_digest'], subject_id=scope.subject_id, case_id=scope.case_id,
                       attempt_id='attempt', receipt_sha256=label['receipt_sha256'],
                       input_hash=problem.digest, observation_revision=problem.generation,
                       latency_source_sha256=label['latency_source_sha256'])
        transformed[split] = [dict(**{k:v for k,v in label.items() if k not in binding},
            profile_revision=models[0].profile_revision, model_revision=models[0].model_revision,
            domain=problem.domain, calibration_revision='cal-1', full_profile_sha256=digest(asdict(models[0])),
            alternatives=checked.payload['alternatives'], abstained=checked.choice is None, feedback_binding=binding)]
    frozen = dict(profile_revision=models[0].profile_revision, model_revision=models[0].model_revision,
                  domain=problem.domain, calibration_revision='cal-1', full_profile_sha256=digest(asdict(models[0])),
                  choices=list(problem.choices), reviewed_by='fixture-reviewer', limits=None,
                  fit_sha256=digest(transformed['fit']), evaluation_sha256=digest(transformed['evaluation']),
                  training_sha256=digest(manifest()))
    return dict(schema='rosy.calibration.feedback_input/1', exports=exports, **labels,
                training=manifest(), reviewed_profile=frozen), transformed


@pytest.mark.parametrize('primary_only,cost_evidence', [(False, False), (False, True), (True, False), (True, True)])
def test_actual_producer_predictions_and_external_review_hashes_join(tmp_path, primary_only, cost_evidence):
    source, expected = data(tmp_path, primary_only=primary_only, cost_evidence=cost_evidence)
    before = copy.deepcopy(source)
    assembled = subject().feedback_bundle(source)
    assert assembled['fit'] == expected['fit'] and assembled['evaluation'] == expected['evaluation']
    assert source == before
    from rosy.decision.deliberation.calibration import evaluate_calibration
    report = evaluate_calibration(**assembled).report
    assert report['state'] == 'HOLD' and report['metrics']['count'] == 1 and report['field_accepted'] is False


@pytest.mark.parametrize('fault', ['case', 'receipt', 'label_prediction', 'missing', 'unknown', 'split', 'profile', 'frozen'])
def test_changed_binding_missing_prediction_or_unreviewed_hash_cannot_pass(tmp_path, fault):
    source, _ = data(tmp_path)
    label = source['evaluation'][0]
    if fault == 'case': label['case_id'] = 'other'
    elif fault == 'receipt': label['receipt_sha256'] = '0'*64
    elif fault == 'label_prediction': label['alternatives'] = []
    elif fault == 'missing': source['evaluation'] = []
    elif fault == 'unknown':
        attempt = source['exports'][1]['case']['attempts'][0]
        attempt.update(state='UNKNOWN', actual_micros=None, model_receipt=None)
        source['exports'][1]['digest'] = digest(source['exports'][1]['case'])
        label['export_digest'] = source['exports'][1]['digest']
    elif fault == 'split': source['evaluation'] = copy.deepcopy(source['fit'])
    elif fault == 'profile': source['reviewed_profile']['model_revision'] = 'other'
    else: source['reviewed_profile']['evaluation_sha256'] = '0'*64
    from rosy.decision.deliberation.calibration import evaluate_calibration
    with pytest.raises(ValueError): evaluate_calibration(**subject().feedback_bundle(source))


def test_existing_offline_cli_consumes_feedback_and_hides_bad_input(tmp_path):
    source, _ = data(tmp_path)
    path = tmp_path / 'feedback.json'
    path.write_text(json.dumps(source), encoding='utf-8')
    command = [sys.executable, str(TOOL), '--from-feedback', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report['state'] == 'HOLD' and report['metrics']['count'] == 1
    source['evaluation'][0]['receipt_sha256'] = '0'*64
    path.write_text(json.dumps(source), encoding='utf-8')
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert json.loads(result.stdout) == dict(state='HOLD', reason='INVALID_CALIBRATION_INPUT', field_accepted=False)
    assert not result.stderr


def test_extra_target_profile_attempt_is_not_silently_excluded(tmp_path):
    source, _ = data(tmp_path)
    exported = source['exports'][1]
    extra = copy.deepcopy(exported['case']['attempts'][0])
    extra['attempt_id'] = 'unreviewed-attempt'
    exported['case']['attempts'].append(extra)
    exported['case']['calls'] = exported['case']['budget']['max_calls'] = 2
    exported['digest'] = digest(exported['case'])
    source['evaluation'][0]['export_digest'] = exported['digest']
    with pytest.raises(ValueError, match='INCOMPLETE_FEEDBACK_REVIEW'):
        subject().feedback_bundle(source)


@pytest.mark.parametrize('field,value', [('domains', ['door']), ('domains', ['fleet_status']), ('modalities', ['image'])])
def test_json_resealed_unsupported_profile_is_not_valid_historical_evidence(tmp_path, field, value):
    source, _ = data(tmp_path)
    for exported, split in zip(source['exports'], ('fit', 'evaluation')):
        case = exported['case']
        for p in case['profiles']: p[field] = value
        case['scope']['profile_sha256'] = digest(case['profiles'])
        receipt = case['attempts'][0]['model_receipt']
        receipt['profiles'] = copy.deepcopy(case['profiles'])
        exported['digest'] = digest(case)
        source[split][0].update(export_digest=exported['digest'], receipt_sha256=digest(receipt))
    source['reviewed_profile']['full_profile_sha256'] = digest(source['exports'][0]['case']['profiles'][0])
    with pytest.raises(ValueError, match='FEEDBACK_SAMPLE_IDENTITY_CHANGED'):
        subject().feedback_bundle(source)


def test_feedback_compare_cli_reuses_identical_reviewed_truth(tmp_path):
    first, _ = data(tmp_path / 'first')
    second, _ = data(tmp_path / 'second', model_revision='another-model')
    path = tmp_path / 'comparison.json'
    path.write_text(json.dumps([first, second]), encoding='utf-8')
    result = subprocess.run([sys.executable, str(TOOL), '--from-feedback', '--compare', str(path)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report['state'] == report['promotion_state'] == 'HOLD'
    assert len(report['candidates']) == 2 and report['field_accepted'] is False
