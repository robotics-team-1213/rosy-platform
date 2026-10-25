"""Opt-in version two JSON validation. Catalog references remain advisory."""
from dataclasses import dataclass, replace
import json
import math

from ...model_tool_catalog import MODEL_TOOL_CATALOG, ToolEffectClass
from ...model_tool_contract import ModelToolCall
from .. import OBJECTIONS, canonical, identifier

FIELDS = ('schema_version', 'profile_revision', 'subject_id', 'case_id', 'generation', 'input_hash',
          'verdict', 'alternatives', 'evidence_ids', 'missing_evidence', 'objections', 'next_step', 'success_check')
VERDICTS = ('do_not_intervene', 'reobserve', 'candidate', 'abstain')


def refs(values, allowed, *, required=False):
    if (type(values) is not list or len(values) > 16 or (required and not values)
            or any(type(value) is not str or value not in allowed for value in values)
            or len(set(values)) != len(values)):
        raise ValueError('INVALID_JUDGMENT_REFERENCES')


def step(problem, value, *, read_only):
    if type(value) is not dict or set(value) != {'tool_name', 'arguments', 'evidence_ids'}:
        raise ValueError('INVALID_JUDGMENT_STEP')
    definition = MODEL_TOOL_CATALOG.get(value['tool_name']) if type(value['tool_name']) is str else None
    scope = ('channel' if problem.domain == 'fleet_status' else
             'incident' if problem.domain in {'line_follow', 'door'} else 'mission')
    if (definition is None or definition.scope != scope or not definition.feedback_enabled or definition.device_action_api
            or (read_only or problem.domain == 'fleet_status')
            and definition.effect_class != ToolEffectClass.READ_ONLY):
        raise ValueError('STEP_NOT_ADMITTED')
    refs(value['evidence_ids'], problem.evidence_ids, required=True)
    call = ModelToolCall(provider_call_id='judgment-v2', tool_name=definition.name,
                         arguments=value['arguments'], turn_id=problem.digest, ordinal=0)
    args = call.arguments
    if definition.name == 'propose_lane_back':
        if (problem.domain != 'line_follow' or 'back_and_retry' not in problem.choices
                or set(args) != {'rationale'} or type(args['rationale']) is not str
                or not args['rationale'] or args['rationale'] != args['rationale'].strip() or len(args['rationale']) > 512):
            raise ValueError('INVALID_RECOVERY_CANDIDATE')
        return
    if definition.effect_class == ToolEffectClass.READ_ONLY:
        if args:
            raise ValueError('INVALID_READ_ARGUMENTS')
    elif (set(args) != {'based_on_event_id', 'rationale'} or type(args['based_on_event_id']) is not int
          or args['based_on_event_id'] < 0 or type(args['rationale']) is not str
          or not args['rationale'] or args['rationale'] != args['rationale'].strip() or len(args['rationale']) > 512):
        raise ValueError('INVALID_CANDIDATE_ARGUMENTS')


@dataclass(frozen=True)
class Judgment:
    payload_json: str
    choice: str | None
    action_admissible: bool = False

    @property
    def payload(self):
        return json.loads(self.payload_json)


