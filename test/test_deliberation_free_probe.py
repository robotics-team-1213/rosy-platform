import importlib
import json
import asyncio
from contextlib import asynccontextmanager
from contextlib import closing
import threading
import time

import pytest


def subjects():
    return (importlib.import_module('deploy.ai_pc.deliberation_free_codec'),
            importlib.import_module('deploy.ai_pc.deliberation_free_gateway'),
            importlib.import_module('deploy.ai_pc.deliberation_free_probe'))


def payload(codec):
    p = codec.PROBLEM
    return dict(schema_version=2, profile_revision=codec.PROFILE.profile_revision,
        subject_id=p.subject_id, case_id=p.case_id, generation=p.generation, input_hash=p.digest,
        verdict='abstain', alternatives=[dict(choice='human', probability=.5),
                                       dict(choice='reobserve', probability=.5)],
        evidence_ids=list(p.evidence_ids), missing_evidence=[], objections=[],
        next_step=None, success_check=None)


def response(codec):
    return dict(id='synthetic-response', model=codec.MODEL,
        choices=[dict(finish_reason='stop', message=dict(role='assistant', content=json.dumps(payload(codec))))],
        usage=dict(prompt_tokens=2000, completion_tokens=1024, total_tokens=3024,
                   completion_tokens_details=dict(reasoning_tokens=1000)))


def test_fixed_free_config_and_synthetic_v2_no_runtime_admission():
    codec, gate, probe = subjects()
    config = probe.config()
    assert config['model'] == config['small_model'] == 'opencode/mimo-v2.6-flash-free'
    assert config['enabled_providers'] == ['opencode']
    assert 'zai-coding-plan' not in json.dumps(config) and 'openrouter' not in json.dumps(config)
    assert config['permission'] == 'deny' and config['agent']['rosy']['steps'] == 1
    assert config['provider']['opencode']['models'][codec.MODEL]['limit']['output'] == 1024
    assert probe.FreeLauncher.cost_verified is False
    assert gate.UPSTREAM == 'https://opencode.ai/inference/v1/chat/completions'
    assert gate.claim.__module__ == 'deploy.ai_pc.deliberation_smoke_budget'
    from deploy.ai_pc.deliberation_smoke_budget import MARKER
    assert str(MARKER) == '/var/lib/rosy-deliberation/smoke/glm-first-review.spent'
    assert codec.trusted_body(codec.body())[0] == codec.PROBLEM
    checked = codec.checked_response(response(codec))
    assert checked['usage']['completion_tokens'] == 1024


@pytest.mark.parametrize('change', ['subject', 'case', 'schema', 'prior', 'url', 'instruction'])
def test_not_exact_synthetic_job_refused_before_upstream(change):
    codec, _, _ = subjects()
    body = json.loads(codec.body())
    if change == 'subject': body['problem']['subject_id'] = 'real-robot'
    elif change == 'case': body['problem']['case_id'] = 'other'
    elif change == 'schema': body['schema']['additionalProperties'] = True
    elif change == 'prior': body['prior'] = [{}]
    elif change == 'url': body['url'] = 'https://paid.invalid'
    else: body['instruction'] = 'execute tools'
    with pytest.raises(ValueError): codec.trusted_body(json.dumps(body))


@pytest.mark.parametrize('change', ['paid', 'tokens', 'reasoning', 'tool', 'scope', 'length'])
def test_wrong_or_unbounded_free_response_is_hold(change):
    codec, _, _ = subjects()
    data = response(codec)
    if change == 'paid': data['model'] = 'mimo-v2.6-flash'
    elif change == 'tokens': data['usage'].update(completion_tokens=1025, total_tokens=3025)
    elif change == 'reasoning': data['usage']['completion_tokens_details']['reasoning_tokens'] = 1025
    elif change == 'tool': data['choices'][0]['message']['tool_calls'] = [{}]
    elif change == 'length': data['choices'][0]['finish_reason'] = 'length'
    else:
        wrong = payload(codec); wrong['case_id'] = 'foreign'
        data['choices'][0]['message']['content'] = json.dumps(wrong)
    with pytest.raises(ValueError): codec.checked_response(data)


def test_free_upstream_fixed_headers_no_identity_spoof_no_redirect(monkeypatch):
    codec, gate, _ = subjects()
    seen = []
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            assert limit == 16385
            return json.dumps(response(codec)).encode()
    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            assert 0 < timeout <= 30
            return Reply()
    monkeypatch.setattr(gate.urllib.request, 'build_opener', lambda *args: Opener())
    gate.upstream({'model': codec.MODEL}, 'fake-unit-key', 1,
                  {'User-Agent': 'actual-sdk-fixture', 'Authorization': 'untrusted', 'Cookie': 'untrusted'})
    assert len(seen) == 1 and seen[0].full_url == gate.UPSTREAM
    headers = dict((k.lower(), v) for k, v in seen[0].header_items())
    assert headers['authorization'] == 'Bearer fake-unit-key'
    assert headers['user-agent'] == 'actual-sdk-fixture' and 'cookie' not in headers


