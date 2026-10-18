"""WHIP is authenticated HTTP, including session deletion and origin binding."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from pathlib import Path
import threading

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'src/rosy_media_edge/whip.py'


def implementation():
    assert SOURCE.is_file(), 'D-789 WHIP client is missing'
    spec = importlib.util.spec_from_file_location('whip_under_test', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def endpoint():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(('POST', self.path, self.headers.get('Authorization'),
                          self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(201)
            self.send_header('Content-Type', 'application/sdp')
            self.send_header('Location', '/camera/session/1')
            self.end_headers()
            self.wfile.write(b'v=0\r\n')

        def do_DELETE(self):
            calls.append(('DELETE', self.path, self.headers.get('Authorization'), b''))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield f'http://127.0.0.1:{server.server_port}/camera/whip', calls
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


def test_whip_authenticates_offer_and_session_delete(endpoint):
    module = implementation()
    url, calls = endpoint
    session = module.WhipSession(url, 'scoped-test-token', allow_loopback_http=True)
    assert session.open('v=0\r\n') == 'v=0\r\n'
    session.close()
    session.close()
    assert calls == [('POST', '/camera/whip', 'Bearer scoped-test-token', b'v=0\r\n'),
                     ('DELETE', '/camera/session/1', 'Bearer scoped-test-token', b'')]


@pytest.mark.parametrize('url', ['http://camera.example/whip',
    'https://user:password@camera.example/whip', 'https://camera.example/whip?token=secret',
    'file:///tmp/offer', 'https://camera.example/whip#secret'])
def test_whip_refuses_unsafe_endpoints(url):
    module = implementation()
    with pytest.raises(ValueError):
        module.WhipSession(url, 'token', allow_loopback_http=True)


def test_whip_refuses_bearer_header_injection():
    module = implementation()
    with pytest.raises(ValueError):
        module.WhipSession('https://media.example/cam/whip', 'token\r\nHeader: value')
