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
    report = compare_deliberation(cases, runs, training_sessions=['training'],
                                 limits={'error_rate': 0.5, 'p95_latency_ms': 20, 'cost_usd': 1})
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
