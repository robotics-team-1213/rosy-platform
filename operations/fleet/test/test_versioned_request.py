from dataclasses import replace
import json

import pytest

from rosy.decision.deliberation.versioned_request import prepare_request
from test_judgment_profiles import adapter, bind_profile, problem, profile


def test_local_zero_cost_request_reuses_exact_scoped_versioned_schema():
    p = problem()
    bound = bind_profile(p, profile(), adapter(), required_modalities=('text',))
    schema, raw = prepare_request(p, bound, (), 1, budget_usd=0)
    body = json.loads(raw)
    assert set(body) == {'problem', 'profile_revision', 'schema', 'prior', 'instruction'}
    assert body['schema'] == schema and body['problem']['input_hash'] == p.digest
    assert body['profile_revision'] == bound.profile.profile_revision
    assert body['prior'] == []


@pytest.mark.parametrize('change', ['changed', 'time', 'cost', 'invalid_prior'])
def test_shared_renderer_rejects_scope_budget_or_unvalidated_prior(change):
    p = problem()
    bound = bind_profile(p, profile(), adapter(), required_modalities=('text',))
    prior, timeout, cost = (), 1, 0
    if change == 'changed': p = replace(p, generation='next')
    elif change == 'time': timeout = True
    elif change == 'cost': cost = 1
    else: prior = ({'case_id': p.case_id},)
    with pytest.raises(ValueError):
        prepare_request(p, bound, prior, timeout, budget_usd=cost)