def judgment(problem, bound, payload, *, missing_allowlist=()):
    bound.validate(problem)
    canonical(payload)
    allowed_missing = tuple(identifier(item) for item in missing_allowlist)
    if (len(allowed_missing) > 16 or len(set(allowed_missing)) != len(allowed_missing)
            or len(canonical(payload).encode()) > bound.profile.max_output_bytes):
        raise ValueError('JUDGMENT_LIMIT_EXCEEDED')
    if type(payload) is not dict or set(payload) != set(FIELDS):
        raise ValueError('INVALID_JUDGMENT_FIELDS')
    if (type(payload['schema_version']) is not int or payload['schema_version'] != 2
            or payload['profile_revision'] != bound.profile.profile_revision
            or any(payload[key] != getattr(problem, key) for key in ('subject_id', 'case_id', 'generation'))
            or payload['input_hash'] != problem.digest or payload['verdict'] not in VERDICTS):
        raise ValueError('INVALID_JUDGMENT_BINDING')
    probabilities = payload['alternatives']
    if type(probabilities) is not list or len(probabilities) != len(problem.choices):
        raise ValueError('INVALID_ALTERNATIVES')
    for item in probabilities:
        if (type(item) is not dict or set(item) != {'choice', 'probability'}
                or type(item['choice']) is not str or item['choice'] not in problem.choices
                or type(item['probability']) not in (float, int) or not 0 <= item['probability'] <= 1
                or not math.isfinite(item['probability'])):
            raise ValueError('INVALID_PROBABILITY')
    if (len({item['choice'] for item in probabilities}) != len(problem.choices)
            or abs(math.fsum(item['probability'] for item in probabilities) - 1) > 1e-6):
        raise ValueError('INVALID_PROBABILITY_DISTRIBUTION')
    refs(payload['evidence_ids'], problem.evidence_ids, required=True)
    refs(payload['missing_evidence'], allowed_missing)
    refs(payload['objections'], OBJECTIONS)
    active = payload['verdict'] in ('candidate', 'reobserve')
    if problem.domain == 'fleet_status' and payload['verdict'] == 'candidate':
        raise ValueError('STATUS_CANDIDATE_REFUSED')
    if active:
        if problem.necessity != ('READ_ONLY_QUERY' if problem.domain == 'fleet_status' else 'INTERVENE'):
            raise ValueError('INTERVENTION_NOT_REQUESTED')
        step(problem, payload['next_step'], read_only=payload['verdict'] == 'reobserve')
        proof = payload['success_check']
        if type(proof) is not dict or set(proof) != {'tool_name', 'arguments', 'evidence_ids', 'expected_facts'}:
            raise ValueError('INVALID_DECLARED_SUCCESS_CHECK')
        step(problem, {key: value for key, value in proof.items() if key != 'expected_facts'}, read_only=True)
        replace(problem, choices=('reobserve',), fleet_choice=None, facts_json=canonical(proof['expected_facts']))
    elif payload['next_step'] is not None or payload['success_check'] is not None:
        raise ValueError('INACTIVE_JUDGMENT_HAS_STEP')
    if (payload['verdict'] == 'do_not_intervene' and problem.domain != 'fleet_status'
            and problem.necessity != 'DO_NOT_INTERVENE'):
        raise ValueError('NORMAL_JUDGMENT_CONFLICT')
    top = max(item['probability'] for item in probabilities)
    winners = [item['choice'] for item in probabilities if item['probability'] == top]
    if active and payload['next_step']['tool_name'] == 'propose_lane_back':
        if (payload['verdict'] != 'candidate' or winners != ['back_and_retry']
                or payload['success_check']['tool_name'] != 'get_incident_status'
                or payload['success_check']['expected_facts'] != {'state': 'normal'}):
            raise ValueError('INVALID_RECOVERY_CANDIDATE')
    return Judgment(canonical(payload), winners[0] if active and len(winners) == 1 else None)


def schema_missing_allowlist(schema):
    """The missing-evidence allowlist a received judgment_schema() was built with; rebuild and compare after."""
    return schema['properties']['missing_evidence'].get('items', {}).get('enum', [])


