import http.client
import json
import os
from pathlib import Path
import socket
import threading
import time
from dataclasses import asdict
from dataclasses import replace
from contextlib import closing

import pytest

from deploy.ai_pc import deliberation_glm_gateway as gate
from rosy.decision.deliberation import Problem


def problem():
    return Problem('synthetic', 'case-1', 'g1', 'line_follow', 1,
                   ('e1',), ('human', 'reobserve'), 'INTERVENE')


def reply():
    p = problem()
    return dict(subject_id=p.subject_id, case_id=p.case_id, generation=p.generation,
                input_hash=p.digest, choice='human', evidence_ids=['e1'], objections=[])


def response():
    return {'model': gate.MODEL,
            'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(reply())}}],
            'usage': {'completion_tokens': 100, 'prompt_tokens': 90, 'total_tokens': 190}}


def test_trusted_payload_requires_current_hash_and_no_prior():
    p = problem()
    body = {'problem': {**asdict(p), 'input_hash': p.digest}, 'prior': [], 'instruction': 'test'}
    assert gate.trusted_body(json.dumps(body))[0] == p
    body['problem']['input_hash'] = 'wrong'
    with pytest.raises(ValueError):
        gate.trusted_body(json.dumps(body))


def test_legacy_job_does_not_require_versioned_codec(monkeypatch):
    import builtins
    original = builtins.__import__
    def restricted(name, globals=None, locals=None, fromlist=(), level=0):
        if 'deliberation_glm_judgment' in fromlist:
            raise ImportError('Versioned deployment absent')
        return original(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, '__import__', restricted)
    p = problem()
    raw = json.dumps({'problem': {**asdict(p), 'input_hash': p.digest},
                      'prior': [], 'instruction': 'test'})
    parsed, body = gate.trusted_body(raw)
    assert parsed == p
    assert gate.checked_response(p, response(), body=body)['usage']['completion_tokens'] == 100


@pytest.mark.parametrize('change', ['tool', 'length', 'tokens', 'scope', 'model', 'missing_model', 'role'])
def test_invalid_upstream_never_admitted(change):
    data = response()
    if change == 'tool':
        data['choices'][0]['message']['tool_calls'] = [{}]
    elif change == 'length':
        data['choices'][0]['finish_reason'] = 'length'
    elif change == 'tokens':
        data['usage']['completion_tokens'] = 1025
    elif change == 'model':
        data['model'] = 'other'
    elif change == 'missing_model':
        data.pop('model')
    elif change == 'role':
        data['choices'][0]['message']['role'] = 'user'
    else:
        data['choices'][0]['message']['content'] = json.dumps({**reply(), 'case_id': 'other'})
    with pytest.raises(ValueError):
        gate.checked_response(problem(), data)


def test_secret_rejects_mode_symlink_and_wrong_schema(tmp_path, monkeypatch):
    path = tmp_path / 'secret'
    monkeypatch.setattr(gate, 'CONFIG_PATH', path)
    path.write_text('{"type":"api","key":"fake-unit-token"}')
    path.chmod(0o600)
    assert gate.read_secret() == 'fake-unit-token'
    path.chmod(0o644)
    with pytest.raises(ValueError):
        gate.read_secret()
    path.unlink()
    path.symlink_to(tmp_path / 'other')
    with pytest.raises(OSError):
        gate.read_secret()


class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(3)
        self.sock.connect(self.host)


