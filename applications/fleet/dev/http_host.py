"""Loopback-only application host with the production static asset allowlists."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import runpy
from urllib.parse import urlsplit

from response import DevResponse, error, reply

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / 'applications/fleet/web'
COMMON = ROOT / 'shared/web'
REGISTRY = runpy.run_path(str(WEB / 'asset_registry.py'))
ASSETS = REGISTRY['load_registry'](WEB)
SHARED = json.loads((COMMON / 'shared-assets.json').read_text(encoding='utf-8'))['shared_assets']
MAX_BODY = 2 * 1024 * 1024
DEV_WEB = Path(__file__).parent / 'web'
DEV_ASSETS = {'runtime-sample.js': 'application/javascript', 'browser-platform.js': 'application/javascript',
              'media-session.js': 'application/javascript', 'controls.js': 'application/javascript', 'controls.css': 'text/css'}


def static_response(path):
    if path == '/':
        return DevResponse(302, [('Location', '/console')], b'')
    if path == '/healthz':
        return reply({'status': 'ok', 'service': 'fleet-app-dev'})
    if path in ASSETS['pages']:
        entry = REGISTRY['resolve_entry'](WEB, ASSETS['pages'], path)
    elif path.startswith('/console/assets/'):
        entry = REGISTRY['resolve_entry'](WEB, ASSETS['assets'], path.removeprefix('/console/assets/'))
    elif path.startswith('/common/') and path.removeprefix('/common/') in SHARED:
        name = path.removeprefix('/common/')
        candidate = (COMMON / name).resolve()
        entry = (candidate, SHARED[name]) if candidate.is_relative_to(COMMON.resolve()) else None
    else:
        entry = None
    if entry is None:
        return error(404, 'NOT_FOUND')
    try:
        return DevResponse(200, [('Content-Type', entry[1]), ('Cache-Control', 'no-store'),
                                ('X-Content-Type-Options', 'nosniff')], entry[0].read_bytes())
    except OSError:
        return error(404, 'NOT_FOUND')


def make_server(provider, origin):
    local = urlsplit(origin)
    if local.scheme not in ('http', 'https') or local.hostname not in ('localhost', '127.0.0.1'):
        raise ValueError('development host must use a loopback origin')
    if local.username or local.password or local.path or local.query or local.fragment:
        raise ValueError('origin must contain only scheme and authority')

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass  # Never log authentication headers, passwords, or sample payloads.

        def respond(self, response, head=False):
            body = response.body
            self.send_response(response.status)
            for name, value in response.headers:
                if name.lower() not in ('content-length', 'connection', 'transfer-encoding'):
                    self.send_header(name, value)
            if isinstance(body, bytes):
                self.send_header('Content-Length', str(len(body)))
            else:
                self.send_header('Connection', 'close')
                self.close_connection = True
            self.end_headers()
            try:
                if not head:
                    for chunk in (body,) if isinstance(body, bytes) else body:
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            finally:
                if hasattr(body, 'close'):
                    body.close()

        def dispatch(self):
            if self.headers.get_all('Host') != [local.netloc]:
                self.close_connection = True
                return self.respond(error(403, 'DEV_HOST_REJECTED'))
            supplied = self.headers.get_all('Origin')
            mutation = self.command not in ('GET', 'HEAD')
            if (supplied is not None and supplied != [origin]) or (mutation and not supplied):
                self.close_connection = True
                return self.respond(error(403, 'DEV_ORIGIN_REJECTED'))
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) > 1:
                self.close_connection = True
                return self.respond(error(400, 'INVALID_BODY'))
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= MAX_BODY:
                    raise ValueError()
            except ValueError:
                self.close_connection = True
                return self.respond(error(413, 'BODY_TOO_LARGE'))
            body = self.rfile.read(length)
            if len(body) != length:
                self.close_connection = True
                return self.respond(error(400, 'INVALID_BODY'))
            path = urlsplit(self.path)
            if path.scheme or path.netloc or not self.path.startswith('/'):
                return self.respond(error(400, 'INVALID_TARGET'))
            if path.path.startswith('/__dev/') and not path.path.startswith('/__dev/assets/'):
                response = self.control(path.path, body)
            elif path.path.startswith(('/api/fleet/', '/api/vision/sources/')):
                response = provider.handle(self.command, self.path, dict(self.headers.items()), body)
            elif self.command in ('GET', 'HEAD'):
                response = self.static(path.path)
            else:
                response = error(405, 'METHOD_NOT_ALLOWED')
            self.respond(response, head=self.command == 'HEAD')

        def static(self, path):
            from sample.engine import SampleEngine
            sample = isinstance(provider, SampleEngine)
            name = 'runtime-sample.js' if path == '/console/assets/app-runtime.js' else path.removeprefix('/__dev/assets/')
            if sample and (path == '/console/assets/app-runtime.js' or path.startswith('/__dev/assets/')) and name in DEV_ASSETS:
                return DevResponse(200, [('Content-Type', DEV_ASSETS[name]), ('Cache-Control', 'no-store')], (DEV_WEB / name).read_bytes())
            response = static_response(path)
            if sample and path in ASSETS['pages'] and response.status == 200:
                controls = b'<link rel="stylesheet" href="/__dev/assets/controls.css"><script type="module" src="/__dev/assets/controls.js"></script>'
                response.body = response.body.replace(b'</head>', controls + b'</head>', 1)
            return response

        def control(self, path, body):
            from sample.engine import SampleEngine
            if not isinstance(provider, SampleEngine):
                return error(404, 'NOT_FOUND')
            try:
                if self.command != 'POST':
                    return error(405, 'METHOD_NOT_ALLOWED')
                payload = json.loads(body)
                if path == '/__dev/reset':
                    provider.reset(payload['scenario_id'])
                elif path == '/__dev/advance':
                    provider.advance(payload['flow_id'], payload['event'])
                else:
                    return error(404, 'NOT_FOUND')
                return reply({'scenario_id': provider.scenario_id})
            except (ValueError, KeyError, TypeError):
                return error(409, 'SAMPLE_TRANSITION_REJECTED')

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = dispatch

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

    class Server(ThreadingHTTPServer):
        daemon_threads = True

    server = Server(('127.0.0.1', local.port if local.port is not None else (443 if local.scheme == 'https' else 80)), Handler)
    if local.port == 0:
        origin = f'{local.scheme}://{local.hostname}:{server.server_address[1]}'
        local = urlsplit(origin)
    return server
