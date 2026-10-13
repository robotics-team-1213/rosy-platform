import asyncio
from dataclasses import asdict
import hashlib
import json

import pytest

from rosy.decision.deliberation import canonical
from rosy.decision.deliberation.contracts.billing import CostEvidence, CallResult, usd
from rosy.decision.deliberation.providers.versioned_request import prepare_request
from test_versioned_cli import make_cli_provider


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


def host_receipt(p, bound, body, payload):
    return dict(basis='vendor_included_plan', policy_basis='https://vendor.example.test/policy',
        policy_revision='included-v1', evidence_sha256='a' * 64, account_ref='PRIVATE_ACCOUNT',
        key_ref='PRIVATE_KEY_REF', endpoint='https://vendor.example.test/coding',
        marginal_cash_usd=0.0, observed_usd_charge=None, schema_version=2,
        job_sha256=digest(json.loads(body)), profile_sha256=digest(asdict(bound.profile)),
        judgment_sha256=digest(payload), provider_response_id='response-1', provider_request_id='request-1',
        credential_sha256='b' * 64, usage=dict(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        cost_status='UNKNOWN', state='PASS_GLM_PROVIDER_ONLY', calls=1)


@pytest.mark.parametrize('fault', [None, 'job_sha256', 'profile_sha256', 'judgment_sha256', 'marginal_cash_usd'])
def test_cli_attaches_call_bound_cost_evidence_without_losing_known_cost(fault):
    p, bound, transport, provider = make_cli_provider('opencode')
    transport.cost = 0.0
    original = transport.__class__.__call__
    class BillingTransport(transport.__class__):
        async def __call__(self, argv, body, *args):
            result = await original(self, argv, body, *args)
            self.billing_receipt = host_receipt(p, bound, body, self.result)
            if fault: self.billing_receipt[fault] = .01 if fault == 'marginal_cash_usd' else 'c' * 64
            return result
    billing = BillingTransport(transport.adapter_capabilities, transport.kind, transport.result, 0.0)
    provider.transport.launch = billing
    result = asyncio.run(provider(p, bound, (), 2, budget_usd=.05))
    assert type(result) is CallResult and len(result) == 2
    checked, cost = result
    assert checked.payload == transport.result and cost == 0.0
    if fault:
        assert result.evidence_error and result.cost_evidence is None
    else:
        value = result.cost_evidence.payload
        assert value['observed_usd_charge'] is None and value['marginal_cash_usd'] == 0
        assert value['usage']['total_tokens'] == 30
        assert not any(text in result.cost_evidence.payload_json for text in ('PRIVATE_', 'account_ref', 'key_ref', 'endpoint'))
        _, body = prepare_request(p, bound, (), 2, budget_usd=.05)
        result.cost_evidence.validate(p, bound, checked, cost, body=body)


def test_legacy_cli_call_still_returns_tuple_two_without_cost_metadata():
    p, bound, _, provider = make_cli_provider()
    result = asyncio.run(provider(p, bound, (), 2, budget_usd=.05))
    assert type(result) is tuple and len(result) == 2


@pytest.mark.parametrize('amount', [10 ** 1000, True, float('nan'), float('inf'), -1])
def test_invalid_amounts_fail_with_value_error_including_huge_integer(amount):
    with pytest.raises(ValueError): usd(amount)


@pytest.mark.parametrize('raw', ['{', 'null', '[]', '{"schema":true}'])
def test_malformed_cost_json_fails_with_value_error(raw):
    with pytest.raises(ValueError): CostEvidence(raw)
