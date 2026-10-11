import json
import time
from dataclasses import replace

import pytest

from deploy.ai_pc import deliberation_glm_gateway as gate
from rosy.decision.deliberation import canonical
from test_deliberation_glm_judgment import fixture, opinion


def setup():
    from deploy.ai_pc import deliberation_glm_receipt as bridge
    problem, bound, raw = fixture()
    response = dict(id='response-1', request_id='request-1', model=gate.MODEL,
        choices=[{'finish_reason': 'stop', 'message': {
            'role': 'assistant', 'content': canonical(opinion(problem, bound))}}],
        usage={'prompt_tokens': 2000, 'completion_tokens': 100, 'total_tokens': 2100})
    receipt = bridge.receipt(raw, response)
    policy = bridge.TrustedIncludedPlanPolicy('plan-v1', 'a' * 64, 'account-ref',
        'key-ref', receipt['profile_sha256'], time.time() + 60)
    sdk = (canonical({'type': 'text', 'part': {'text': canonical(opinion(problem, bound))}})
           + '\n' + canonical({'type': 'step_finish', 'part': {'cost': 999}})).encode()
    return bridge, raw, receipt, policy, sdk


def test_verified_plan_basis_is_distinct_from_observed_charge_and_sdk_cost():
    bridge, raw, receipt, policy, sdk = setup()
    normalized, billing = bridge.normalize(raw, sdk, receipt, policy, 16384, 0)
    assert json.loads(normalized.splitlines()[-1])['part']['cost'] == 0
    assert billing['basis'] == 'vendor_included_plan' and billing['marginal_cash_usd'] == 0
    assert billing['observed_usd_charge'] is None
    assert billing['provider_request_id'] == 'request-1'
    assert receipt['cost_status'] == 'UNKNOWN'


@pytest.mark.parametrize('change', ['none', 'expired', 'profile', 'job', 'judgment',
                                  'request_id', 'tokens', 'sdk_scope', 'tool', 'limit'])
def test_unknown_or_mismatched_billing_binding_refuses(change):
    bridge, raw, receipt, policy, sdk = setup()
    limit = 16384
    if change == 'none': policy = None
    elif change == 'expired': policy = replace(policy, valid_until=0)
    elif change == 'profile': policy = replace(policy, profile_sha256='b' * 64)
    elif change == 'job': receipt['job_sha256'] = 'b' * 64
    elif change == 'judgment': receipt['judgment_sha256'] = 'b' * 64
    elif change == 'request_id': receipt['provider_request_id'] = ''
    elif change == 'tokens': receipt['usage'].update(completion_tokens=1025, total_tokens=3025)
    elif change == 'sdk_scope':
        records = [json.loads(line) for line in sdk.splitlines()]
        value = json.loads(records[0]['part']['text'])
        value['case_id'] = 'foreign'
        records[0]['part']['text'] = canonical(value)
        sdk = '\n'.join(canonical(record) for record in records).encode()
    elif change == 'tool': sdk += b'\n{"type":"tool_use"}'
    else: limit = 10
    with pytest.raises((ValueError, KeyError, TypeError)):
        bridge.normalize(raw, sdk, receipt, policy, limit, 0)


def test_versioned_launcher_default_admission_refuses_before_gateway(monkeypatch):
    import asyncio
    from deploy.ai_pc import deliberation_opencode as module
    class Sandbox:
        def __init__(self, *args): pass
        def close(self): pass
    monkeypatch.setattr(module, 'SandboxLauncher', Sandbox)
    _, _, raw = fixture()
    with module.GlmOpenCodeLauncher() as launcher:
        assert launcher.cost_verified is False and launcher.adapter_capabilities.isolated is False
        with pytest.raises(ValueError):
            asyncio.run(launcher(module.ARGV, raw, 1, 16384, 0))
        assert launcher.used is False
