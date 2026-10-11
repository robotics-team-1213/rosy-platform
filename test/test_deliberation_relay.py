import http.client
import http.server
import threading

import pytest

from deploy.ai_pc import deliberation_relay as relay


@pytest.mark.parametrize('path,body', [('/other', b'{}'), ('/v1/chat/completions', b'x' * 16385)])
def test_relay_rejects_route_and_size_without_socket(path, body, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('gateway must not be contacted')
    monkeypatch.setattr(relay, 'UnixConnection', forbidden)
    with http.server.HTTPServer(('127.0.0.1', 0), relay.Handler) as server:
        worker = threading.Thread(target=server.handle_request)
        worker.start()
        with http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3) as conn:
            conn.request('POST', path, body)
            response = conn.getresponse()
            response.read()
            assert response.status == 400
        worker.join(4)
        assert not worker.is_alive()
