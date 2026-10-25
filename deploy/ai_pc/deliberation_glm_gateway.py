"""One admitted GLM request; the isolated CLI never receives host credentials."""
import http.server
import json
import math
import os
from pathlib import Path
import signal
import socket
import socketserver
import stat
import struct
import sys
import time
import urllib.request

from rosy.decision.deliberation import Problem, canonical, identifier, opinion
from rosy.decision.structured_output import openai_chat, openai_reply
from .deliberation_smoke_budget import claim

MODEL = 'glm-5.3-flash'
UPSTREAM = 'https://api.z.ai/api/coding/paas/v4/chat/completions'
CONFIG_PATH = Path('/var/lib/rosy-deliberation/glm-coding-plan.json')
LIMIT = 16384


def trusted_body(raw):
    data = json.loads(raw)
    if 'schema' in data or 'profile_revision' in data:
        from . import deliberation_glm_judgment as versioned
        problem, _, _, body = versioned.request(data)
        return problem, body
    if (set(data) != {'problem', 'prior', 'instruction'}
            or type(data['prior']) is not list or len(data['prior']) > 1):
        raise ValueError('INVALID_TRUSTED_JOB')
    fields = dict(data['problem'])
    digest = fields.pop('input_hash')
    problem = Problem(**fields)
    if digest != problem.digest:
        raise ValueError('INVALID_TRUSTED_JOB')
    if data['prior']:
        prior = dict(data['prior'][0])
        identifier(prior.pop('profile_id'))
        checked = opinion(problem, prior)
        if (problem.fleet_choice is None or checked['choice'] == problem.fleet_choice
                or 'unsafe' in checked['objections']):
            raise ValueError('INVALID_TRUSTED_JOB')
    canonical(data)
    return problem, canonical(data)


def read_secret():
    fd = os.open(CONFIG_PATH, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096):
            raise ValueError('SECRET_BOUNDARY_FAILED')
        data = json.loads(os.read(fd, 4097))
        if (set(data) != {'type', 'key'} or data['type'] != 'api'
                or type(data['key']) is not str or not data['key']
                or any(ord(char) < 33 or ord(char) > 126 for char in data['key'])):
            raise ValueError('SECRET_BOUNDARY_FAILED')
        return data['key']
    finally:
        os.close(fd)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('UPSTREAM_REDIRECT_REFUSED')


