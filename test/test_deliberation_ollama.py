import json
from dataclasses import asdict

import pytest

from deploy.ai_pc import deliberation_ollama as ollama
from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.judgment import judgment_schema
from rosy.decision.deliberation.profiles import BoundProfile


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
    assert asyncio.run(ollama.OllamaTransport()(b'{}', 1, 123)) == (0, b'{}')
    argv, raw, remaining, limit = seen[0]
    assert argv[1] == '-c' and argv[-1] == '1' and raw == b'{}' and limit == 123
