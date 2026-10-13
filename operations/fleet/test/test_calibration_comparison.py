import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_judgment_calibration import rows, profile, manifest, limits, digest


def bundle(name, *, latency=10):
    fit, evaluation = rows(f'fit-{name}'), rows('evaluation')
    for row in (*fit, *evaluation):
        row.update(full_profile_sha256=digest(name), model_revision=name, latency_ms=latency)
    frozen = profile(fit, evaluation, limits())
    frozen.update(full_profile_sha256=digest(name), model_revision=name)
    return dict(fit=fit, evaluation=evaluation, training=manifest(), reviewed_profile=frozen)


def refreeze(value):
    for field in ('fit', 'evaluation', 'training'):
        value['reviewed_profile'][field + '_sha256'] = digest(value[field])


def compare(values):
    module = importlib.import_module('rosy.decision.deliberation.evaluation.comparison')
    return module.compare_calibrations(values).report


def test_same_reviewed_truth_allows_offline_comparison_but_never_promotion():
    values = [bundle('baseline'), bundle('candidate')]
    result = compare(values)
    assert result['state'] == 'PASS_COMPARISON_OFFLINE_ONLY'
    assert result['promotion_state'] == 'HOLD' and result['field_accepted'] is False
    assert result['baseline_profile_sha256'] == digest('baseline')
    assert len(result['candidates']) == 2
    assert all(not row['regressions'] for row in result['candidates'])
    values[1]['evaluation'].reverse()
    refreeze(values[1])
    assert compare(values)['evaluation_truth_sha256'] == result['evaluation_truth_sha256']


@pytest.mark.parametrize('field,value', [('expected', 'human'), ('reviewed_by', 'other'),
    ('session_id', 'other'), ('recording_sha256', digest('other'))])
def test_different_truth_or_lineage_cannot_be_compared(field, value):
    values = [bundle('baseline'), bundle('candidate')]
    values[1]['evaluation'][0][field] = value
    refreeze(values[1])
    with pytest.raises(ValueError):
        compare(values)


def test_duplicate_candidate_and_different_limits_refuse():
    original = bundle('baseline')
    with pytest.raises(ValueError):
        compare([original, copy.deepcopy(original)])
    candidate = bundle('candidate')
    candidate['reviewed_profile']['limits']['maximum_p95_latency_ms'] = 30
    with pytest.raises(ValueError):
        compare([original, candidate])


def test_latency_regression_fails_even_when_both_pass_their_limits():
    result = compare([bundle('baseline'), bundle('candidate', latency=11)])
    assert result['state'] == 'FAIL'
    assert result['candidates'][1]['calibration_state'] == 'PASS_OFFLINE_ONLY'
    assert 'p95_latency_ms' in result['candidates'][1]['regressions']


def test_missing_reviewed_limits_holds_and_forbidden_error_fails():
    values = [bundle('baseline'), bundle('candidate')]
    for value in values:
        value['reviewed_profile']['limits'] = None
    assert compare(values)['state'] == 'HOLD'
    values[1]['evaluation'][0]['unsafe_error'] = True
    refreeze(values[1])
    assert compare(values)['state'] == 'FAIL'


def test_same_truth_comparison_preserves_reviewed_bin_support_hold():
    values = [bundle('baseline'), bundle('candidate')]
    for value in values:
        value['reviewed_profile']['limits']['minimum_bin_cases'] = 61
    report = compare(values)
    assert report['state'] == 'HOLD' and report['promotion_state'] == 'HOLD'
    assert all(row['calibration_state'] == 'HOLD' for row in report['candidates'])


def test_each_candidate_must_keep_training_and_evaluation_independent():
    values = [bundle('baseline'), bundle('candidate')]
    values[1]['training']['sessions'].append('evaluation')
    refreeze(values[1])
    with pytest.raises(ValueError):
        compare(values)


def test_existing_model_pc_cli_can_compare_and_reports_no_operational_permission(tmp_path):
    source = tmp_path / 'comparison.json'
    source.write_text(json.dumps([bundle('baseline'), bundle('candidate')]))
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, str(root / 'tools/decision_calibration.py'),
                             '--compare', str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['promotion_state'] == 'HOLD'
