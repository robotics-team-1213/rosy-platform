"""applications/fleet/dev runs without Fleet, ROS, or an upstream."""
import importlib.util
import json
import socket
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

DEV = Path(__file__).resolve().parents[1] / 'dev'


@pytest.fixture
def http_host(monkeypatch):
    monkeypatch.syspath_prepend(str(DEV))
    import http_host
    return http_host


def test_windows_bind_is_exclusive_before_binding(http_host, monkeypatch):
    calls = []
    exclusive = 0x10000
    monkeypatch.setattr(socket, 'SO_EXCLUSIVEADDRUSE', exclusive, raising=False)

    def initialize(server, address, handler):
        server.socket = SimpleNamespace(setsockopt=lambda *args: calls.append(args))
        server.server_bind()

    def bind(server):
        calls.append(('bind', server.allow_reuse_address, server.allow_reuse_port))

    monkeypatch.setattr(http_host.ThreadingHTTPServer, '__init__', initialize)
    monkeypatch.setattr(http_host.ThreadingHTTPServer, 'server_bind', bind)
    monkeypatch.setattr(http_host.ThreadingHTTPServer, 'allow_reuse_port', True)
    http_host.make_server(object(), 'http://localhost:4173')
    assert calls == [(socket.SOL_SOCKET, exclusive, 1), ('bind', False, False)]


def test_preview_port_has_one_owner_until_close(http_host):
    with http_host.make_server(load_engine(), 'http://localhost:0') as first:
        port = first.server_address[1]
        assert port > 0
        origin = f'http://localhost:{port}'
        with pytest.raises(OSError):
            with http_host.make_server(object(), origin):
                pass
    with http_host.make_server(object(), origin) as restarted:
        assert restarted.server_address[1] == port


def load_engine():
    path = DEV / 'sample' / 'engine.py'
    assert path.is_file(), 'standalone sample engine is missing'
    sys.path.insert(0, str(DEV))
    try:
        from sample.engine import SampleEngine
        return SampleEngine()
    finally:
        sys.path.remove(str(DEV))


def test_unknown_request_is_error_and_never_generic_success():
    engine = load_engine()
    engine.handle('POST', '/api/fleet/auth/login', {}, b'{"login":"sample","password":"CHANGE_ME"}')
    response = engine.handle('POST', '/api/fleet/not-implemented',
                             {'Cookie': 'rosy_sample_session=sample-1'}, b'{}')
    assert response.status == 501
    assert json.loads(response.body)['detail']['code'] == 'SAMPLE_REQUEST_NOT_IMPLEMENTED'


def test_sample_starts_without_backend_and_never_creates_upstream():
    assert (DEV / 'serve.py').is_file(), 'standalone command is missing'
    result = subprocess.run([sys.executable, '-I', str(DEV / 'serve.py'), '--check'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'sample ready' in result.stdout


def test_sample_profile_reads_report_absent_storage_without_hiding_unknown_requests():
    engine = load_engine()
    headers = {'Authorization': 'Bearer sample-operator'}
    for path in ('/device-profiles', '/device-profile-sources',
                 '/device-profile-sources/robot/sample-robot', '/device-profile-sources/arm/sample-arm'):
        response = engine.handle('GET', '/api/fleet' + path, headers, b'')
        assert response.status == 404
        assert json.loads(response.body) == {'detail': 'Not Found'}
    assert not engine.unhandled
    response = engine.handle('GET', '/api/fleet/device-profile-sources/unknown/sample-robot', headers, b'')
    assert response.status == 501
    assert engine.unhandled == [('GET', '/api/fleet/device-profile-sources/unknown/sample-robot')]


def test_sample_session_ignores_real_fleet_credentials():
    engine = load_engine()
    response = engine.handle('GET', '/api/fleet/auth/session',
                             {'Cookie': 'rosy_fleet_session=real-secret'}, b'')
    assert response.status == 401
    response = engine.handle('POST', '/api/fleet/auth/login', {},
                             b'{"login":"sample","password":"CHANGE_ME"}')
    assert response.status == 204
    cookie = next(v for k, v in response.headers if k.lower() == 'set-cookie')
    assert cookie.startswith('rosy_sample_session=')
    assert 'rosy_fleet_session' not in cookie


@pytest.mark.parametrize('scenario', ['normal', 'viewer'])
def test_sample_usb_listing_is_empty_over_http_without_relaxing_auth_or_origin(http_host, scenario):
    from http.client import HTTPConnection
    from threading import Thread

    engine = load_engine()
    engine.reset(scenario)
    server = http_host.make_server(engine, 'http://localhost:0')
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    port = server.server_address[1]
    origin = f'http://localhost:{port}'
    listing = '/api/fleet/workcell-observations/usb-devices'

    def request(method, path, data=None, headers=None):
        connection = HTTPConnection('localhost', port, timeout=5)
        try:
            connection.request(method, path, body=json.dumps(data) if data is not None else None,
                               headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    try:
        assert request('GET', listing)[0] == 401
        status, response_headers, _ = request('POST', '/api/fleet/auth/login',
            {'login': 'sample', 'password': 'CHANGE_ME'}, {'Origin': origin})
        assert status == 204
        session_header = response_headers['Set-Cookie'].split(';', 1)[0]
        headers = {'Cookie': session_header}
        assert request('GET', listing, headers={**headers, 'Origin': 'https://other.example'})[0] == 403
        status, _, body = request('GET', listing, headers=headers)
        assert status == 200 and json.loads(body) == {'workcells': []}
        assert engine.unhandled == []
        decision = '/api/fleet/workcell-observations/sample-cell/usb-devices/' + 'a' * 32 + '/decision'
        assert request('POST', decision, {'role': 'top'}, headers)[0] == 403
        assert request('POST', decision, {'role': 'top'}, {**headers, 'Origin': origin})[0] == (
            403 if scenario == 'viewer' else 501)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)


def test_local_vision_frame_needs_its_lease_and_preserves_binary_headers():
    engine = load_engine()
    engine.handle('POST', '/api/fleet/auth/login', {}, b'{"login":"sample","password":"CHANGE_ME"}')
    response = engine.handle('POST', '/api/fleet/vision/lease', {'Cookie':'rosy_sample_session=sample-1'},
                             b'{"source_id":"sample-camera"}')
    assert response.status == 200
    lease = json.loads(response.body)
    assert lease['frame_path'] == '/api/vision/sources/sample-camera/frame'
    assert engine.handle('GET', lease['frame_path'], {'Cookie':'rosy_sample_session=sample-1'}, b'').status == 401
    response = engine.handle('GET', lease['frame_path'], {'Authorization':'Bearer ' + lease['lease']}, b'')
    assert response.status == 200 and response.body.startswith(b'\x89PNG\r\n\x1a\n')
    assert dict(response.headers)['Content-Type'] == 'image/png'

