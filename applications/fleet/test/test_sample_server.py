"""applications/fleet/dev runs without Fleet, ROS, or an upstream."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

DEV = Path(__file__).resolve().parents[1] / 'dev'


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
                 '/device-profile-sources/robot/sample-robot'):
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