def judgment_schema(problem, bound, *, missing_allowlist=()):
    bound.validate(problem)
    # An empty allowlist is an always-empty array: Ollama refuses `enum: []` with HTTP 400 (D-878).
    array = lambda values: ({'type': 'array', 'items': {'type': 'string', 'enum': list(values)},
                             'uniqueItems': True, 'maxItems': 16} if values else {'type': 'array', 'maxItems': 0})
    properties = {key: {'const': getattr(problem, key)} for key in ('subject_id', 'case_id', 'generation')}
    properties.update(schema_version={'const': 2}, profile_revision={'const': bound.profile.profile_revision},
                      input_hash={'const': problem.digest},
                      verdict={'enum': [v for v in VERDICTS if problem.domain != 'fleet_status' or v != 'candidate']},
                      evidence_ids={**array(problem.evidence_ids), 'minItems': 1},
                      missing_evidence=array(tuple(identifier(v) for v in missing_allowlist)), objections=array(sorted(OBJECTIONS)),
                      alternatives={'type': 'array', 'minItems': len(problem.choices), 'maxItems': len(problem.choices),
                                    'items': {'type': 'object', 'additionalProperties': False,
                                              'required': ['choice', 'probability'], 'properties': {
                                                  'choice': {'enum': list(problem.choices)},
                                                  'probability': {'type': 'number', 'minimum': 0, 'maximum': 1}}}})
    defs, refs_of = {}, {'next_step': [], 'success_check': [], 'read_step': []}
    for field in ('next_step', 'success_check'):
        scope = ('channel' if problem.domain == 'fleet_status' else
                 'incident' if problem.domain in {'line_follow', 'door'} else 'mission')
        for definition in MODEL_TOOL_CATALOG.values():
            if definition.name == 'propose_lane_back' and (problem.domain != 'line_follow' or 'back_and_retry' not in problem.choices):
                continue
            if (definition.scope != scope or not definition.feedback_enabled or definition.device_action_api
                    or (field == 'success_check' or problem.domain == 'fleet_status')
                    and definition.effect_class != ToolEffectClass.READ_ONLY):
                continue
            entry = {'type': 'object', 'additionalProperties': False,
                     'required': ['tool_name', 'arguments', 'evidence_ids'], 'properties': {
                         'tool_name': {'const': definition.name}, 'arguments': definition.parameters,
                         'evidence_ids': {**array(problem.evidence_ids), 'minItems': 1}}}
            if field == 'success_check':
                states = {'fleet_status': ['unknown', 'offline', 'online', 'mixed', 'empty'],
                          'line_follow': ['unknown', 'blocked', 'normal'], 'door': ['unknown', 'open', 'closed'],
                          'arm_target': ['unknown', 'present', 'missing']}[problem.domain]
                fact_keys = ['state'] + ({'door': ['door_state'], 'arm_target': ['target_state']}.get(problem.domain, []))
                entry['required'].append('expected_facts')
                entry['properties']['expected_facts'] = {
                    'type': 'object', 'minProperties': 1, 'additionalProperties': False,
                    'properties': {key: {'type': 'string', 'enum': states} for key in fact_keys}}
            defs[f'{field}.{definition.name}'] = entry
            ref = {'$ref': f'#/$defs/{field}.{definition.name}'}
            refs_of[field].append(ref)
            if field == 'next_step' and definition.effect_class == ToolEffectClass.READ_ONLY:
                refs_of['read_step'].append(ref)
        properties[field] = {'anyOf': [{'type': 'null'}, *refs_of[field]]}
    base = {'type': 'object', 'additionalProperties': False, 'required': list(FIELDS)}
    # Root properties keep the readers' view; the variants carry judgment()'s verdict/step pairing so a
    # constrained decoder cannot emit an acting verdict without its steps (D-878, 2026-10-25 pipeline run).
    # Variants point at root properties and named $defs (llama.cpp resolves object keys, not array indexes),
    # so the job stays inside the 16 KiB canonical budget.
    acting = problem.necessity == ('READ_ONLY_QUERY' if problem.domain == 'fleet_status' else 'INTERVENE')
    resting = [v for v in properties['verdict']['enum'] if v == 'abstain' or v == 'do_not_intervene'
               and (problem.domain == 'fleet_status' or problem.necessity == 'DO_NOT_INTERVENE')]
    variants = [(resting, {'type': 'null'}, {'type': 'null'})]
    checks = {'anyOf': refs_of['success_check']}
    if acting and refs_of['read_step'] and refs_of['success_check']:
        variants.append((['reobserve'], {'anyOf': refs_of['read_step']}, checks))
    if acting and problem.domain != 'fleet_status' and refs_of['next_step'] and refs_of['success_check']:
        variants.append((['candidate'], {'anyOf': refs_of['next_step']}, checks))
    shared = {key: {'$ref': f'#/properties/{key}'} for key in FIELDS}
    return {**base, 'properties': properties, '$defs': defs, 'anyOf': [
        {**base, 'properties': {**shared, 'verdict': {'enum': names}, 'next_step': planned, 'success_check': check}}
        for names, planned, check in variants]}