@pytest.mark.parametrize('change', ['valid', 'paid', 'tool', 'route', '403'])
def test_actual_unix_free_gateway_uses_one_shared_claim_and_holds_refusal(tmp_path, monkeypatch, change):
    codec, gate, _ = subjects()
    from test_deliberation_glm_gateway import Connection
    claims, calls = [], []
    monkeypatch.setattr(gate, 'claim', lambda body: claims.append(body))
    def upstream(body, token, remaining, headers):
        calls.append(body)
        assert body['model'] == codec.MODEL and body['max_tokens'] == 1024 and body['stream'] is False
        assert body['messages'][1]['content'] == codec.body().decode() and 'tools' not in body
        assert headers['User-Agent'] == 'actual-sdk-fixture'
        if change == '403': raise PermissionError('synthetic-refusal')
        return response(codec)
    monkeypatch.setattr(gate, 'upstream', upstream)
    incoming = dict(model=codec.MODEL, messages=[dict(role='user', content='untrusted injection')])
    if change == 'paid': incoming['model'] = 'mimo-v2.6-flash'
    if change == 'tool': incoming['tools'] = [{}]
    path = str(tmp_path / 'gateway.sock')
    with gate.Gateway(path, gate.Handler) as server:
        server.body, server.token = codec.body().decode(), 'fake-unit-key'
        server.deadline, server.calls, server.timeout = time.monotonic() + 30, 0, 2
        worker = threading.Thread(target=server.handle_request, daemon=True); worker.start()
        with closing(Connection(path)) as client:
            try:
                client.request('POST', '/other' if change == 'route' else '/v1/chat/completions',
                               json.dumps(incoming), {'User-Agent': 'actual-sdk-fixture'})
                result = client.getresponse(); result.read(); status = result.status
            except (BrokenPipeError, ConnectionResetError):
                # 'route' is refused on the request line, before the body is read. http.client sends
                # the body after the headers, so a fast refusal can close the socket under that send
                # (CI 2026-10-16: runs 38959095932, 38964287715, 38968030520). Either way it is refused.
                if change != 'route':
                    raise
                status = None  # no response to read; the server-side checks below still hold
        worker.join(4); assert not worker.is_alive()
        count = 1 if change in {'valid', '403'} else 0
        assert len(calls) == len(claims) == server.calls == count
        assert status in ({200} if change == 'valid' else {400, None} if change == 'route' else {400})
        assert server.metrics['cost_usd'] is None and server.metrics['cost_complete'] is False
        assert server.metrics['state'] == ('PASS_FREE_PROVIDER_ONLY' if change == 'valid' else 'HOLD')


@pytest.mark.parametrize('change', ['valid', 'different_sdk', 'cancel', 'malformed', 'paid_args'])
def test_free_launcher_binds_sdk_response_and_cleans_cancellation(monkeypatch, change):
    codec, gate, probe = subjects()
    from deploy.ai_pc.deliberation_glm_receipt import digest
    events = []
    class Sandbox:
        def __init__(self, *args): pass
        def command(self, *args): return ('systemd-run', '--', 'bwrap', '--unshare-all', '--', '/provider')
        def close(self): events.append('close')
    @asynccontextmanager
    async def gateway(body, remaining, directory, *, free):
        assert free is True
        events.append('gateway')
        try: yield object()
        finally: events.append('gateway-cleaned')
    async def bounded(command, body, remaining, limit):
        events.append('cli')
        if change == 'cancel': raise asyncio.CancelledError()
        data = payload(codec)
        if change == 'different_sdk': data['objections'] = ['conflict']
        return 0, (json.dumps(dict(type='text', part=dict(text=json.dumps(data)))) + '\n'
                   + json.dumps(dict(type='step_finish', part=dict(cost=999)))).encode()
    async def finish(process, *, free):
        return dict(state='PASS_FREE_PROVIDER_ONLY', calls=1, job_sha256=digest(json.loads(codec.body())),
            judgment_sha256=digest(payload(codec)), cost_usd=None, cost_complete=False,
            runtime_admitted=False, action_admissible=False)
    async def clean(unit): events.append('scope-cleaned')
    for name, function in (('SandboxLauncher', Sandbox), ('gateway_session', gateway),
                           ('bounded_process', bounded), ('finish_gateway', finish), ('cleanup_scope', clean)):
        monkeypatch.setattr(probe, name, function)
    with probe.FreeLauncher() as launch:
        args = ('opencode', 'run', '--paid') if change == 'paid_args' else probe.ARGV
        body = b'{}' if change == 'malformed' else codec.body()
        if change == 'valid':
            checked, receipt = asyncio.run(launch(args, body, 1, 16384))
            assert checked == payload(codec) and receipt['cost_usd'] is None
        else:
            with pytest.raises(asyncio.CancelledError if change == 'cancel' else ValueError):
                asyncio.run(launch(args, body, 1, 16384))
        if change not in {'malformed', 'paid_args'}:
            with pytest.raises(ValueError, match='ONE_SHOT_ALREADY_USED'):
                asyncio.run(launch(probe.ARGV, codec.body(), 1, 16384))
    assert events == (['close'] if change in {'malformed', 'paid_args'} else
                      ['gateway', 'cli', 'scope-cleaned', 'gateway-cleaned', 'close'])


def test_fixed_synthetic_request_matches_across_hash_seeds():
    import os
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'PYTHONPATH': os.pathsep.join((str(root),
        str(root / 'operations/decision/src'), str(root / 'contracts/foundation')))}
    request = subprocess.run((sys.executable, '-c',
        'from deploy.ai_pc.deliberation_free_codec import body; import sys; sys.stdout.buffer.write(body())'),
        env={**environment, 'PYTHONHASHSEED': '1'}, capture_output=True, check=True, timeout=10).stdout
    for seed in ('2', '3', '4'):
        subprocess.run((sys.executable, '-c',
            'from deploy.ai_pc.deliberation_free_codec import trusted_body; import sys; trusted_body(sys.stdin.buffer.read())'),
            input=request, env={**environment, 'PYTHONHASHSEED': seed},
            capture_output=True, check=True, timeout=10)