"""Shared versioned request codec. Transport admission remains with each provider."""
from dataclasses import asdict
import math

from .. import canonical
from ..contracts.judgment import Judgment, judgment, judgment_schema
from ..contracts.profiles import BoundProfile


def prepare_request(problem, bound, prior, remaining, *, budget_usd, missing_allowlist=()):
    if type(bound) is not BoundProfile:
        raise ValueError('EXPLICIT_BOUND_PROFILE_REQUIRED')
    bound.validate(problem)
    if (type(remaining) not in (int, float) or not math.isfinite(remaining)
            or not 0 < remaining <= bound.profile.timeout_s
            or type(budget_usd) not in (int, float) or not math.isfinite(budget_usd)
            or not 0 <= budget_usd <= bound.profile.max_cost_usd
            or type(prior) not in (tuple, list) or len(prior) > 2):
        raise ValueError('INVALID_VERSIONED_CALL_BUDGET')
    checked_prior = []
    for pair in prior:
        if (type(pair) not in (tuple, list) or len(pair) != 2
                or type(pair[0]) is not BoundProfile or type(pair[1]) is not Judgment):
            raise ValueError('INVALID_VERSIONED_PRIOR')
        previous, checked = pair
        previous.validate(problem)
        verified = judgment(problem, previous, checked.payload, missing_allowlist=missing_allowlist)
        checked_prior.append({'profile_id': previous.profile.profile_id, **verified.payload})
    if len({item['profile_id'] for item in checked_prior}) != len(checked_prior):
        raise ValueError('INVALID_VERSIONED_PRIOR')
    schema = judgment_schema(problem, bound, missing_allowlist=missing_allowlist)
    body = canonical({'problem': {**asdict(problem), 'input_hash': problem.digest},
                      'profile_revision': bound.profile.profile_revision, 'schema': schema,
                      'prior': checked_prior, 'instruction': 'Return only schema version 2 advisory JSON. '
                      'Never use tools or claim verified physical success or calibration.'}).encode()
    return schema, body
