import json
from dataclasses import asdict, replace

import pytest

from deploy.ai_pc import deliberation_ollama as ollama
from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.judgment import judgment_schema
from rosy.decision.deliberation.profiles import BoundProfile


@pytest.mark.parametrize('error,kind', [
    (TimeoutError('private-detail'), 'TIMEOUT'),
    (OSError('private-detail'), 'TRANSPORT'),
    (ValueError('private-detail'), 'VALIDATION'),
    (RuntimeError('private-detail'), 'INTERNAL'),
])
def test_cli_failure_is_diagnostic_without_raw_error_or_retry(monkeypatch, capsys, error, kind):
    from io import BytesIO
    from types import SimpleNamespace
    calls = []
    def fail(raw, remaining):
        calls.append((raw, remaining))
        raise error
    monkeypatch.setattr(ollama, 'execute', fail)
    monkeypatch.setattr(ollama.sys, 'argv', ['ollama', '1'])
    monkeypatch.setattr(ollama.sys, 'stdin', SimpleNamespace(buffer=BytesIO(b'{}')))
    monkeypatch.setattr(ollama.signal, 'signal', lambda *args: None)
    timers = []
    monkeypatch.setattr(ollama.signal, 'setitimer', lambda *args: timers.append(args))
    assert ollama.main() == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {'state': 'HOLD', 'reason': 'LOCAL_PROVIDER_FAILED', 'failure_kind': kind}
    assert output.err == '' and 'private-detail' not in output.out
    assert calls == [(b'{}', 1.0)]
    assert timers == [(ollama.signal.ITIMER_REAL, 1.0), (ollama.signal.ITIMER_REAL, 0)]


def test_cli_success_releases_timer_and_restores_handler(monkeypatch, capsys):
    from io import BytesIO
    from types import SimpleNamespace
    handlers, timers = [], []
    previous = object()
    monkeypatch.setattr(ollama, 'execute', lambda *args: {'checked': True})
    monkeypatch.setattr(ollama.sys, 'argv', ['ollama', '1'])
    monkeypatch.setattr(ollama.sys, 'stdin', SimpleNamespace(buffer=BytesIO(b'{}')))
    monkeypatch.setattr(ollama.signal, 'getsignal', lambda *args: previous)
    monkeypatch.setattr(ollama.signal, 'signal', lambda *args: handlers.append(args))
    monkeypatch.setattr(ollama.signal, 'setitimer', lambda *args: timers.append(args))
    assert ollama.main() == 0
    assert json.loads(capsys.readouterr().out) == {'checked': True}
    assert timers == [(ollama.signal.ITIMER_REAL, 1.0), (ollama.signal.ITIMER_REAL, 0)]
    assert handlers[-1] == (ollama.signal.SIGALRM, previous)


def body():
    problem = Problem('synthetic', 'case', 'g1', 'line_follow', 1, ('e1',),
                      ('human', 'reobserve'), 'INTERVENE')
    profile = ollama.model_profile('p1')
    bound = BoundProfile(profile, problem.digest)
    return canonical({'problem': {**asdict(problem), 'input_hash': problem.digest},
                      'profile_revision': 'p1', 'schema': judgment_schema(problem, bound),
                      'prior': [], 'instruction': 'Return only schema version 2 advisory JSON. '
                      'Never use tools or claim verified physical success or calibration.'}).encode()


def response():
    p = json.loads(body())['problem']
    payload = dict(schema_version=2, profile_revision='p1', subject_id=p['subject_id'], case_id=p['case_id'],
                   generation=p['generation'], input_hash=p['input_hash'], verdict='abstain',
                   alternatives=[{'choice': 'human', 'probability': .5}, {'choice': 'reobserve', 'probability': .5}],
                   evidence_ids=['e1'], missing_evidence=[], objections=['insufficient_evidence'],
                   next_step=None, success_check=None)
    return {'model': ollama.MODEL, 'done': True, 'done_reason': 'stop', 'message': {
        'role': 'assistant', 'content': canonical(payload)}, 'prompt_eval_count': 100, 'eval_count': 50}


