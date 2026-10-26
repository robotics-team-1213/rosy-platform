"""Fixed free Zen gateway: one synthetic call, same original persistent smoke slot."""
import http.server
import json
import math
import os
from pathlib import Path
import signal
import stat
import sys
import time
import urllib.request

from rosy.decision.deliberation import canonical
from rosy.decision.structured_output import openai_chat
from . import deliberation_free_codec as codec
from .deliberation_glm_gateway import Gateway, NoRedirect, stream_response
from .deliberation_smoke_budget import claim
from .deliberation_glm_receipt import digest

UPSTREAM = 'https://opencode.ai/inference/v1/chat/completions'
CONFIG_PATH = Path('/var/lib/rosy-deliberation/opencode-free.json')
LIMIT = 16384
CLIENT_HEADERS = ('user-agent', 'x-opencode-session', 'x-opencode-project', 'x-opencode-request',
                  'x-opencode-client', 'x-opencode-version', 'x-opencode-session-id', 'x-opencode-project-id')


def client_headers(headers):
    result = {}
    for name, value in headers.items():
        if name.lower() in CLIENT_HEADERS:
            if len(value) > 512 or any(ord(char) < 32 or ord(char) > 126 for char in value):
                raise ValueError('CLIENT_METADATA_REFUSED')
            result[name] = value  # Actual CLI metadata only; never synthesize an OpenCode identity.
    return result


def read_secret():
    fd = os.open(CONFIG_PATH, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096):
            raise ValueError('SECRET_BOUNDARY_FAILED')
        data = json.loads(os.read(fd, 4097))
        if (set(data) != {'type', 'key'} or data['type'] != 'api' or type(data['key']) is not str
                or not data['key'] or any(ord(c) < 33 or ord(c) > 126 for c in data['key'])):
            raise ValueError('SELECTED_OPENCODE_KEY_REQUIRED')
        return data['key']
    finally:
        os.close(fd)


def upstream(body, token, remaining, headers):
    request = urllib.request.Request(UPSTREAM, canonical(body).encode(),
        {**client_headers(headers), 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
        method='POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=remaining) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('FREE_OUTPUT_LIMIT')
    return json.loads(raw)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_POST(self):
        server = self.server
        self.connection.settimeout(max(.01, server.deadline - time.monotonic()))
        try:
            if (self.path != '/v1/chat/completions' or server.calls or self.headers.get('Transfer-Encoding')
                    or sum(len(k) + len(v) for k, v in self.headers.items()) > 8192):
                raise ValueError('FREE_REQUEST_REFUSED')
            size = int(self.headers.get('Content-Length', '-1'))
            if not 0 < size <= LIMIT:
                raise ValueError('FREE_REQUEST_REFUSED')
            incoming = json.loads(self.rfile.read(size))
            if (incoming.get('model') != codec.MODEL or incoming.get('tools')
                    or incoming.get('tool_choice', 'none') != 'none' or type(incoming.get('messages')) is not list
                    or any(item.get('tool_calls') or item.get('function_call')
                           or item.get('role') in {'tool', 'function'} for item in incoming['messages'])):
                raise ValueError('FREE_REQUEST_REFUSED')
            headers = client_headers(self.headers)
            # shortcut: json_object until an opencode json_schema probe passes (D-878 §3).
            request = openai_chat(codec.MODEL,
                [dict(role='system', content='Return only the requested schema v2 advisory JSON. No tools.'),
                 dict(role='user', content=server.body)])
            claim(server.body)
            server.calls = 1
            response = codec.checked_response(upstream(request, server.token,
                max(.01, server.deadline - time.monotonic()), headers))
            raw = stream_response(response) if incoming.get('stream') is True else canonical(response).encode()
            server.metrics = dict(state='PASS_FREE_PROVIDER_ONLY', calls=1, usage=response['usage'],
                job_sha256=digest(json.loads(server.body)),
                judgment_sha256=digest(json.loads(response['choices'][0]['message']['content'])),
                tariff_basis='FIXED_FREE_SKU_CATALOG', cost_usd=None, cost_complete=False,
                runtime_admitted=False, action_admissible=False)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if incoming.get('stream') is True else 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except Exception:
            server.metrics = dict(state='HOLD', reason='FREE_REQUEST_FAILED', calls=server.calls,
                                  cost_usd=None, cost_complete=False)
            self.send_error(400, 'FREE_REQUEST_FAILED')


def main():
    job = json.loads(sys.stdin.buffer.readline(LIMIT + 1024))
    if (set(job) != {'body', 'deadline_s', 'socket_path', 'secret_path'}
            or job['secret_path'] != str(CONFIG_PATH)):
        raise ValueError('FREE_JOB_REFUSED')
    duration = job['deadline_s']
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 30:
        raise ValueError('FREE_DEADLINE_REFUSED')
    _, body = codec.trusted_body(job['body'])
    path = Path(job['socket_path']); parent = path.parent.stat()
    if (not path.is_absolute() or path.parent.resolve() != path.parent or path.exists()
            or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700):
        raise ValueError('FREE_SOCKET_BOUNDARY_FAILED')
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError()))
    signal.setitimer(signal.ITIMER_REAL, duration)
    with Gateway(str(path), Handler) as server:
        try:
            os.chmod(path, 0o600)
            server.body, server.token = body, read_secret()
            server.deadline, server.calls, server.timeout = time.monotonic() + duration, 0, duration
            server.metrics = dict(state='HOLD', reason='NO_FREE_REQUEST', calls=0)
            print('READY', flush=True)
            server.handle_request()
            print(canonical(server.metrics), flush=True)
            return 0 if server.metrics['state'] == 'PASS_FREE_PROVIDER_ONLY' else 1
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception:
        print('{"state":"HOLD","reason":"FREE_GATEWAY_FAILED","calls":null}', flush=True)
        sys.exit(1)
