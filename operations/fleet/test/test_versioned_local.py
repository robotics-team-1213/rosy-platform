import asyncio
import json
from dataclasses import replace

import pytest

from rosy.decision.deliberation.local import VersionedLocalProvider
from rosy.decision.deliberation.profiles import bind_profile
from test_judgment_profiles import adapter, problem, profile
from test_model_judgment import payload


def local_provider(change=None):
    selected, descriptor = profile(), adapter()
    seen = []
    async def launch(body, remaining, limit):
        seen.append(json.loads(body))
        result = dict(model_id=selected.model_id, model_revision=selected.model_revision, cost_usd=0.0,
                      usage={'input_tokens': 10, 'output_tokens': 20}, judgment=payload(problem()))
        if change == 'model': result['model_id'] = 'cloud'
        if change == 'revision': result['model_revision'] = 'new'
        if change == 'cost': result['cost_usd'] = .01
        if change == 'usage': result['usage']['output_tokens'] = True
        if change == 'scope': result['judgment']['case_id'] = 'another'
        if change == 'oversize': return 0, b'x' * (limit + 1)
        if change == 'failed': return 1, b'{}'
        return 0, json.dumps(result).encode()
    launch.adapter_capabilities = descriptor
    launch.schema_versions = (2,)
    launch.cost_verified = True
    return VersionedLocalProvider(profile=selected, adapter=descriptor, launch=launch), seen


def test_generic_local_provider_consumes_shared_v2_renderer_and_parser():
    provider, seen = local_provider()
    bound = bind_profile(problem(), provider.profile, provider.adapter, required_modalities=('text',))
    checked, cost = asyncio.run(provider(problem(), bound, (), 1, budget_usd=0))
    assert checked.choice == 'reobserve' and checked.action_admissible is False and cost == 0
    assert seen[0]['schema']['properties']['schema_version'] == {'const': 2}
    assert seen[0]['problem']['input_hash'] == problem().digest


@pytest.mark.parametrize('change', ['model', 'revision', 'cost', 'usage', 'scope', 'oversize', 'failed'])
def test_unknown_result_or_cost_is_not_free_accepted_judgment(change):
    provider, _ = local_provider(change)
    bound = bind_profile(problem(), provider.profile, provider.adapter, required_modalities=('text',))
    with pytest.raises(ValueError):
        asyncio.run(provider(problem(), bound, (), 1, budget_usd=0))


@pytest.mark.parametrize('change', ['descriptor', 'schema', 'cost_verified', 'scope'])
def test_unadmitted_transport_never_called(change):
    provider, seen = local_provider()
    bound = bind_profile(problem(), provider.profile, provider.adapter, required_modalities=('text',))
    if change == 'descriptor': provider.launch.adapter_capabilities = replace(provider.adapter, isolated=False)
    if change == 'schema': provider.launch.schema_versions = (1,)
    if change == 'cost_verified': provider.launch.cost_verified = False
    target = replace(problem(), generation='changed') if change == 'scope' else problem()
    with pytest.raises(ValueError):
        asyncio.run(provider(target, bound, (), 1, budget_usd=0))
    assert seen == []


def test_cloud_profile_is_never_local_cost_verified():
    with pytest.raises(ValueError):
        VersionedLocalProvider(profile=profile(provider_kind='http'), adapter=adapter(provider_kind='http'),
                               launch=lambda: None)
