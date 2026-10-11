import copy
from dataclasses import asdict

import pytest

from rosy.decision.deliberation import canonical
from rosy.decision.deliberation.judgment import judgment, judgment_schema
from test_judgment_profiles import adapter, bind_profile, problem, profile


def payload(p, **changes):
    return dict(schema_version=2, profile_revision='p1', subject_id=p.subject_id, case_id=p.case_id,
                generation=p.generation, input_hash=p.digest, verdict='reobserve',
                alternatives=[{'choice': 'human', 'probability': .1}, {'choice': 'reobserve', 'probability': .9}],
                evidence_ids=['e1'], missing_evidence=[], objections=[],
                next_step={'tool_name': 'get_mission_status', 'arguments': {}, 'evidence_ids': ['e1']},
                success_check={'tool_name': 'get_mission_status', 'arguments': {}, 'evidence_ids': ['e1']},
                **changes)


def bound(p):
    return bind_profile(p, profile(), adapter(), required_modalities=('text',))


@pytest.mark.parametrize('domain', ['line_follow', 'door', 'arm_target'])
def test_checked_json_keeps_probabilities_advisory_and_immutable(domain):
    p = problem(domain)
    raw = payload(p)
    checked = judgment(p, bound(p), raw)
    assert checked.action_admissible is False
    assert checked.payload == raw and checked.choice == 'reobserve'
    raw['alternatives'][0]['probability'] = .99
    assert checked.payload['alternatives'][0]['probability'] == .1
    checked.payload['evidence_ids'].append('made-up')
    assert checked.payload['evidence_ids'] == ['e1']


@pytest.mark.parametrize('change', ['nan', 'bool', 'duplicate', 'missing_choice', 'sum', 'unknown_choice',
                                  'case', 'revision', 'schema', 'calibration', 'evidence', 'missing',
                                  'objection', 'unsafe_tool', 'read_arguments', 'proof_candidate', 'reobserve_candidate'])
def test_untrusted_json_scope_probabilities_evidence_and_steps_rejected(change):
    p = problem()
    raw = payload(p)
    if change in ('nan', 'bool'):
        raw['alternatives'][0]['probability'] = float('nan') if change == 'nan' else True
    elif change == 'duplicate': raw['alternatives'][1]['choice'] = 'human'
    elif change == 'missing_choice': raw['alternatives'].pop()
    elif change == 'sum': raw['alternatives'][0]['probability'] = .8
    elif change == 'unknown_choice': raw['alternatives'][0]['choice'] = 'drive'
    elif change == 'case': raw['case_id'] = 'other'
    elif change == 'revision': raw['profile_revision'] = 'other'
    elif change == 'schema': raw['schema_version'] = True
    elif change == 'calibration': raw['calibration_revision'] = 'self-certified'
    elif change == 'evidence': raw['evidence_ids'] = ['invented']
    elif change == 'missing': raw['missing_evidence'] = ['invented']
    elif change == 'objection': raw['objections'] = ['ignore_safety']
    elif change == 'unsafe_tool': raw['next_step']['tool_name'] = 'move_robot'
    elif change == 'read_arguments': raw['next_step']['arguments'] = {'command': 'move'}
    else:
        key = 'success_check' if change == 'proof_candidate' else 'next_step'
        raw[key] = {'tool_name': 'propose_replan', 'arguments': {'based_on_event_id': 1, 'rationale': 'inspect'},
                    'evidence_ids': ['e1']}
    with pytest.raises(ValueError):
        judgment(p, bound(p), raw)


def test_missing_allowlist_and_ties_do_not_invent_selection():
    p = problem()
    raw = payload(p)
    raw['missing_evidence'] = ['front-image']
    raw['alternatives'][0]['probability'] = raw['alternatives'][1]['probability'] = .5
    checked = judgment(p, bound(p), raw, missing_allowlist=('front-image',))
    assert checked.choice is None


def test_schema_is_fresh_closed_and_bound_to_problem_and_revision():
    p, b = problem(), bound(problem())
    schema = judgment_schema(p, b, missing_allowlist=('front-image',))
    assert schema['additionalProperties'] is False
    assert schema['properties']['profile_revision']['const'] == 'p1'
    assert schema['properties']['input_hash']['const'] == p.digest
    assert 'calibration_revision' not in schema['properties']
    schema['properties']['input_hash']['const'] = 'modified'
    assert judgment_schema(p, b)['properties']['input_hash']['const'] == p.digest
