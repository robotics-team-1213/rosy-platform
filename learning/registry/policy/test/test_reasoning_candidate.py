"""Registry candidates preserve recomputed offline evidence, never approval."""
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/registry/policy'), str(ROOT / 'contracts/learning/src'),
               str(ROOT / 'operations/decision/src'), str(ROOT / 'operations/fleet/test')]
from rosy.contracts.learning import seal
from test_judgment_calibration import rows, manifest, profile, limits, IDENTITY
from test_judgment_profiles import profile as model_profile


def inputs():
    fit, evaluation = rows('fit'), rows('evaluation')
    return asdict(model_profile(**{key: IDENTITY[key] for key in
        ('profile_revision', 'model_revision', 'calibration_revision')})), dict(
        fit=fit, evaluation=evaluation, training=manifest(), reviewed_profile=profile(fit, evaluation, limits()))


def subject():
    return importlib.import_module('reasoning_candidate')


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