@pytest.mark.parametrize('change', ['none', 'pre_digest', 'post_digest', 'length', 'tools', 'cloud', 'tokens', 'scope'])
def test_fixed_local_readback_and_only_bounded_request(monkeypatch, change):
    seen = []
    def exchange(path, data, remaining):
        seen.append((path, data))
        assert 0 < remaining <= 30
        if path == '/api/ps':
            digest = ollama.DIGEST
            if change == 'pre_digest' or change == 'post_digest' and len(seen) == 3:
                digest = 'different'
            return {'models': [{'name': ollama.MODEL, 'model': ollama.MODEL, 'digest': digest,
                                'context_length': 8192}]}
        result = response()
        if change == 'length': result['done_reason'] = 'length'
        if change == 'tools': result['message']['tool_calls'] = [{}]
        if change == 'cloud': result['model'] = 'cloud-model'
        if change == 'tokens': result['eval_count'] = 1025
        if change == 'scope':
            payload = json.loads(result['message']['content'])
            payload['case_id'] = 'other'
            result['message']['content'] = canonical(payload)
        return result
    monkeypatch.setattr(ollama, 'exchange', exchange)
    if change == 'none':
        result = ollama.execute(body(), 30)
        assert result['cost_usd'] == 0 and result['usage']['output_tokens'] == 50
        assert result['judgment']['verdict'] == 'abstain'
    else:
        with pytest.raises(ValueError):
            ollama.execute(body(), 30)
    assert seen[0][0] == '/api/ps'
    if change == 'pre_digest':
        assert len(seen) == 1
    else:
        assert [item[0] for item in seen] == ['/api/ps', '/api/chat', '/api/ps']
        request = seen[1][1]
        assert len(canonical(request).encode()) <= 16384
        assert request['model'] == ollama.MODEL and request['stream'] is False
        assert request['options']['num_predict'] == 1024 and 'tools' not in request and 'think' not in request


def test_wrong_schema_refuses_before_http(monkeypatch):
    raw = json.loads(body())
    raw['schema']['properties']['input_hash'] = {'const': 'injected'}
    monkeypatch.setattr(ollama, 'exchange', lambda *args: pytest.fail('no HTTP admission'))
    with pytest.raises(ValueError):
        ollama.execute(canonical(raw).encode(), 1)


def test_exchange_uses_fixed_loopback_no_auth_and_bounded_reader(monkeypatch):
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            assert limit == 16385
            return b'{}'
    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            assert timeout == 1
            return Response()
    monkeypatch.setattr(ollama.urllib.request, 'build_opener', lambda *args: Opener())
    ollama.exchange('/api/ps', None, 1)
    assert seen[0].full_url == 'http://127.0.0.1:11434/api/ps'
    assert seen[0].get_header('Authorization') is None
    with pytest.raises(ValueError):
        ollama.exchange('https://other.invalid', None, 1)
    with pytest.raises(ValueError):
        ollama.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid')


def test_transport_uses_bounded_subprocess_not_thread(monkeypatch):
    import asyncio
    seen = []
    async def bounded(argv, raw, remaining, limit):
        seen.append((argv, raw, remaining, limit))
        return 0, b'{}'
    monkeypatch.setattr(ollama, 'bounded_process', bounded)
    monkeypatch.setattr(ollama.sys, 'executable', '/opt/unit-venv/bin/python')
    admitted = replace(ollama.CAPABILITIES, ready=True, isolated=True, cost_verified=True)
    transport = ollama.OllamaTransport(admission=admitted)
    assert asyncio.run(transport(b'{}', 1, 123)) == (0, b'{}')
    argv, raw, remaining, limit = seen[0]
    assert argv[0] == '/opt/unit-venv/bin/python' and argv[1] == '-c'
    assert argv[-1] == '1' and raw == b'{}' and limit == 123


def test_default_transport_is_not_runtime_admitted_before_launch(monkeypatch):
    import asyncio
    async def forbidden(*args):
        pytest.fail('source must not certify runtime admission')
    monkeypatch.setattr(ollama, 'bounded_process', forbidden)
    transport = ollama.OllamaTransport()
    assert not transport.adapter_capabilities.ready and not transport.adapter_capabilities.isolated
    assert transport.cost_verified is False
    with pytest.raises(ValueError, match='RUNTIME_NOT_ADMITTED'):
        asyncio.run(transport(b'{}', 1, 100))


@pytest.mark.parametrize('change', [dict(model_id='other'), dict(model_revision='changed'),
                                  dict(adapter='other'), dict(modalities=('image',)),
                                  dict(schema_version=1), dict(provider_kind='http')])
def test_explicit_admission_must_match_fixed_backend(change):
    descriptor = replace(ollama.CAPABILITIES, ready=True, isolated=True, cost_verified=True, **change)
    with pytest.raises(ValueError, match='BACKEND_MISMATCH'):
        ollama.OllamaTransport(admission=descriptor)