def upstream(body, token, remaining):
    request = urllib.request.Request(UPSTREAM, canonical(body).encode(),
        {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}, method='POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=remaining) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('UPSTREAM_OUTPUT_EXCEEDED')
    return json.loads(raw)


def checked_response(problem, response, *, body=None):
    payload = openai_reply(response, MODEL, 'INVALID_UPSTREAM_RESULT')
    usage = {key: response['usage'][key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    if (any(type(value) is not int or value < 0 for value in usage.values())
            or usage['completion_tokens'] > 1024
            or usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']):
        raise ValueError('INVALID_UPSTREAM_RESULT')
    details = response['usage'].get('completion_tokens_details', {})
    if 'reasoning_tokens' in details:
        count = details['reasoning_tokens']
        if type(count) is not int or not 0 <= count <= usage['completion_tokens']:
            raise ValueError('INVALID_REASONING_USAGE')
        usage['completion_tokens_details'] = {'reasoning_tokens': count}
    if body is not None and 'schema' in json.loads(body):
        from . import deliberation_glm_judgment as versioned
        payload = versioned.result(problem, body, payload)
    else:
        payload = opinion(problem, payload)
    return {'id': 'rosy-glm-one-shot', 'object': 'chat.completion', 'model': MODEL,
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': canonical(payload)},
                         'finish_reason': 'stop'}], 'usage': usage}


def stream_response(response):
    base = {'id': response['id'], 'object': 'chat.completion.chunk', 'model': response['model']}
    content = response['choices'][0]['message']['content']
    chunks = [{**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': content},
                                   'finish_reason': None}]},
              {**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
              {**base, 'choices': [], 'usage': response['usage']}]
    return ''.join('data: ' + canonical(chunk) + '\n\n' for chunk in chunks).encode() + b'data: [DONE]\n\n'


class Gateway(socketserver.UnixStreamServer):
    def verify_request(self, request, address):
        return struct.unpack('3i', request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1] == os.getuid()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        server = self.server
        self.connection.settimeout(max(0.01, server.deadline - time.monotonic()))
        try:
            if (self.path != '/v1/chat/completions' or server.calls
                    or sum(len(k) + len(v) for k, v in self.headers.items()) > 8192):
                raise ValueError('REQUEST_REFUSED')
            size = int(self.headers.get('Content-Length', '-1'))
            if not 0 < size <= LIMIT or self.headers.get('Transfer-Encoding'):
                raise ValueError('REQUEST_REFUSED')
            incoming = json.loads(self.rfile.read(size))
            if (incoming.get('model') != MODEL or incoming.get('tools')
                    or incoming.get('tool_choice', 'none') != 'none'
                    or type(incoming.get('messages')) is not list
                    or any(item.get('tool_calls') or item.get('function_call')
                           or item.get('role') in {'tool', 'function'} for item in incoming['messages'])):
                raise ValueError('REQUEST_REFUSED')
            # shortcut: json_object until a z.ai json_schema probe passes (D-878 §3), then pass the job schema.
            request = openai_chat(MODEL, [
                {'role': 'system', 'content': 'Return only the requested bound JSON opinion. No tools.'},
                {'role': 'user', 'content': server.body}],
                thinking={'type': 'enabled'}, reasoning_effort='low')
            claim(server.body)
            server.calls = 1
            provider_response = upstream(request, server.token, max(0.01, server.deadline - time.monotonic()))
            response = checked_response(server.problem, provider_response, body=server.body)
            stream = incoming.get('stream') is True
            raw = stream_response(response) if stream else canonical(response).encode()
            server.metrics = {'state': 'PASS_GLM_PROVIDER_ONLY', 'calls': 1, 'usage': response['usage']}
            if 'schema' in json.loads(server.body):
                from .deliberation_glm_receipt import receipt
                server.metrics.update(receipt(server.body, provider_response,
                                              credential_sha256=server.credential_sha256))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if stream else 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except Exception:
            server.metrics = {'state': 'HOLD', 'reason': 'GLM_REQUEST_FAILED', 'calls': server.calls}
            self.send_error(400, 'GLM_REQUEST_FAILED')


def main():
    job = json.loads(sys.stdin.buffer.readline(LIMIT + 1024))
    fields = {'body', 'deadline_s', 'socket_path', 'secret_path'}
    if set(job) not in (fields, fields | {'credential_sha256'}) or job['secret_path'] != str(CONFIG_PATH):
        raise ValueError('INVALID_JOB')
    duration = job['deadline_s']
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 30:
        raise ValueError('INVALID_DEADLINE')
    problem, body = trusted_body(job['body'])
    path = Path(job['socket_path'])
    parent = path.parent.stat()
    if (not path.is_absolute() or path.parent.resolve() != path.parent or path.exists()
            or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700):
        raise ValueError('SOCKET_BOUNDARY_FAILED')
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError()))
    signal.setitimer(signal.ITIMER_REAL, duration)
    with Gateway(str(path), Handler) as server:
        try:
            os.chmod(path, 0o600)
            server.problem, server.body, server.token = problem, body, read_secret()
            if 'schema' in json.loads(body):
                from .deliberation_glm_receipt import credential
                server.credential_sha256 = credential(server.token, job.get('credential_sha256'))
            server.deadline, server.calls = time.monotonic() + duration, 0
            server.metrics = {'state': 'HOLD', 'reason': 'NO_REQUEST', 'calls': 0}
            server.timeout = duration
            print('READY', flush=True)
            server.handle_request()
            print(canonical(server.metrics), flush=True)
            return 0 if server.metrics['state'] == 'PASS_GLM_PROVIDER_ONLY' else 1
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('{"state":"HOLD","reason":"GLM_GATEWAY_FAILED"}', flush=True)
        sys.exit(1)
