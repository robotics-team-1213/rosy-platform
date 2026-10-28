"""Media session termination uses the exact local MediaMTX session UUID."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
from pathlib import Path
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def implementation():
    assert (ROOT / 'src/rosy_media/backend.py').is_file(), 'D-789 MediaMTX management adapter missing'
    return importlib.import_module('rosy_media.backend')


def test_backend_kick_uses_dedicated_credential_and_exact_uuid():
    module = implementation()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append((self.path, self.headers.get('Authorization')))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = module.MediaMTXClient(f'http://127.0.0.1:{server.server_port}', 'media-admin')
        client.kick('00000000-0000-0000-0000-000000000001')
        assert calls == [('/v3/webrtc/sessions/kick/00000000-0000-0000-0000-000000000001', 'Bearer media-admin')]
        with pytest.raises(ValueError):
            client.kick('../../fleet/restart')
        assert len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('base', ['http://site.example:9997', 'https://127.0.0.1:9997',
                                'http://user:pass@127.0.0.1:9997', 'http://127.0.0.1:9997?token=x'])
def test_backend_cannot_target_remote_or_credential_bearing_urls(base):
    module = implementation()
    with pytest.raises(ValueError):
        module.MediaMTXClient(base, 'media-admin')
