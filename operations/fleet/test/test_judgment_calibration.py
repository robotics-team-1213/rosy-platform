import hashlib
import importlib
import json
import math

import pytest


IDENTITY = dict(profile_revision='profile-2', model_revision='model-1',
                domain='line_follow', calibration_revision='calibration-1')


def subject():
    return importlib.import_module('rosy.decision.deliberation.calibration')


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def rows(split, count=60):
    return [dict(id=f'{split}-{i}', session_id=split, recording_id=f'{split}-{i}',
                 session_sha256=digest(split), recording_sha256=digest(f'{split}-{i}'),
                 reviewed_by='fixture-reviewer', expected='reobserve', **IDENTITY,
                 alternatives=[dict(choice='reobserve', probability=.99), dict(choice='human', probability=.01)],
                 abstained=False, latency_ms=10, unsafe_error=False, binding_error=False,
                 unnecessary_effect=False, required_abstain_error=False) for i in range(count)]


def manifest():
    return dict(sessions=['training'], recordings=['training-recording'],
                session_hashes=[digest('training')], recording_hashes=[digest('training-recording')])


def profile(fit, evaluation, limits=None):
    return dict(**IDENTITY, choices=['reobserve', 'human'], reviewed_by='fixture-reviewer',
                fit_sha256=digest(fit), evaluation_sha256=digest(evaluation),
                training_sha256=digest(manifest()), limits=limits)


def limits():
    return dict(minimum_cases=10, minimum_bin_cases=10, minimum_accuracy_lower=.9,
                maximum_brier=.1, maximum_ece=.1, maximum_p95_latency_ms=20)


def evaluate(fit=None, evaluation=None, frozen=None):
    fit = fit if fit is not None else rows('fit')
    evaluation = evaluation if evaluation is not None else rows('evaluation')
    return subject().evaluate_calibration(fit, evaluation, training=manifest(),
                                         reviewed_profile=frozen or profile(fit, evaluation))


def test_one_sided_wilson_small_sample_does_not_certify_perfect_predictions():
    module = subject()
    assert module.wilson_lower(0, 0) == 0
    assert module.wilson_lower(50, 50) < .95
    assert module.wilson_lower(60, 60) == pytest.approx(.956852074218559, abs=1e-12)
    assert module.wilson_lower(0, 60) == pytest.approx(0)
    for counts in [(True, 10), (1, False), (-1, 10), (11, 10)]:
        with pytest.raises(ValueError):
            module.wilson_lower(*counts)


def test_unreviewed_quality_limits_hold_with_metrics_not_95_performance_claim():
    artifact = evaluate()
    report = artifact.report
    assert report['state'] == 'HOLD' and report['field_accepted'] is False
    assert report['metrics']['count'] == 60
    assert report['metrics']['brier'] == pytest.approx(.0002)
    assert report['metrics']['ece'] == pytest.approx(.01)
    assert report['bins'][-2]['count'] == 60
    assert artifact.digest == digest(report)


def test_frozen_independent_profile_can_only_pass_offline():
    fit, evaluation = rows('fit'), rows('evaluation')
    artifact = evaluate(fit, evaluation, profile(fit, evaluation, limits()))
    assert artifact.report['state'] == 'PASS_OFFLINE_ONLY'
    assert artifact.report['metrics']['accuracy_lower'] < 1
    assert artifact.report['field_accepted'] is False
    report = artifact.report
    report['state'] = 'PASS_FIELD'
    assert artifact.report['state'] == 'PASS_OFFLINE_ONLY'


@pytest.mark.parametrize('field,value', [('recording_id', 'fit-0'), ('session_id', 'fit'),
    ('recording_sha256', digest('fit-0')), ('session_sha256', digest('fit')),
    ('recording_id', 'training-recording'), ('session_sha256', digest('training'))])
def test_split_or_training_lineage_relabel_leak_refuses(field, value):
    fit, evaluation = rows('fit'), rows('evaluation')
    evaluation[0][field] = value
    with pytest.raises(ValueError, match='leak|duplicate'):
        evaluate(fit, evaluation)


@pytest.mark.parametrize('bad', [math.nan, math.inf, True, -.1, 1.1])
def test_invalid_probability_and_unknown_latency_refuse(bad):
    fit, evaluation = rows('fit'), rows('evaluation')
    evaluation[0]['alternatives'][0]['probability'] = bad
    with pytest.raises(ValueError):
        evaluate(fit, evaluation)
    evaluation = rows('evaluation')
    evaluation[0]['latency_ms'] = bad
    if bad != 1.1:
        with pytest.raises(ValueError):
            evaluate(fit, evaluation)


def test_revisions_hashes_and_partial_class_bin_fail_closed():
    fit, evaluation = rows('fit'), rows('evaluation')
    evaluation[0]['model_revision'] = 'other'
    with pytest.raises(ValueError, match='revision|identity'):
        evaluate(fit, evaluation)
    evaluation = rows('evaluation')
    frozen = profile(fit, evaluation, limits())
    frozen['evaluation_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='hash'):
        evaluate(fit, evaluation, frozen)


def test_danger_and_abstain_errors_count_in_denominator_and_fail():
    fit, evaluation = rows('fit'), rows('evaluation')
    evaluation[0]['abstained'] = True
    evaluation[0]['required_abstain_error'] = True
    artifact = evaluate(fit, evaluation, profile(fit, evaluation, limits()))
    assert artifact.report['state'] == 'FAIL'
    assert artifact.report['metrics']['count'] == 60 and artifact.report['metrics']['correct'] == 59
