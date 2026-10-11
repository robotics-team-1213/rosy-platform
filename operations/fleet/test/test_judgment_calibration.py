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


def full_profile_digest():
    from dataclasses import asdict
    from test_judgment_profiles import profile as runtime_profile
    return digest(asdict(runtime_profile(profile_revision=IDENTITY['profile_revision'],
        model_revision=IDENTITY['model_revision'], calibration_revision=IDENTITY['calibration_revision'])))


def rows(split, count=60):
    return [dict(id=f'{split}-{i}', session_id=split, recording_id=f'{split}-{i}',
                 session_sha256=digest(split), recording_sha256=digest(f'{split}-{i}'),
                 reviewed_by='fixture-reviewer', expected='reobserve', **IDENTITY,
                 full_profile_sha256=full_profile_digest(),
                 alternatives=[dict(choice='reobserve', probability=.99), dict(choice='human', probability=.01)],
                 abstained=False, latency_ms=10, unsafe_error=False, binding_error=False,
                 unnecessary_effect=False, required_abstain_error=False) for i in range(count)]


def manifest():
    return dict(sessions=['training'], recordings=['training-recording'],
                session_hashes=[digest('training')], recording_hashes=[digest('training-recording')])


def profile(fit, evaluation, limits=None):
    return dict(**IDENTITY, full_profile_sha256=full_profile_digest(),
                choices=['reobserve', 'human'], reviewed_by='fixture-reviewer',
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
    assert module.wilson_lower(60, 60) == pytest.approx(.9568532014067297, abs=1e-12)
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
    assert next(b for b in report['bins'] if b['choice'] == 'reobserve' and b['index'] == 9)['count'] == 60
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


@pytest.mark.parametrize('bad', [math.nan, math.inf, True, -.1, 1.1, 10**400])
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


def selection(artifact, *, score=.99, approved=True, domain='line_follow', objections=None, changed=False,
              model_changes=None):
    from dataclasses import replace
    from test_judgment_profiles import problem, profile as runtime_profile, adapter, bind_profile
    from test_model_judgment import payload
    from rosy.decision.deliberation.judgment import judgment
    p = problem(domain)
    values = dict(profile_revision=IDENTITY['profile_revision'],
                  model_revision=IDENTITY['model_revision'], calibration_revision='calibration-1')
    selected = runtime_profile(**{**values, **(model_changes or {})})
    descriptor = adapter(**{field: getattr(selected, field) for field in
                           ('provider_kind', 'model_id', 'model_revision', 'adapter')})
    b = bind_profile(p, selected, descriptor, required_modalities=('text',))
    raw = payload(p)
    raw.update(profile_revision=selected.profile_revision,
               alternatives=[dict(choice='reobserve', probability=score), dict(choice='human', probability=1-score)],
               objections=objections or [])
    checked = judgment(p, b, raw)
    return subject().select_calibrated(p, b, checked, artifact,
        approved_artifacts={'calibration-1': artifact.digest} if approved else {},
        current_profile=replace(selected, profile_revision='changed') if changed else selected)


def test_only_trusted_matching_artifact_qualifies_and_never_grants_action():
    fit, evaluation = rows('fit'), rows('evaluation')
    artifact = evaluate(fit, evaluation, profile(fit, evaluation, limits()))
    result = selection(artifact)
    assert result['eligible'] is True and result['action_admissible'] is False
    assert result['calibrated_confidence'] >= .95 and result['raw_probability'] == .99
    assert result['input_hash'] and result['case_id'] == 'case'
    for kwargs in [dict(approved=False), dict(domain='door'), dict(objections=['unsafe']), dict(changed=True)]:
        assert selection(artifact, **kwargs)['eligible'] is False
    assert selection(evaluate())['eligible'] is False


def test_small_or_empty_confidence_bin_never_promoted_and_raw_gap_is_separate():
    fit, evaluation = rows('fit', 50), rows('evaluation', 50)
    artifact = evaluate(fit, evaluation, profile(fit, evaluation, limits()))
    assert artifact.report['state'] == 'PASS_OFFLINE_ONLY'
    assert selection(artifact)['eligible'] is False
    fit, evaluation = rows('fit'), rows('evaluation')
    artifact = evaluate(fit, evaluation, profile(fit, evaluation, limits()))
    assert selection(artifact, score=.59)['eligible'] is False
    assert selection(artifact, score=.89)['eligible'] is False
    assert selection(artifact, score=.01)['eligible'] is False


@pytest.mark.parametrize('sequence', [list, tuple])
def test_frozen_collection_types_have_identical_metrics(sequence):
    fit, evaluation = sequence(rows('fit')), sequence(rows('evaluation'))
    assert evaluate(fit, evaluation).report['metrics']['count'] == 60


def test_fitted_probabilities_are_tested_without_refitting_on_evaluation_truth():
    fit, evaluation = rows('fit'), rows('evaluation')
    for row in fit:
        row['expected'] = 'human'
    report = evaluate(fit, evaluation, profile(fit, evaluation, limits())).report
    assert report['state'] == 'FAIL'
    assert report['metrics']['calibrated_top_brier'] == 1
    assert report['metrics']['calibrated_ece'] == 1
    assert report['metrics']['brier'] == pytest.approx(.0002)


def test_evaluation_bin_missing_from_fit_is_uncertified_not_fake_zero_error():
    fit, evaluation = rows('fit'), rows('evaluation')
    for row in evaluation:
        row['alternatives'] = [dict(choice='reobserve', probability=.01), dict(choice='human', probability=.99)]
        row['expected'] = 'human'
    report = evaluate(fit, evaluation, profile(fit, evaluation, limits())).report
    assert report['state'] == 'HOLD'
    assert report['metrics']['calibrated_coverage'] == 0
    assert report['metrics']['calibrated_top_brier'] is None


@pytest.mark.parametrize('change', [dict(profile_id='different-profile'), dict(model_id='different-model'),
    dict(provider_kind='http'), dict(adapter='http-json'), dict(role='reviewer'),
    dict(max_calls=1), dict(timeout_s=10), dict(max_cost_usd=.1)])
def test_artifact_cannot_be_reused_by_changed_model_profile_with_same_revision(change):
    fit, evaluation = rows('fit'), rows('evaluation')
    artifact = evaluate(fit, evaluation, profile(fit, evaluation, limits()))
    assert selection(artifact, model_changes=change)['eligible'] is False


@pytest.mark.parametrize('split', ['fit', 'evaluation'])
def test_total_support_cannot_hide_under_supported_probability_bin(split):
    fit, evaluation = rows('fit'), rows('evaluation')
    target = fit if split == 'fit' else evaluation
    for row in (target[1:] if split == 'fit' else target[:1]):
        row['alternatives'] = [dict(choice='reobserve', probability=.89), dict(choice='human', probability=.11)]
    if split == 'evaluation':
        for row in fit[:10]:
            row['alternatives'] = [dict(choice='reobserve', probability=.89), dict(choice='human', probability=.11)]
    report = evaluate(fit, evaluation, profile(fit, evaluation, limits())).report
    assert report['state'] == 'HOLD'
    assert min(report['metrics']['count'], report['fit_metrics']['count']) == 60


def test_exact_bin_minimum_and_absent_bins_keep_offline_pass():
    fit, evaluation = rows('fit'), rows('evaluation')
    reviewed = limits()
    reviewed['minimum_bin_cases'] = 60
    assert evaluate(fit, evaluation, profile(fit, evaluation, reviewed)).report['state'] == 'PASS_OFFLINE_ONLY'
    reviewed['minimum_bin_cases'] = 61
    assert evaluate(fit, evaluation, profile(fit, evaluation, reviewed)).report['state'] == 'HOLD'


@pytest.mark.parametrize('split', ['fit', 'evaluation'])
def test_error_categories_preserve_overlapping_errors_and_case_denominator(split):
    fit, evaluation = rows('fit'), rows('evaluation')
    target = fit if split == 'fit' else evaluation
    target[0].update(unsafe_error=True, binding_error=True, unnecessary_effect=True, required_abstain_error=True)
    target[1]['unsafe_error'] = True
    report = evaluate(fit, evaluation, profile(fit, evaluation, limits())).report
    metrics = report['fit_metrics'] if split == 'fit' else report['metrics']
    assert report['state'] == 'FAIL' and metrics['count'] == 60 and metrics['forbidden'] == 2
    assert metrics['error_counts'] == dict(unsafe_error=2, binding_error=1,
                                         unnecessary_effect=1, required_abstain_error=1)
