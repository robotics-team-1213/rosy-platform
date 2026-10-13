import hashlib
import json
import pytest
from tools.decision_replay import compare_deliberation


def case(case_id='case-1', **changes):
    return {**dict(id=case_id, session_id='evaluation', recording_id=case_id,
                   expected='reobserve', reviewed_by='team', problem_hash='a'*64), **changes}


def rows(cases):
    return [{ 'case_id': c['id'], 'problem_hash': c['problem_hash'], 'mode': mode,
              'choice': 'reobserve', 'latency_ms': 10, 'cost_usd': 0.01,
              'forbidden_effect': False, 'binding_error': False,
              'profile_revision': 'pinned', 'policy_revision': 'd640' }
            for c in cases for mode in ('rules', 'single', 'deliberation')]


def test_independent_same_cases_all_modes_denominators_and_no_field_pass():
    cases = [case(), case('case-2', expected=None)]
    runs = rows(cases)
    limits = {'error_rate': 0.5, 'p95_latency_ms': 20, 'cost_usd': 1}
    profile = {'dataset_sha256': hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
               'limits': limits, 'reviewed_by': 'team', 'minimum_cases': 2,
               'revisions': {mode: {'profile_revision': 'pinned', 'policy_revision': 'd640'}
                             for mode in ('rules', 'single', 'deliberation')}}
    report = compare_deliberation(cases, runs, training_sessions=['training'],
                                 training_recordings=[], reviewed_profile=profile, limits=limits)
    assert report['state'] == 'PASS_OFFLINE_ONLY' and report['field_accepted'] is False
    assert all(m['count'] == 2 and m['correct'] == 1 for m in report['modes'].values())


def test_unreviewed_or_unfixed_limits_hold_and_missing_or_leaked_cases_refuse():
    cases = [case()]
    assert compare_deliberation(cases, rows(cases), training_sessions=[], limits=None)['state'] == 'HOLD'
    with pytest.raises(ValueError):
        compare_deliberation(cases, rows(cases)[:-1], training_sessions=[], limits=None)
    with pytest.raises(ValueError):
        compare_deliberation(cases, rows(cases), training_sessions=['evaluation'], limits=None)


def test_forbidden_effect_is_zero_gate_and_unknown_latency_refuses():
    cases = [case()]
    runs = rows(cases)
    runs[0]['forbidden_effect'] = True
    assert compare_deliberation(cases, runs, training_sessions=[], limits=None)['state'] == 'FAIL'
    runs[0]['latency_ms'] = float('nan')
    with pytest.raises(ValueError):
        compare_deliberation(cases, runs, training_sessions=[], limits=None)


def test_frozen_limits_and_recording_lineage_are_required():
    cases = [case()]
    limits = {'error_rate': 0, 'p95_latency_ms': 20, 'cost_usd': 1}
    assert compare_deliberation(cases, rows(cases), training_sessions=[], limits=limits)['state'] == 'HOLD'
    with pytest.raises(ValueError, match='leaked'):
        compare_deliberation(cases, rows(cases), training_sessions=[],
                             training_recordings=['case-1'], limits=limits)


def test_same_recording_cannot_be_relabelled_as_independent_cases():
    cases = [case(), case('case-2', session_id='another', recording_id='case-1')]
    with pytest.raises(ValueError, match='duplicate'):
        compare_deliberation(cases, rows(cases), training_sessions=[], limits=None)


def test_mixed_or_unreviewed_mode_revisions_cannot_pass():
    cases = [case(), case('case-2')]
    limits = {'error_rate': 0, 'p95_latency_ms': 20, 'cost_usd': 1}
    profile = {'dataset_sha256': hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
               'limits': limits, 'reviewed_by': 'team', 'minimum_cases': 2,
               'revisions': {mode: {'profile_revision': 'pinned', 'policy_revision': 'd640'}
                             for mode in ('rules', 'single', 'deliberation')}}
    runs = rows(cases)
    runs[-1]['profile_revision'] = 'cherry-picked-v2'
    with pytest.raises(ValueError, match='revision'):
        compare_deliberation(cases, runs, training_sessions=[], training_recordings=[],
                             reviewed_profile=profile, limits=limits)
    del profile['revisions']
    with pytest.raises(ValueError, match='profile'):
        compare_deliberation(cases, rows(cases), training_sessions=[], training_recordings=[],
                             reviewed_profile=profile, limits=limits)
