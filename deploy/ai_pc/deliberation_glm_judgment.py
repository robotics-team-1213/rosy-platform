"""Fixed v2 codec; profile identity describes routing, never runtime admission."""
import json
from dataclasses import replace

from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.judgment import judgment, judgment_schema, schema_missing_allowlist
from rosy.decision.deliberation.profiles import BoundProfile, ModelProfile
from rosy.decision.deliberation.versioned_request import prepare_request
from .deliberation_ollama import model_profile as primary_profile
from .deliberation_ollama import status_model_profile as status_primary_profile

FIELDS = {'problem', 'profile_revision', 'schema', 'prior', 'instruction'}
LIMIT = 16384


def model_profile(revision):
    return ModelProfile('glm-reviewer', revision, 'reviewer', 'opencode',
        'zai-coding-plan/glm-5.3-flash', 'glm-5.3-flash', 'opencode-1.18.35-json-v2',
        ('line_follow', 'door', 'arm_target'), ('text',), 30, LIMIT, 1, 10)


def status_model_profile(revision):
    return replace(model_profile(revision), profile_id='glm-status-reviewer',
                   adapter='opencode-1.18.35-status-json-v2', domains=('fleet_status',))


def request(data):
    if (type(data) is not dict or set(data) != FIELDS or type(data['prior']) is not list
            or len(data['prior']) > 1 or len(canonical(data).encode()) > LIMIT):
        raise ValueError('INVALID_VERSIONED_GLM_JOB')
    fields = dict(data['problem'])
    digest = fields.pop('input_hash')
    problem = Problem(**fields)
    if digest != problem.digest:
        raise ValueError('INVALID_VERSIONED_GLM_BINDING')
    bound = BoundProfile((status_model_profile if problem.domain == 'fleet_status' else model_profile)(
        data['profile_revision']), problem.digest)
    missing = schema_missing_allowlist(data['schema'])
    if type(missing) is not list or len(missing) > 16 or len(set(missing)) != len(missing):
        raise ValueError('INVALID_VERSIONED_GLM_SCHEMA')
    schema = judgment_schema(problem, bound, missing_allowlist=missing)
    if canonical(schema) != canonical(data['schema']):
        raise ValueError('INVALID_VERSIONED_GLM_SCHEMA')
    pairs = []
    for item in data['prior']:
        payload = dict(item)
        profile_id = payload.pop('profile_id')
        previous = BoundProfile((status_primary_profile if problem.domain == 'fleet_status' else primary_profile)(
            payload['profile_revision']), problem.digest)
        checked = judgment(problem, previous, payload, missing_allowlist=missing)
        # Fleet owns review admission; a bound primary can also need calibration review.
        if (profile_id != previous.profile.profile_id or checked.choice is None
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
