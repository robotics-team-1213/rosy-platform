"""D-652 necessity criteria; source correctness is a separate domain obligation."""

from dataclasses import FrozenInstanceError, replace
import importlib
import importlib.util
import math

import pytest


def api():
    assert importlib.util.find_spec('rosy_situation.assessment') is not None, 'D-652 assessment is missing'
    return importlib.import_module('rosy_situation.assessment')


def sample(**changes):
    a = api()
    values = dict(subject_id='arm-cell', case_id='job-7', revision='state-9', owner='cell-owner',
                  condition='progressing', evidence=(a.EvidenceRef('arm-cell', 'device', 'state-9', 99.0,
                                                                 case_id='job-7'),))
    values.update(changes)
    return a.AssessmentInput(**values)


def assess(request, now=100.0):
    a = api()
    return a.assess(request, now=now, policy=a.AssessmentPolicy('criteria-v1', 3.0, 5.0, 2.0))


@pytest.mark.parametrize('condition,since,until,status,reason', [
    ('progressing', None, None, 'DO_NOT_INTERVENE', 'progressing'),
    ('normal', None, None, 'DO_NOT_INTERVENE', 'normal'),
    ('resolved', None, None, 'DO_NOT_INTERVENE', 'resolved'),
    ('safe_wait', None, 110.0, 'DO_NOT_INTERVENE', 'safe_wait'),
    ('handling', None, 110.0, 'DO_NOT_INTERVENE', 'handling'),
    ('blocked', 98.0, None, 'DO_NOT_INTERVENE', 'confirmation_pending'),
    ('blocked', 95.0, None, 'INTERVENE', 'persistent_blockage'),
    ('safe_wait', None, 100.0, 'INTERVENE', 'wait_expired'),
    ('handling', None, 99.0, 'INTERVENE', 'handling_expired'),
    ('deadline_exceeded', None, None, 'INTERVENE', 'deadline_exceeded'),
    ('budget_exhausted', None, None, 'INTERVENE', 'budget_exhausted'),
    ('hazard', None, None, 'INTERVENE', 'hazard'),
    ('owner_lost', None, None, 'INTERVENE', 'owner_lost'),
    ('unknown', None, None, 'ABSTAIN', 'condition_unknown'),
    ('safe_wait', None, None, 'ABSTAIN', 'deadline_unknown'),
    ('handling', None, None, 'ABSTAIN', 'deadline_unknown'),
    ('blocked', None, None, 'ABSTAIN', 'duration_unknown'),
])
def test_necessity_criteria(condition, since, until, status, reason):
    result = assess(sample(condition=condition, since=since, until=until))
    assert (result.necessity, result.reason) == (status, reason)
    assert result.revision == 'state-9' and result.policy_revision == 'criteria-v1'


@pytest.mark.parametrize('subject,owner,case', [
    ('arm-cell', 'cell-owner', 'job-7'), ('robot', 'core-owner', 'stuck-7'),
    ('robot-group', 'traffic-owner', 'wait-cycle-7'), ('observation-only', 'site-observer', None),
])
def test_same_semantics_without_a_mission_or_fleet(subject, owner, case):
    a = api()
    request = sample(subject_id=subject, owner=owner, case_id=case,
                     evidence=(a.EvidenceRef(subject, 'observation', 'seq-9', 99.0, case_id=case),))
    assert assess(request).necessity == 'DO_NOT_INTERVENE'


@pytest.mark.parametrize('stamp,reason', [
    (96.9, 'evidence_stale'), (97.0, 'evidence_stale'), (100.1, 'evidence_future'),
    (math.nan, 'evidence_time_invalid'), (math.inf, 'evidence_time_invalid'),
    (True, 'evidence_time_invalid'),
])
def test_freshness_does_not_turn_uncertainty_into_normal(stamp, reason):
    a = api()
    request = sample(evidence=(a.EvidenceRef('arm-cell', 'device', 'state-9', stamp, case_id='job-7'),))
    result = assess(request)
    assert (result.necessity, result.reason) == ('ABSTAIN', reason)
    assert not result.applies_to(request, policy_revision='criteria-v1', now=100.0)


@pytest.mark.parametrize('changes,reason', [
    ({'evidence': ()}, 'evidence_missing'), ({'owner': None}, 'owner_unknown'),
    ({'revision': ''}, 'revision_missing'), ({'conflicted': True}, 'evidence_conflict'),
    ({'condition': 'invented'}, 'condition_unknown'),
])
def test_missing_or_conflicting_input_abstains(changes, reason):
    result = assess(sample(**changes))
    assert (result.necessity, result.reason) == ('ABSTAIN', reason)


def test_other_subject_or_incident_is_not_current_evidence():
    a = api()
    for subject, case in [('other-arm', 'job-7'), ('arm-cell', 'old-job')]:
        result = assess(sample(evidence=(a.EvidenceRef(subject, 'device', 'state-9', 99.0, case_id=case),)))
        assert result.necessity == 'ABSTAIN' and result.reason == 'evidence_binding_mismatch'


def test_oldest_evidence_and_deadlines_bound_the_permission_to_reuse():
    a = api()
    request = sample(condition='handling', until=100.5,
                     evidence=(a.EvidenceRef('arm-cell', 'device', 'state-9', 99.0, case_id='job-7'),
                               a.EvidenceRef('arm-cell', 'goal', 'goal-3', 98.0, case_id='job-7')))
    result = assess(request)
    assert result.valid_until == 100.5
    assert result.applies_to(request, policy_revision='criteria-v1', now=100.49)
    assert not result.applies_to(request, policy_revision='criteria-v2', now=100.1)
    assert not result.applies_to(request, policy_revision='criteria-v1', now=100.5)
    for changes in ({'revision': 'state-10'}, {'case_id': 'job-8'}, {'owner': 'another-owner'},
                    {'subject_id': 'another-cell'}):
        assert not result.applies_to(replace(request, **changes), policy_revision='criteria-v1', now=100.1)
    assert not result.applies_to(request, policy_revision='criteria-v1', now=99.9)
    assert not result.applies_to(request, policy_revision='criteria-v1', now=math.nan)


def test_transient_blockage_expires_at_confirmation_boundary():
    result = assess(sample(condition='blocked', since=96.0))
    assert result.valid_until == 101.0
    assert assess(sample(condition='blocked', since=96.0), now=101.0).necessity == 'INTERVENE'


def test_inputs_and_outputs_are_immutable_and_policy_is_validated():
    a = api()
    request = sample()
    with pytest.raises(FrozenInstanceError):
        request.condition = 'hazard'
    with pytest.raises(FrozenInstanceError):
        assess(request).necessity = 'INTERVENE'
    for args in [('', 3, 5, 2), ('v1', -1, 5, 2), ('v1', 3, math.nan, 2), ('v1', 3, 5, True)]:
        with pytest.raises(ValueError):
            a.AssessmentPolicy(*args)
