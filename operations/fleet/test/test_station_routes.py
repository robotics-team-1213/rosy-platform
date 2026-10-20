"""The opt-in station read surface is authenticated and cannot grant motion."""
import importlib
import importlib.util

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from test_station_pose_service import service, stable


def client(svc, *, authorized):
    name = 'fleet.server.station_routes'
    assert importlib.util.find_spec(name) is not None, 'station routes are not implemented'
    app = FastAPI()

    def viewer():
        if not authorized:
            raise HTTPException(401, 'auth required')

    importlib.import_module(name).install_station_routes(app, service=svc, require_viewer=viewer)
    return TestClient(app)


def test_station_read_is_authenticated(tmp_path):
    svc, _, _ = service(tmp_path)
    with client(svc, authorized=False) as web:
        assert web.get('/api/fleet/stations').status_code == 401


def test_station_read_has_no_motion_or_mutation_surface(tmp_path):
    svc, _, _ = service(tmp_path)
    stable(svc)
    with client(svc, authorized=True) as web:
        response = web.get('/api/fleet/stations')
        assert response.status_code == 200
        assert response.json()['stations'][0]['pose_revision'] == 1
        assert web.post('/api/fleet/stations').status_code == 405


def test_expired_installation_is_not_reported_as_valid(tmp_path):
    svc, now, _ = service(tmp_path)
    stable(svc)
    now[0] = 111.0
    with client(svc, authorized=True) as web:
        assert web.get('/api/fleet/stations').json()['stations'][0]['status'] == 'INVALID'
