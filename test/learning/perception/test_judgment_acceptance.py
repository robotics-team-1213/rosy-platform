"""Synthetic checker tests do not supply human labels or field acceptance."""

import pytest
import judgment_acceptance as checker


def fixture():
    categories = [('normal', 'DO_NOT_INTERVENE'), ('authorized_wait', 'DO_NOT_INTERVENE'),
                  ('blocked', 'INTERVENE'), ('insufficient', 'ABSTAIN'),
                  ('conflict', 'ABSTAIN'), ('natural_clearance', 'DO_NOT_INTERVENE')]
    labels = [{'id': str(index), 'subject_id': 'pinky', 'case_id': str(index),
               'category': category, 'expected': expected, 'dangerous': expected == 'INTERVENE',
               'due_ms': 100, 'session_id': 'eval-session', 'location_id': 'eval-location',
               'recording_sha256': 'a' * 64, 'start_at': index * 10, 'end_at': index * 10 + 1,
               'reviewed_by': 'fake-reviewer', 'truth_receipt': 'fake-independent-evidence'}
              for index, (category, expected) in enumerate(categories)]
    observations = [{'id': row['id'], 'necessity': row['expected'], 'policy_revision': 'fake-policy',
                     'latency_ms': 10, 'elapsed_ms': 100, 'notification_ms': 20 if row['expected'] == 'INTERVENE' else None,
                     'command_submitted': False, 'actual_subject_id': None, 'actual_case_id': None,
                     'command_stale': False, 'authority_valid': True, 'action_attempted': False,
                     'outcome': 'NATURAL_CLEARANCE' if row['category'] == 'natural_clearance' else 'UNKNOWN',
                     'outcome_receipt': None} for row in labels]
    training = [{'session_id': 'train-session', 'recording_sha256': 'b' * 64,
                 'location_id': 'train-location', 'start_at': 0, 'end_at': 10}]
    profile = {'schema': checker.SCHEMA, 'approved_by': 'fake-reviewer', 'review_receipt': 'fake-profile-review',
               'label_sha256': checker.digest(labels), 'training_sha256': checker.digest(training),
               'policy_revision': 'fake-policy', 'minimum_counts': {category: 1 for category, _ in categories},
               'minimum_resolution_cases': 0, 'limits': {'miss_rate': 0, 'unnecessary_rate': 0, 'abstain_rate': 1,
                 'p95_judgment_ms': 20, 'p95_notification_ms': 30, 'resolution_rate_min': 0,
                 'abstain_required_error_rate': 0}}
    return profile, labels, observations, training


def test_normal_denominator_abstain_and_natural_clearance_are_separate():
    result = checker.evaluate(*fixture())
    assert result['status'] == 'PASS_OFFLINE_ONLY'
    assert result['metrics']['miss_rate']['denominator'] == 1
    assert result['metrics']['unnecessary_rate']['denominator'] == 3
    assert result['metrics']['abstain_rate']['numerator'] == 2
    assert result['metrics']['resolution_rate']['value'] is None
    assert result['metrics']['natural_clearance'] == 1


def test_positive_abstain_before_deadline_is_pending_after_deadline_is_missed():
    profile, labels, observations, training = fixture()
    observations[2].update(necessity='ABSTAIN', elapsed_ms=50)
    result = checker.evaluate(profile, labels, observations, training)
    assert result['status'] == 'HOLD' and result['metrics']['pending_positive'] == 1
    assert result['metrics']['miss_rate']['numerator'] == 0
    observations[2]['elapsed_ms'] = 101
    result = checker.evaluate(profile, labels, observations, training)
    assert result['status'] == 'FAIL' and result['metrics']['danger_missed'] == 1


def test_unreviewed_or_unknown_thresholds_never_pass():
    profile, labels, observations, training = fixture()
    profile['approved_by'] = None
    assert checker.evaluate(profile, labels, observations, training)['status'] == 'HOLD'
    profile['approved_by'] = 'fake-reviewer'
    profile['limits']['p95_judgment_ms'] = None
    assert checker.evaluate(profile, labels, observations, training)['status'] == 'HOLD'


def test_label_hash_training_overlap_and_missing_observation_are_refused():
    profile, labels, observations, training = fixture()
    labels[0]['expected'] = 'INTERVENE'
    with pytest.raises(ValueError, match='label hash'):
        checker.evaluate(profile, labels, observations, training)
    profile, labels, observations, training = fixture()
    training[0]['session_id'] = 'eval-session'
    profile['training_sha256'] = checker.digest(training)
    with pytest.raises(ValueError, match='overlap'):
        checker.evaluate(profile, labels, observations, training)
    profile, labels, observations, training = fixture()
    with pytest.raises(ValueError, match='observation identity'):
        checker.evaluate(profile, labels, observations[:-1], training)


def test_normal_command_other_case_and_stale_action_fail_zero_gates():
    profile, labels, observations, training = fixture()
    observations[0].update(command_submitted=True, action_attempted=True,
                           actual_subject_id='other', actual_case_id='other', command_stale=True,
                           authority_valid=False)
    result = checker.evaluate(profile, labels, observations, training)
    assert result['status'] == 'FAIL'
    assert result['metrics']['normal_commands'] == 1
    assert result['metrics']['stale_or_other_case_actions'] == 1
    assert result['metrics']['forbidden_authority'] == 1


@pytest.mark.parametrize('necessity', ['INTERVENE', 'DO_NOT_INTERVENE'])
def test_required_abstain_cannot_pass_as_a_definite_judgment(necessity):
    profile, labels, observations, training = fixture()
    observations[3]['necessity'] = necessity
    observations[4]['necessity'] = necessity
    result = checker.evaluate(profile, labels, observations, training)
    assert result['status'] == 'FAIL'
    assert result['metrics']['abstain_required_error_rate'] == {'numerator': 2, 'denominator': 2, 'value': 1}


def test_duplicate_physical_interval_cannot_inflate_independent_samples():
    profile, labels, observations, training = fixture()
    labels.append({**labels[0], 'id': 'duplicate'})
    observations.append({**observations[0], 'id': 'duplicate'})
    profile['label_sha256'] = checker.digest(labels)
    with pytest.raises(ValueError, match='duplicate physical'):
        checker.evaluate(profile, labels, observations, training)
