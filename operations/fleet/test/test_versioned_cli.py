import asyncio
from dataclasses import replace
import json

import pytest

from rosy.decision.deliberation import canonical
from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation.versioned_cli import VersionedCliProvider
from test_judgment_profiles import adapter, bind_profile, problem, profile
from test_model_judgment import payload


class Transport:
    schema_versions = (2,)
    cost_verified = True

    def __init__(self, capabilities, kind, result, cost=0.01):
        self.adapter_capabilities, self.kind, self.result, self.cost = capabilities, kind, result, cost
        self.calls = []

    async def __call__(self, argv, body, remaining, limit, budget):
        self.calls.append((argv, json.loads(body), remaining, limit, budget))
        if self.kind == 'claude':
            return 0, canonical({'is_error': False, 'structured_output': self.result,
                                 'total_cost_usd': self.cost}).encode()
        return 0, (canonical({'type': 'text', 'part': {'text': canonical(self.result)}}) + '\n'
                   + canonical({'type': 'step_finish', 'part': {'cost': self.cost}})).encode()


def make_cli_provider(kind='claude', **changes):
    p = problem()
    selected = profile(provider_kind=kind, model_id='provider/model', adapter='isolated-cli',
                       max_cost_usd=.1, max_output_bytes=8192, **changes)
    caps = adapter(provider_kind=kind, model_id='provider/model', adapter='isolated-cli')
    bound = bind_profile(p, selected, caps, required_modalities=('text',))
    transport = Transport(caps, kind, payload(p))
    return p, bound, transport, VersionedCliProvider(profile=selected, adapter=caps, launch=transport,
                                                    cli_version='1.18.35')


@pytest.mark.parametrize('kind', ['claude', 'opencode'])
def test_version_two_invokes_fixed_transport_and_validates_bound_json(kind):
    p, bound, transport, provider = make_cli_provider(kind)
    result, cost = asyncio.run(provider(p, bound, (), 2, budget_usd=.05))
    assert result.payload == payload(p) and result.action_admissible is False and cost == .01
    argv, body, remaining, limit, budget = transport.calls[0]
    assert body['schema']['properties']['input_hash']['const'] == p.digest
    assert body['problem']['input_hash'] == p.digest and body['profile_revision'] == 'p1'
    assert (remaining, limit, budget) == (2, 8192, .05)
    if kind == 'claude':
        assert json.loads(argv[argv.index('--json-schema') + 1]) == body['schema']
        assert '--bare' in argv and argv[argv.index('--tools') + 1] == ''
    else:
        assert argv == ('opencode', 'run', '--pure', '--format', 'json', '--model', 'provider/model')


@pytest.mark.parametrize('change', ['legacy', 'unknown_cost', 'wrong_capabilities', 'profile', 'timeout', 'budget'])
def test_not_admitted_transport_or_binding_never_called(change):
    p, bound, transport, provider = make_cli_provider()
    remaining, budget = 2, .05
    if change == 'legacy': transport.schema_versions = (1,)
    elif change == 'unknown_cost': transport.cost_verified = False
    elif change == 'wrong_capabilities': transport.adapter_capabilities = replace(transport.adapter_capabilities, model_revision='other')
    elif change == 'profile': bound = replace(bound, profile=replace(bound.profile, profile_revision='other'))
    elif change == 'timeout': remaining = 31
    else: budget = .2
    with pytest.raises(ValueError):
        asyncio.run(provider(p, bound, (), remaining, budget_usd=budget))
    assert transport.calls == []


def test_valid_prior_is_case_bound_and_malformed_output_cost_not_fallback():
    p, bound, transport, provider = make_cli_provider()
    prior_profile = replace(bound.profile, profile_id='previous-model', profile_revision='prior1')
    prior_bound = replace(bound, profile=prior_profile)
    raw = payload(p)
    raw['profile_revision'] = 'prior1'
    checked_prior = judgment(p, prior_bound, raw)
    asyncio.run(provider(p, bound, ((prior_bound, checked_prior),), 2, budget_usd=.05))
    assert transport.calls[0][1]['prior'][0]['profile_id'] == 'previous-model'
    transport.cost = None
    with pytest.raises(ValueError):
        asyncio.run(provider(p, bound, (), 2, budget_usd=.05))
    transport.cost = .01
    transport.result = {'case_id': 'other'}
    with pytest.raises(ValueError):
        asyncio.run(provider(p, bound, (), 2, budget_usd=.05))


def test_other_case_prior_refuses_without_transport_call():
    p, bound, transport, provider = make_cli_provider()
    other = replace(p, case_id='other')
    other_bound = replace(bound, input_hash=other.digest)
    checked = judgment(other, other_bound, payload(other))
    with pytest.raises(ValueError):
        asyncio.run(provider(p, bound, ((other_bound, checked),), 2, budget_usd=.05))
    assert not transport.calls


def test_versioned_deadline_cancels_a_hanging_transport_without_replay():
    p, bound, transport, provider = make_cli_provider()
    ended = []

    class Hanging(Transport):
        async def __call__(self, *args):
            self.calls.append(args)
            try:
                await asyncio.sleep(1)
                return await super().__call__(*args)
            finally:
                ended.append(True)

    hanging = Hanging(transport.adapter_capabilities, 'claude', payload(p))
    provider.transport.launch = hanging
    with pytest.raises(TimeoutError):
        asyncio.run(provider(p, bound, (), .01, budget_usd=.05))
    assert ended == [True] and len(hanging.calls) == 1
