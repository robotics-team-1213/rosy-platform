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
    receipt = bridge.receipt(raw, response, credential_sha256='f' * 64)
    receipt.update(state='PASS_GLM_PROVIDER_ONLY', calls=1)
    policy = bridge.TrustedIncludedPlanPolicy('plan-v1', 'a' * 64, 'account-ref',
        'key-ref', receipt['profile_sha256'], time.time() + 60, 'f' * 64)
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
                                  'request_id', 'tokens', 'sdk_scope', 'tool', 'limit', 'credential'])
def test_unknown_or_mismatched_billing_binding_refuses(change):
    bridge, raw, receipt, policy, sdk = setup()
    limit = 16384
    if change == 'none': policy = None
    elif change == 'expired': policy = replace(policy, valid_until=0)
    elif change == 'profile': policy = replace(policy, profile_sha256='b' * 64)
    elif change == 'job': receipt['job_sha256'] = 'b' * 64
    elif change == 'judgment': receipt['judgment_sha256'] = 'b' * 64
    elif change == 'request_id': receipt['provider_request_id'] = ''
    elif change == 'credential': receipt['credential_sha256'] = 'b' * 64
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


@pytest.mark.parametrize('change', ['calibration', 'role', 'timeout', 'revision'])
def test_same_revision_profile_changes_refused_before_sandbox(monkeypatch, change):
    from deploy.ai_pc import deliberation_opencode as module
    bridge, _, _, policy, _ = setup()
    _, bound, _ = fixture()
    changes = {'calibration': {'calibration_revision': 'cal-v2'}, 'role': {'role': 'primary'},
               'timeout': {'timeout_s': 1}, 'revision': {'profile_revision': 'foreign'}}
    profile = replace(bound.profile, **changes[change])
    calls = []
    monkeypatch.setattr(module, 'SandboxLauncher', lambda *args: calls.append(args))
    caps = replace(bridge.CAPABILITIES, ready=True, isolated=True, cost_verified=True)
    with pytest.raises(ValueError):
        module.GlmOpenCodeLauncher(admission=caps, billing_policy=policy, profile=profile)
    assert calls == []


def test_changed_actual_credential_refused_before_ready_marker_and_upstream(tmp_path, monkeypatch, capsys):
    import hashlib
    import io
    from types import SimpleNamespace
    _, _, raw = fixture()
    tmp_path.chmod(0o700)
    job = dict(body=raw.decode(), deadline_s=1, socket_path=str(tmp_path / 'gateway.sock'),
               secret_path=str(gate.CONFIG_PATH),
               credential_sha256=hashlib.sha256(b'approved-fake-A').hexdigest())
    monkeypatch.setattr(gate.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(canonical(job).encode())))
    monkeypatch.setattr(gate, 'read_secret', lambda: 'changed-fake-B')
    calls = []
    monkeypatch.setattr(gate, 'claim', lambda *args: calls.append('claim'))
    monkeypatch.setattr(gate, 'upstream', lambda *args: calls.append('upstream'))
    with pytest.raises(ValueError, match='BILLING_CREDENTIAL_CHANGED'):
        gate.main()
    assert calls == [] and 'READY' not in capsys.readouterr().out
    assert not (tmp_path / 'gateway.sock').exists()


@pytest.mark.parametrize('change', ['valid', 'wrong_runtime', 'expired', 'wrong_sdk', 'cancel'])
def test_actual_versioned_provider_uses_launcher_host_receipt_not_sdk_cost(monkeypatch, change):
    import asyncio
    from contextlib import asynccontextmanager
    from deploy.ai_pc import deliberation_opencode as module
    from rosy.decision.deliberation.versioned_cli import VersionedCliProvider
    bridge, raw, receipt, policy, sdk = setup()
    problem, bound, _ = fixture()
    caps = replace(bridge.CAPABILITIES, ready=True, isolated=True, cost_verified=True)
    if change == 'wrong_runtime': caps = replace(caps, model_revision='foreign')
    if change == 'wrong_sdk': receipt['judgment_sha256'] = 'b' * 64
    events = []
    class Sandbox:
        def __init__(self, *args): pass
        def command(self, *args):
            return ('systemd-run', '--', 'bwrap', '--unshare-all', '--', '/provider')
        def close(self): pass
    @asynccontextmanager
    async def gateway(body, remaining, directory, *, credential_sha256):
        assert body == raw and 0 < remaining <= 1
        assert credential_sha256 == policy.credential_sha256
        events.append('gateway')
        try:
            yield object()
        finally:
            events.append('gateway-cleaned')
    async def bounded(command, body, remaining, limit):
        events.append('cli')
        if change == 'cancel': raise asyncio.CancelledError()
        return 0, sdk
    async def finish(process): return receipt
    async def cleanup(unit): events.append('scope-cleaned')
    for name, value in (('SandboxLauncher', Sandbox), ('gateway_session', gateway),
                        ('bounded_process', bounded), ('finish_gateway', finish), ('cleanup_scope', cleanup)):
        monkeypatch.setattr(module, name, value)
    if change == 'wrong_runtime':
        with pytest.raises(ValueError): module.GlmOpenCodeLauncher(admission=caps, billing_policy=policy,
                                                                  profile=bound.profile)
        assert events == []
        return
    with module.GlmOpenCodeLauncher(admission=caps, billing_policy=policy, profile=bound.profile) as launcher:
        if change == 'expired':
            policy = replace(policy, valid_until=0)
            launcher.billing_policy = policy
        provider = VersionedCliProvider(profile=bound.profile, adapter=caps,
                                       launch=launcher, cli_version='1.18.35')
        if change == 'valid':
            result, cost = asyncio.run(provider(problem, bound, (), 1, budget_usd=0))
            assert result.payload == opinion(problem, bound) and cost == 0
            assert launcher.billing_receipt['observed_usd_charge'] is None
            assert launcher.billing_receipt['job_sha256'] == bridge.digest(json.loads(raw))
        else:
            error = asyncio.CancelledError if change == 'cancel' else ValueError
            with pytest.raises(error):
                asyncio.run(provider(problem, bound, (), 1, budget_usd=0))
        assert launcher.used is (change != 'expired')
        if change != 'expired':
            with pytest.raises(ValueError, match='ONE_SHOT_ALREADY_USED'):
                asyncio.run(provider(problem, bound, (), 1, budget_usd=0))
    assert events == ([] if change == 'expired' else
                      ['gateway', 'cli', 'scope-cleaned', 'gateway-cleaned'])
