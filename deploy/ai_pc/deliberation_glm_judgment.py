"""Fixed v2 codec; profile identity describes routing, never runtime admission."""
import json

from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.judgment import judgment, judgment_schema
from rosy.decision.deliberation.profiles import BoundProfile, ModelProfile
from rosy.decision.deliberation.versioned_request import prepare_request
from .deliberation_ollama import model_profile as primary_profile

FIELDS = {'problem', 'profile_revision', 'schema', 'prior', 'instruction'}
LIMIT = 16384


def model_profile(revision):
    return ModelProfile('glm-reviewer', revision, 'reviewer', 'opencode',
        'zai-coding-plan/glm-5.3-flash', 'glm-5.3-flash', 'opencode-1.18.35-json-v2',
        ('line_follow', 'door', 'arm_target'), ('text',), 30, LIMIT, 1, 10)


def request(data):
    if (type(data) is not dict or set(data) != FIELDS or type(data['prior']) is not list
            or len(data['prior']) > 1 or len(canonical(data).encode()) > LIMIT):
        raise ValueError('INVALID_VERSIONED_GLM_JOB')
    fields = dict(data['problem'])
    digest = fields.pop('input_hash')
    problem = Problem(**fields)
    if digest != problem.digest:
        raise ValueError('INVALID_VERSIONED_GLM_BINDING')
    bound = BoundProfile(model_profile(data['profile_revision']), problem.digest)
    missing = data['schema']['properties']['missing_evidence']['items']['enum']
    if type(missing) is not list or len(missing) > 16 or len(set(missing)) != len(missing):
        raise ValueError('INVALID_VERSIONED_GLM_SCHEMA')
    schema = judgment_schema(problem, bound, missing_allowlist=missing)
    if canonical(schema) != canonical(data['schema']):
        raise ValueError('INVALID_VERSIONED_GLM_SCHEMA')
    pairs = []
    for item in data['prior']:
        payload = dict(item)
        profile_id = payload.pop('profile_id')
        previous = BoundProfile(primary_profile(payload['profile_revision']), problem.digest)
        checked = judgment(problem, previous, payload, missing_allowlist=missing)
        if (profile_id != previous.profile.profile_id or problem.fleet_choice is None
                or checked.choice is None or checked.choice == problem.fleet_choice
                or 'unsafe' in checked.payload['objections']):
            raise ValueError('INVALID_VERSIONED_GLM_PRIOR')
        pairs.append((previous, checked))
    _, raw = prepare_request(problem, bound, pairs, 30, budget_usd=0,
                             missing_allowlist=missing)
    if canonical(json.loads(raw)) != canonical(data):
        raise ValueError('INVALID_VERSIONED_GLM_JOB')
    return problem, bound, tuple(missing), raw.decode()


def result(problem, body, payload):
    current, bound, missing, _ = request(json.loads(body))
    if current != problem:
        raise ValueError('INVALID_VERSIONED_GLM_BINDING')
    return judgment(problem, bound, payload, missing_allowlist=missing).payload
