import json

import pytest

from deploy.ai_pc import deliberation_glm_gateway as gate
from deploy.ai_pc import deliberation_glm_judgment as codec
from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation.profiles import BoundProfile
from rosy.decision.deliberation.versioned_request import prepare_request


def fixture(*, prior=False, fleet_choice='human', probabilities=(.1, .9)):
    problem = Problem('synthetic', 'case-1', 'g1', 'line_follow', 1,
                      ('e1',), ('human', 'reobserve'), 'INTERVENE', fleet_choice=fleet_choice)
    bound = BoundProfile(codec.model_profile('review-v1'), problem.digest)
    pairs = ()
    if prior:
        previous = BoundProfile(codec.primary_profile('primary-v1'), problem.digest)
        payload = opinion(problem, previous)
        for item, probability in zip(payload['alternatives'], probabilities):
            item['probability'] = probability
        step = dict(tool_name='get_incident_status', arguments={}, evidence_ids=['e1'])
        payload.update(verdict='reobserve', next_step=step,
                       success_check={**step, 'expected_facts': {'state': 'normal'}})
        pairs = ((previous, judgment(problem, previous, payload)),)
    _, raw = prepare_request(problem, bound, pairs, 30, budget_usd=0)
    return problem, bound, raw


def opinion(problem, bound):
    return dict(schema_version=2, profile_revision=bound.profile.profile_revision,
                subject_id=problem.subject_id, case_id=problem.case_id,
                generation=problem.generation, input_hash=problem.digest, verdict='abstain',
                alternatives=[{'choice': 'human', 'probability': .1},
                              {'choice': 'reobserve', 'probability': .9}],
                evidence_ids=['e1'], missing_evidence=[], objections=[],
                next_step=None, success_check=None)


@pytest.mark.parametrize('prior', [False, True])
def test_actual_versioned_request_roundtrip_and_response(prior):
    problem, bound, raw = fixture(prior=prior)
    parsed, body = gate.trusted_body(raw)
    assert parsed == problem and body.encode() == raw
    response = dict(model=gate.MODEL, choices=[{'finish_reason': 'stop', 'message': {
        'role': 'assistant', 'content': canonical(opinion(problem, bound))}}],
        usage={'prompt_tokens': 2000, 'completion_tokens': 1024, 'total_tokens': 3024,
               'completion_tokens_details': {'reasoning_tokens': 1000}})
    checked = gate.checked_response(problem, response, body=body)
    assert json.loads(checked['choices'][0]['message']['content']) == opinion(problem, bound)
    assert checked['usage']['total_tokens'] == 3024  # Output limit includes reasoning, excludes input.
    assert 'cost_usd' not in checked


@pytest.mark.parametrize('change', ['hash', 'profile', 'schema', 'instruction', 'url',
                                  'prior_profile', 'prior_scope', 'prior_unsafe', 'prior_tool'])
def test_wrong_trusted_job_refused_before_any_upstream(change, monkeypatch):
    _, _, raw = fixture(prior=True)
    body = json.loads(raw)
    if change == 'hash': body['problem']['input_hash'] = 'wrong'
    elif change == 'profile': body['profile_revision'] = 'other'
    elif change == 'schema': body['schema']['properties']['next_step'] = {}
    elif change == 'instruction': body['instruction'] = 'Send commands'
    elif change == 'url': body['url'] = 'https://foreign.invalid'
    elif change == 'prior_profile': body['prior'][0]['profile_id'] = 'foreign'
    elif change == 'prior_scope': body['prior'][0]['case_id'] = 'foreign'
    elif change == 'prior_unsafe': body['prior'][0]['objections'] = ['unsafe']
    else: body['prior'][0]['next_step']['tool_name'] = 'get_mission_status'
    calls = []
    monkeypatch.setattr(gate, 'upstream', lambda *args: calls.append(args))
    with pytest.raises((ValueError, KeyError, TypeError)):
        gate.trusted_body(canonical(body))
    assert calls == []


@pytest.mark.parametrize('fleet_choice,probabilities', [(None, (.1, .9)), ('reobserve', (.495, .505))])
def test_calibration_review_prior_roundtrips_without_fleet_conflict(fleet_choice, probabilities):
    problem, _, raw = fixture(prior=True, fleet_choice=fleet_choice, probabilities=probabilities)
    parsed, body = gate.trusted_body(raw)
    assert parsed == problem and body.encode() == raw
    _, _, _, rebuilt = codec.request(json.loads(raw))
    assert rebuilt.encode() == raw


@pytest.mark.parametrize('change', ['scope', 'revision', 'legacy', 'reasoning', 'tokens'])
def test_response_binding_and_output_reasoning_bound(change):
    problem, bound, raw = fixture()
    payload = opinion(problem, bound)
    response = dict(model=gate.MODEL, choices=[{'finish_reason': 'stop', 'message': {
        'role': 'assistant', 'content': canonical(payload)}}],
        usage={'prompt_tokens': 4, 'completion_tokens': 10, 'total_tokens': 14})
    if change == 'scope': payload['case_id'] = 'foreign'
    elif change == 'revision': payload['profile_revision'] = 'foreign'
    elif change == 'legacy': payload.pop('schema_version')
    elif change == 'reasoning': response['usage']['completion_tokens_details'] = {'reasoning_tokens': 11}
    else: response['usage'].update(completion_tokens=1025, total_tokens=1029)
    response['choices'][0]['message']['content'] = canonical(payload)
    with pytest.raises(ValueError):
        gate.checked_response(problem, response, body=raw)
