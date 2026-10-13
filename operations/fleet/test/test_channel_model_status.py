"""An explicit status question cannot become CORE intervention or a device tool."""
from dataclasses import replace

import pytest

from rosy.decision.deliberation import Problem
from rosy.decision.deliberation.judgment import judgment, judgment_schema
from rosy.decision.model_tool_catalog import provider_tool_schemas
from test_judgment_profiles import adapter, bind_profile, problem, profile
from test_model_judgment import payload


def question():
    return Problem('fleet', 'request', 'observations-1', 'fleet_status', 1,
                   ('e1',), ('human', 'reobserve'), 'READ_ONLY_QUERY',
                   goal='Read the current Fleet status', facts_json='{"state":"offline"}')


def bound(p):
    selected = profile(profile_id='status-primary', adapter='status-json-v2', domains=('fleet_status',))
    admission = adapter(adapter='status-json-v2', domains=('fleet_status',))
    return bind_profile(p, selected, admission, required_modalities=('text',))


def status_payload(p):
    raw = payload(p)
    for field in ('next_step', 'success_check'):
        raw[field]['tool_name'] = 'get_fleet_state'
    raw['success_check']['expected_facts'] = {'state': 'offline'}
    return raw


def test_status_query_has_its_own_domain_admission_and_read_only_schema():
    p = question()
    checked = judgment(p, bound(p), status_payload(p))
    assert checked.action_admissible is False
    assert checked.choice == 'reobserve'
    with pytest.raises(ValueError, match='MODEL_PROFILE_NOT_ADMITTED'):
        bind_profile(p, profile(), adapter(), required_modalities=('text',))
    tools = provider_tool_schemas(scope='channel')
    assert [tool['name'] for tool in tools] == ['get_fleet_state']
    schema = judgment_schema(p, bound(p))
    assert 'propose_replan' not in str(schema) and 'request_incident_human' not in str(schema)


@pytest.mark.parametrize('change', ['candidate', 'mission_tool', 'incident_tool', 'arguments', 'evidence', 'facts'])
def test_status_model_cannot_cross_scope_or_invent_evidence(change):
    p = question()
    raw = status_payload(p)
    if change == 'candidate': raw['verdict'] = 'candidate'
    elif change == 'mission_tool': raw['next_step']['tool_name'] = 'propose_replan'
    elif change == 'incident_tool': raw['next_step']['tool_name'] = 'request_incident_human'
    elif change == 'arguments': raw['next_step']['arguments'] = {'command': 'move'}
    elif change == 'evidence': raw['evidence_ids'] = ['invented']
    else: raw['success_check']['expected_facts'] = {'token': 'private'}
    with pytest.raises(ValueError):
        judgment(p, bound(p), raw)


def test_status_question_is_not_operational_intervention_and_old_hash_is_unchanged():
    p = question()
    for necessity in ('INTERVENE', 'DO_NOT_INTERVENE', 'ABSTAIN'):
        with pytest.raises(ValueError): replace(p, necessity=necessity)
    with pytest.raises(ValueError): replace(problem(), necessity='READ_ONLY_QUERY')
    original = problem()
    assert original.facts_json == '{"state":"unknown"}'
    assert original.digest == 'ba4d1447f9c793a9685c05213ffd960747d169c5e5534a8e7bee3a96c9632fd3'
