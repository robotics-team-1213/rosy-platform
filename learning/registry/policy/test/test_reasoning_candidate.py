"""Registry candidates preserve recomputed offline evidence, never approval."""
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import sys
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/registry/policy'), str(ROOT / 'contracts/learning/src'),
               str(ROOT / 'operations/decision/src'), str(ROOT / 'operations/fleet/test'),
               str(ROOT / 'operations/fleet')]
from rosy.contracts.learning import seal
from test_judgment_calibration import rows, manifest, profile, limits, IDENTITY
from test_judgment_profiles import profile as model_profile


def inputs():
    fit, evaluation = rows('fit'), rows('evaluation')
    return asdict(model_profile(**{key: IDENTITY[key] for key in
        ('profile_revision', 'model_revision', 'calibration_revision')})), dict(
        fit=fit, evaluation=evaluation, training=manifest(), reviewed_profile=profile(fit, evaluation, limits()))


def subject():
    return importlib.import_module('rosy.decision.deliberation.evaluation.reasoning_candidate')


def test_candidate_json_roundtrip_recomputes_and_preserves_scope():
    runtime, source = inputs()
    candidate = subject().build_candidate(runtime, source)
    assert candidate['domain'] == 'line_follow'
    assert candidate['calibration_report']['state'] == 'PASS_OFFLINE_ONLY'
    assert candidate['field_accepted'] is False
    assert subject().validate_candidate(json.loads(json.dumps(candidate))) == candidate
    source['evaluation'][0]['expected'] = 'human'
    assert subject().validate_candidate(candidate) == candidate  # Independent snapshot.


@pytest.mark.parametrize('change', ['model', 'budget', 'domain', 'report', 'truth', 'extra', 'revision'])
def test_resealed_candidate_cannot_replace_binding_or_evaluation(change):
    runtime, source = inputs()
    candidate = subject().build_candidate(runtime, source)
    if change == 'model': candidate['profile']['model_id'] = 'foreign'
    elif change == 'budget': candidate['profile']['max_calls'] = 1
    elif change == 'domain': candidate['domain'] = 'door'
    elif change == 'report': candidate['calibration_report']['state'] = 'PASS_FIELD'
    elif change == 'truth': candidate['calibration_input']['evaluation'][0]['expected'] = 'human'
    elif change == 'extra': candidate['approved'] = True
    else: candidate['profile']['calibration_revision'] = 'foreign'
    with pytest.raises(ValueError): subject().validate_candidate(seal(candidate))


def test_hold_is_preserved_and_null_calibration_revision_is_refused():
    runtime, source = inputs()
    source['reviewed_profile']['limits'] = None
    candidate = subject().build_candidate(runtime, source)
    assert candidate['calibration_report']['state'] == 'HOLD'
    assert subject().validate_candidate(candidate) == candidate
    runtime['calibration_revision'] = None
    with pytest.raises(ValueError): subject().build_candidate(runtime, source)


@pytest.mark.parametrize('reviewed', [True, False])
def test_isolated_model_pc_cli_produces_actual_candidate(tmp_path, reviewed):
    runtime, source = inputs()
    if not reviewed: source['reviewed_profile']['limits'] = None
    frozen = tmp_path / 'candidate-input.json'
    frozen.write_text(json.dumps(dict(profile=runtime, calibration_input=source)))
    result = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/decision_calibration.py'),
        '--candidate', str(frozen)], capture_output=True, text=True, timeout=30)
    assert result.returncode == (0 if reviewed else 1), result.stderr
    candidate = json.loads(result.stdout)
    assert len(result.stdout.encode()) > 16384
    assert subject().validate_candidate(candidate) == candidate
    assert candidate['calibration_report']['state'] == ('PASS_OFFLINE_ONLY' if reviewed else 'HOLD')


def test_candidate_cli_binds_real_journal_feedback_and_refuses_changed_receipt(tmp_path):
    from test_calibration_feedback_cli import data
    source, _ = data(tmp_path / 'journal')
    runtime = source['exports'][0]['case']['profiles'][0]
    path = tmp_path / 'feedback-candidate.json'
    command = [sys.executable, '-I', str(ROOT / 'tools/decision_calibration.py'),
               '--candidate', '--from-feedback', str(path)]
    path.write_text(json.dumps(dict(profile=runtime, calibration_input=source)))
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and not result.stderr
    candidate = subject().validate_candidate(json.loads(result.stdout))
    assert candidate['calibration_report']['state'] == 'HOLD'
    assert candidate['calibration_input']['evaluation'][0]['feedback_binding']['receipt_sha256']
    source['evaluation'][0]['receipt_sha256'] = '0' * 64
    path.write_text(json.dumps(dict(profile=runtime, calibration_input=source)))
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and not result.stderr
    assert json.loads(result.stdout) == dict(state='HOLD', reason='INVALID_CALIBRATION_INPUT', field_accepted=False)


def test_feedback_fixture_bootstraps_without_fleet_test_collection(tmp_path):
    script = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
              "import test_reasoning_candidate; from test_calibration_feedback_cli import data; "
              "data(Path(sys.argv[2]))")
    result = subprocess.run([sys.executable, '-I', '-c', script, str(Path(__file__).parent),
                             str(tmp_path / 'isolated-journal')], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
