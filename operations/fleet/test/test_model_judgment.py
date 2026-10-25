from dataclasses import replace

import pytest

from rosy.decision.deliberation.judgment import judgment, judgment_schema, schema_missing_allowlist
from test_judgment_profiles import adapter, bind_profile, problem, profile


def payload(p, **changes):
    tool = 'get_incident_status' if p.domain in {'line_follow', 'door'} else 'get_mission_status'
    return dict(schema_version=2, profile_revision='p1', subject_id=p.subject_id, case_id=p.case_id,
                generation=p.generation, input_hash=p.digest, verdict='reobserve',
                alternatives=[{'choice': 'human', 'probability': .1}, {'choice': 'reobserve', 'probability': .9}],
                evidence_ids=['e1'], missing_evidence=[], objections=[],
                next_step={'tool_name': tool, 'arguments': {}, 'evidence_ids': ['e1']},
                success_check={'tool_name': tool, 'arguments': {}, 'evidence_ids': ['e1'],
                               'expected_facts': {'state': 'unknown'}},
                **changes)


def bound(p):
    return bind_profile(p, profile(), adapter(), required_modalities=('text',))


def test_huge_integer_probability_is_a_validation_error():
    p = problem()
    raw = payload(p)
    raw['alternatives'][0]['probability'] = 10**400
    with pytest.raises(ValueError, match='INVALID_PROBABILITY'):
        judgment(p, bound(p), raw)


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
                                  'objection', 'unsafe_tool', 'read_arguments', 'proof_candidate', 'reobserve_candidate',
                                  'proof_undeclared', 'proof_arbitrary'])
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
    elif change == 'proof_undeclared': raw['success_check'].pop('expected_facts')
    elif change == 'proof_arbitrary': raw['success_check']['expected_facts'] = {'success': True}
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


def test_normal_and_abstention_never_declare_treatment_and_output_limit_is_binding():
    p = replace(problem(), necessity='DO_NOT_INTERVENE')
    raw = payload(p)
    with pytest.raises(ValueError):
        judgment(p, bound(p), raw)
    raw.update(verdict='do_not_intervene', next_step=None, success_check=None)
    checked = judgment(p, bound(p), raw)
    assert checked.action_admissible is False and checked.choice is None
    restricted = bind_profile(p, profile(max_output_bytes=32), adapter(), required_modalities=('text',))
    with pytest.raises(ValueError):
        judgment(p, restricted, raw)


def test_candidate_is_non_executable_and_success_is_only_declared():
    p = problem('arm_target')
    raw = payload(p)
    raw.update(verdict='candidate', next_step={'tool_name': 'propose_replan',
               'arguments': {'based_on_event_id': 1, 'rationale': 'inspect'}, 'evidence_ids': ['e1']})
    assert judgment(p, bound(p), raw).action_admissible is False
    raw.update(verdict='abstain', next_step=None, success_check=None)
    assert judgment(p, bound(p), raw).choice is None


def test_empty_missing_allowlist_has_no_empty_enum_and_round_trips():
    """2026-10-25 Model PC: Ollama 0.35.1 refused `enum: []` with HTTP 400, so every default local job failed."""
    p, b = problem(), bound(problem())
    def enums(node):
        if isinstance(node, dict):
            return ([node['enum']] if 'enum' in node else []) + [e for v in node.values() for e in enums(v)]
        return [e for v in node for e in enums(v)] if isinstance(node, list) else []
    schema = judgment_schema(p, b)
    assert all(enums(schema)) and schema['properties']['missing_evidence'] == {'type': 'array', 'maxItems': 0}
    assert schema_missing_allowlist(schema) == []
    assert schema_missing_allowlist(judgment_schema(p, b, missing_allowlist=('camera',))) == ['camera']
    with pytest.raises(ValueError):
        judgment(p, b, payload(p, missing_evidence=['camera']))


@pytest.mark.parametrize('domain', ['line_follow', 'door', 'arm_target'])
def test_schema_variants_pair_each_verdict_with_the_steps_judgment_requires(domain):
    """2026-10-25 Model PC: 2 of 3 real judgments were reobserve with next_step null, refused after decoding."""
    from rosy.decision.model_tool_catalog import MODEL_TOOL_CATALOG, ToolEffectClass
    p = problem(domain)
    variants = {tuple(v['properties']['verdict']['enum']): v['properties'] for v in judgment_schema(p, bound(p))['anyOf']}
    assert set(variants) == {('abstain',), ('reobserve',), ('candidate',)}  # INTERVENE: do_not_intervene conflicts
    assert variants[('abstain',)]['next_step'] == variants[('abstain',)]['success_check'] == {'type': 'null'}
    for names, props in variants.items():
        if names != ('abstain',):
            assert {'type': 'null'} not in props['next_step']['anyOf'] + props['success_check']['anyOf']
    reads = [e['properties']['tool_name']['const'] for e in variants[('reobserve',)]['next_step']['anyOf']]
    assert reads and all(MODEL_TOOL_CATALOG[n].effect_class == ToolEffectClass.READ_ONLY for n in reads)
    for entry in judgment_schema(p, bound(p))['properties']['next_step']['anyOf'][1:]:
        assert not MODEL_TOOL_CATALOG[entry['properties']['tool_name']['const']].device_action_api


def test_schema_is_fresh_closed_and_bound_to_problem_and_revision():
    p, b = problem(), bound(problem())
    schema = judgment_schema(p, b, missing_allowlist=('front-image',))
    assert schema['additionalProperties'] is False
    assert schema['properties']['profile_revision']['const'] == 'p1'
    assert schema['properties']['input_hash']['const'] == p.digest
    assert 'calibration_revision' not in schema['properties']
    schema['properties']['input_hash']['const'] = 'modified'
    assert judgment_schema(p, b)['properties']['input_hash']['const'] == p.digest