@pytest.mark.parametrize('change', ['valid', 'stream', 'model', 'tool', 'history', 'route', 'oversize'])
@pytest.mark.parametrize('schema_version', [1, 2])
def test_gateway_reconstructs_only_trusted_job_and_one_call(tmp_path, monkeypatch, change, schema_version):
    seen = []
    monkeypatch.setattr(gate, 'claim', lambda body: None)
    answer = response()
    p = problem()
    body = json.dumps({'problem': {**asdict(p), 'input_hash': p.digest},
                       'prior': [], 'instruction': 'test'})
    if schema_version == 2:
        from test_deliberation_glm_judgment import fixture, opinion
        p, bound, body = fixture(prior=True)
        body = body.decode()
        answer['choices'][0]['message']['content'] = json.dumps(opinion(p, bound))
        answer.update(id='response-1', request_id='request-1')
    def upstream(body, token, remaining):
        seen.append(body)
        assert token == 'fake-unit-token' and 0 < remaining <= 30
        return answer
    monkeypatch.setattr(gate, 'upstream', upstream)
    path = str(tmp_path / 'gateway.sock')
    incoming = {'model': gate.MODEL, 'messages': [{'role': 'user', 'content': 'untrusted injected text'}]}
    route = '/v1/chat/completions'
    if change == 'stream': incoming['stream'] = True
    if change == 'model': incoming['model'] = 'other'
    if change == 'tool': incoming['tools'] = [{}]
    if change == 'history': incoming['messages'][0]['role'] = 'tool'
    if change == 'route': route = '/arbitrary'
    raw = json.dumps(incoming).encode() if change != 'oversize' else b'x' * 16385
    with gate.Gateway(path, gate.Handler) as server:
        server.timeout = 2
        server.problem, server.body, server.token = p, body, 'fake-unit-token'
        server.credential_sha256 = 'f' * 64
        server.deadline, server.calls = time.monotonic() + 30, 0
        server.metrics = {}
        worker = threading.Thread(target=server.handle_request, daemon=True)
        worker.start()
        result = None
        try:
            with closing(Connection(path)) as conn:
                conn.request('POST', route, raw, {'Content-Type': 'application/json'})
                result = conn.getresponse()
                output = result.read()
        except (BrokenPipeError, ConnectionResetError, http.client.RemoteDisconnected):
            if change not in {'route', 'oversize'}:
                raise
            # Header rejection may close before the refused body is transmitted.
        worker.join(4)
        assert not worker.is_alive()
        if change in {'valid', 'stream'}:
            assert result.status == 200 and len(seen) == server.calls == 1
            assert seen[0]['messages'][1]['content'] == body
            assert seen[0]['max_tokens'] == 1024 and seen[0]['stream'] is False
            assert 'tools' not in seen[0]
            assert b'[DONE]' in output if change == 'stream' else json.loads(output)['usage']
            worker = threading.Thread(target=server.handle_request, daemon=True)
            worker.start()
            try:
                with closing(Connection(path)) as conn:
                    conn.request('POST', '/v1/chat/completions', json.dumps(incoming))
                    denied = conn.getresponse()
                    denied.read()
                    assert denied.status == 400
            except (BrokenPipeError, ConnectionResetError, http.client.RemoteDisconnected):
                pass  # Replay may close before its refused body is transmitted.
            worker.join(4)
            assert not worker.is_alive() and len(seen) == server.calls == 1
        else:
            assert (result is None or result.status == 400) and seen == [] and server.calls == 0


def test_upstream_fixed_tls_and_no_redirects(monkeypatch):
    seen = []
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            assert limit == 16385
            return json.dumps(response()).encode()
    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            assert timeout == 2
            return Reply()
    monkeypatch.setattr(gate.urllib.request, 'build_opener', lambda *handlers: Opener())
    gate.upstream({'model': gate.MODEL}, 'fake-unit-token', 2)
    assert seen[0].full_url == gate.UPSTREAM and seen[0].method == 'POST'
    with pytest.raises(ValueError, match='REDIRECT'):
        gate.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid')


def test_peer_credentials_refuse_another_uid(tmp_path):
    class Peer:
        def getsockopt(self, *args):
            return gate.struct.pack('3i', 100, os.getuid() + 1, os.getgid())
    with gate.Gateway(str(tmp_path / 'gate.sock'), gate.Handler) as server:
        assert not server.verify_request(Peer(), '')


def test_fleet_disagreement_accepts_one_validated_prior_only():
    p = replace(problem(), fleet_choice='reobserve')
    prior = {**reply(), 'input_hash': p.digest, 'profile_id': 'qwen-local'}
    body = {'problem': {**asdict(p), 'input_hash': p.digest}, 'prior': [prior], 'instruction': 'test'}
    assert gate.trusted_body(json.dumps(body))[0] == p
    for invalid in ([{**prior, 'choice': 'reobserve'}], [{**prior, 'objections': ['unsafe']}],
                    [{**prior, 'profile_id': ''}], [prior, prior], [{**prior, 'input_hash': 'wrong'}]):
        body['prior'] = invalid
        with pytest.raises(ValueError):
            gate.trusted_body(json.dumps(body))


@pytest.mark.parametrize('reasoning', [-1, 101, True])
def test_reasoning_usage_must_be_within_completion_tokens(reasoning):
    data = response()
    data['usage']['completion_tokens_details'] = {'reasoning_tokens': reasoning}
    with pytest.raises(ValueError):
        gate.checked_response(problem(), data)


def test_reasoning_usage_is_preserved_when_included_in_output_cap():
    data = response()
    data['usage']['completion_tokens_details'] = {'reasoning_tokens': 90}
    assert gate.checked_response(problem(), data)['usage']['completion_tokens_details'] == {'reasoning_tokens': 90}


def test_upstream_oversize_and_timeout_are_not_retried(monkeypatch):
    calls = []
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b'x' * limit
    class Opener:
        def open(self, *args, **kwargs):
            calls.append(1)
            return Reply()
    monkeypatch.setattr(gate.urllib.request, 'build_opener', lambda *handlers: Opener())
    with pytest.raises(ValueError, match='OUTPUT_EXCEEDED'):
        gate.upstream({'model': gate.MODEL}, 'fake-unit-token', 1)
    assert calls == [1]
