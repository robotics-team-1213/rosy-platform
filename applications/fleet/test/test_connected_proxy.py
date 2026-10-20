"""Real local TLS upstream; verify origin, credentials and response delivery boundaries."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
import subprocess
import threading

import pytest
from test_sample_server import DEV


def proxy_type():
    assert (DEV / 'connected.py').is_file(), 'connected Fleet provider is missing'
    from connected import ConnectedAPI
    return ConnectedAPI


@pytest.fixture
def upstream(tmp_path):
    certificate, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-keyout', str(key), '-out', str(certificate), '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=DNS:localhost'], check=True, capture_output=True)
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            requests.append((self.command, self.path, dict(self.headers)))
            path = self.path.removeprefix('/api/fleet/')
            code = int(path) if path in ('401', '403', '409', '500') else 204 if path in ('login', 'logout') else 302 if path == 'redirect' else 200
            self.send_response(code)
            self.send_header('Content-Type', 'application/octet-stream')
            if path in ('login', 'logout', 'domain'):
                value = '' if path == 'logout' else 'test-session'
                self.send_header('Set-Cookie', f'rosy_fleet_session={value}; Path=/; Secure; HttpOnly; SameSite=Lax'
                                 + ('; Max-Age=0' if path == 'logout' else '; Domain=localhost' if path == 'domain' else ''))
            if path == 'redirect':
                self.send_header('Location', 'https://external.invalid/steal')
            self.end_headers()
            if code != 204:
                self.wfile.write(b'\x00\xffsample\n')
        do_POST = do_GET
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'https://localhost:{server.server_address[1]}', ssl.create_default_context(cafile=str(certificate)), requests
    finally:
        server.shutdown(); server.server_close(); thread.join(5)


def read(response):
    if isinstance(response.body, bytes):
        return response.body
    try:
        return b''.join(response.body)
    finally:
        response.body.close()


def test_login_write_logout_and_cookie_revocation(upstream):
    endpoint, context, requests = upstream
    proxy = proxy_type()(endpoint, context, 'https://localhost:4174')
    headers = {'Host': 'localhost:4174', 'Origin': 'https://localhost:4174',
               'Cookie': 'other=secret; rosy_sample_session=demo; rosy_fleet_session=test-session',
               'Authorization': 'Bearer test-token', 'X-Rosy-Session': 'test-family', 'Idempotency-Key': 'test-intent',
               'Forwarded': 'host=attacker.invalid', 'X-Forwarded-Host': 'attacker.invalid'}
    for path in ('login', 'logout'):
        response = proxy.handle('POST', '/api/fleet/' + path, headers, b'{}')
        assert response.status == 204
        cookie = next(v for k, v in response.headers if k.lower() == 'set-cookie')
        assert all(part in cookie for part in ('Secure', 'HttpOnly', 'SameSite=Lax'))
        assert ('Max-Age=0' in cookie) == (path == 'logout')
        read(response)
    forwarded = {k.lower(): v for k, v in requests[-1][2].items()}
    assert forwarded['host'] == endpoint.removeprefix('https://')
    assert forwarded['origin'] == endpoint
    assert forwarded['cookie'] == 'rosy_fleet_session=test-session'
    assert forwarded['authorization'] == 'Bearer test-token'
    assert forwarded['x-rosy-session'] == 'test-family'
    assert forwarded['idempotency-key'] == 'test-intent'
    assert not any(k == 'forwarded' or k.startswith('x-forwarded-') for k in forwarded)


@pytest.mark.parametrize('headers', [{}, {'Host': 'localhost:4174'},
    {'Host': 'foreign.invalid', 'Origin': 'https://localhost:4174'},
    {'Host': 'localhost:4174', 'Origin': 'https://foreign.invalid'}])
def test_foreign_origin_host_and_missing_origin_never_reach_upstream(upstream, headers):
    endpoint, context, requests = upstream
    response = proxy_type()(endpoint, context, 'https://localhost:4174').handle('POST', '/api/fleet/write', headers, b'{}')
    assert response.status == 403
    assert not requests


def test_tls_errors_binary_cancellation_and_redirect(upstream):
    endpoint, context, requests = upstream
    proxy = proxy_type()(endpoint, context, 'https://localhost:4174')
    headers = {'Host': 'localhost:4174'}
    for status in ('200', '401', '403', '409', '500'):
        response = proxy.handle('GET', '/api/fleet/' + status, headers, b'')
        assert response.status == int(status)
        assert read(response) == b'\x00\xffsample\n'
    response = proxy.handle('GET', '/api/fleet/200', headers, b'')
    response.body.close()
    assert response.body.closed
    assert proxy.handle('GET', '/api/fleet/domain', headers, b'').status == 502
    assert proxy.handle('GET', '/api/fleet/redirect', headers, b'').status == 502
    bad = proxy_type()(endpoint, ssl.create_default_context(), 'https://localhost:4174')
    assert bad.handle('GET', '/api/fleet/200', headers, b'').status == 502
    assert all(path.startswith('/api/fleet/') for _, path, _ in requests)


def test_connected_requires_verified_https_and_rejects_arbitrary_targets():
    cls = proxy_type()
    for endpoint in ('http://localhost', 'https://user:password@localhost', 'https://localhost/api'):
        with pytest.raises(ValueError):
            cls(endpoint, ssl.create_default_context(), 'https://localhost:4174')
    with pytest.raises(ValueError):
        cls('https://localhost', ssl._create_unverified_context(), 'https://localhost:4174')


def test_vision_frame_uses_only_lease_bearer_and_same_upstream(upstream):
    endpoint, context, requests = upstream
    proxy = proxy_type()(endpoint, context, 'https://localhost:4174')
    headers = {'Host':'localhost:4174', 'Authorization':'Bearer sample-lease', 'Cookie':'rosy_fleet_session=private-session'}
    response = proxy.handle('GET', '/api/vision/sources/sample-camera/frame', headers, b'')
    assert response.status == 200 and read(response) == b'\x00\xffsample\n'
    forwarded = {key.lower(): value for key, value in requests[-1][2].items()}
    assert forwarded['authorization'] == 'Bearer sample-lease' and 'cookie' not in forwarded
    before = len(requests)
    assert proxy.handle('GET', '/api/vision/secrets', headers, b'').status == 400
    assert proxy.handle('POST', '/api/vision/sources/sample-camera/frame',
                        {**headers, 'Origin': 'https://localhost:4174'}, b'').status == 400
    assert len(requests) == before
