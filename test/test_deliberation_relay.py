import http.client
import http.server
import threading
from contextlib import closing

import pytest

from deploy.ai_pc import deliberation_relay as relay


@pytest.mark.parametrize('path,body', [('/other', b'{}'), ('/v1/chat/completions', b'x' * 16385)])
def test_relay_rejects_route_and_size_without_socket(path, body, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('gateway must not be contacted')
    monkeypatch.setattr(relay, 'UnixConnection', forbidden)
    with http.server.HTTPServer(('127.0.0.1', 0), relay.Handler) as server:
        server.timeout = 2
        worker = threading.Thread(target=server.handle_request, daemon=True)
        worker.start()
        with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)) as conn:
            conn.request('POST', path, body)
            response = conn.getresponse()
            response.read()
            assert response.status == 400
        worker.join(4)
        assert not worker.is_alive()


def test_relay_forwards_body_only_to_fixed_unix_route(monkeypatch):
    seen = []
    class Result:
        status = 200
        def read(self, limit): return b'data: [DONE]\n\n'
        def getheader(self, name, default): return 'text/event-stream'
    class Gateway:
        def __init__(self, host, timeout):
            assert host == 'localhost' and timeout == 30
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def close(self): pass
        def request(self, *args): seen.append(args)
        def getresponse(self): return Result()
    monkeypatch.setattr(relay, 'UnixConnection', Gateway)
    with http.server.HTTPServer(('127.0.0.1', 0), relay.Handler) as server:
        server.timeout = 2
        worker = threading.Thread(target=server.handle_request, daemon=True)
        worker.start()
        with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)) as conn:
            conn.request('POST', '/v1/chat/completions', b'{}', {'Authorization': 'untrusted'})
            response = conn.getresponse()
            assert response.read() == b'data: [DONE]\n\n' and response.status == 200
        worker.join(4)
        assert seen == [('POST', '/v1/chat/completions', b'{}', {'Content-Type': 'application/json'})]
