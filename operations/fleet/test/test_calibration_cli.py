import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_judgment_calibration import limits, manifest, profile, rows

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('reviewed,unsafe,state,code', [
    (False, False, 'HOLD', 1), (True, False, 'PASS_OFFLINE_ONLY', 0),
    (True, True, 'FAIL', 1),
])
def test_offline_cli_reports_reviewed_metrics_without_model_or_field_admission(tmp_path, reviewed, unsafe, state, code):
    fit, evaluation = rows('fit'), rows('evaluation')
    evaluation[0]['unsafe_error'] = unsafe
    data = dict(fit=fit, evaluation=evaluation, training=manifest(),
                reviewed_profile=profile(fit, evaluation, limits() if reviewed else None))
    source = tmp_path / 'reviewed.json'
    source.write_text(json.dumps(data), encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'tools/decision_calibration.py'), str(source)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == code, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['state'] == state and receipt['field_accepted'] is False
    assert receipt['metrics']['count'] == 60
    assert receipt['full_profile_sha256'] == data['reviewed_profile']['full_profile_sha256']


def test_offline_cli_refuses_changed_dataset_without_exposing_input(tmp_path):
    fit, evaluation = rows('fit'), rows('evaluation')
    data = dict(fit=fit, evaluation=evaluation, training=manifest(),
                reviewed_profile=profile(fit, evaluation, limits()))
    data['evaluation'][0]['expected'] = 'human'
    source = tmp_path / 'changed.json'
    source.write_text(json.dumps(data), encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'tools/decision_calibration.py'), str(source)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'state': 'HOLD', 'reason': 'INVALID_CALIBRATION_INPUT',
                                        'field_accepted': False}
    assert not result.stderr


def test_offline_cli_keeps_under_supported_bins_on_hold(tmp_path):
    fit, evaluation = rows('fit'), rows('evaluation')
    reviewed = limits()
    reviewed['minimum_bin_cases'] = 61
    source = tmp_path / 'reviewed.json'
    source.write_text(json.dumps(dict(fit=fit, evaluation=evaluation, training=manifest(),
                                     reviewed_profile=profile(fit, evaluation, reviewed))), encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'tools/decision_calibration.py'), str(source)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report['state'] == 'HOLD' and report['field_accepted'] is False
    assert all(value == 0 for value in report['metrics']['error_counts'].values())
