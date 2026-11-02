"""Development mode keeps connection metadata and requires human authentication."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.development_session import DevelopmentSessions
from fleet.server.site_auth import SitePrincipal, build_authorize, build_role_guards
from fleet.server.site_users import hash_password
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

BASE = "https://127.0.0.1:8090"
ORIGIN = {"Origin": BASE}
SESSION = "/api/fleet/auth/development-session"


def _client(tmp_path, *, development=True, logins=None, console_token=None):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8081", "t")], [FakeRobot("rosy_01")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    app = create_app(console, task_service=tasks, console_token=console_token, site_logins=logins,
                     development_sessions=DevelopmentSessions() if development else None)
    return TestClient(app, base_url=BASE, client=("127.0.0.1", 50000))


@pytest.mark.parametrize("development", [True, False])
def test_connection_metadata_does_not_issue_anonymous_credentials(tmp_path, development):
    client = _client(tmp_path, development=development)
    response = client.get("/api/fleet/auth/connection")
    assert response.json() == {"mode": "development" if development else "paired", "password_login": False}
    assert response.headers["cache-control"] == "no-store"
    response = client.post(SESSION, headers=ORIGIN)
    assert response.status_code == 403
    assert "token" not in response.json()


@pytest.mark.parametrize("token", [None, "retired-development-token", "registry-secret"])
def test_development_without_human_configuration_never_falls_back_to_site_console(tmp_path, token):
    client = _client(tmp_path, console_token="registry-secret")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    assert client.get("/api/fleet/session", headers=headers).status_code == 401


def test_existing_synthetic_development_bearer_is_never_consulted():
    class OldSessions:
        def principal(self, token):
            return SitePrincipal("development-12345678", "operator")
    app = FastAPI()
    authorize = build_authorize(None, {}, None, development=OldSessions())
    @app.get("/api/fleet/session")
    def session(principal=Depends(authorize)):
        return {"principal_id": principal.principal_id}
    assert TestClient(app).get("/api/fleet/session", headers={"Authorization": "Bearer old"}).status_code == 401


def test_development_human_cookie_preserves_identity_role_and_logout(tmp_path):
    logins = {"alice": {"principal_id": "alice", "role": "viewer", "password_scrypt": hash_password("correct horse")}}
    client = _client(tmp_path, logins=logins)
    assert client.get("/api/fleet/auth/connection").json() == {"mode": "development", "password_login": True}
    assert client.get("/api/fleet/session").status_code == 401
    assert client.post("/api/fleet/auth/login", headers=ORIGIN,
                       json={"login": "alice", "password": "correct horse"}).status_code == 204
    assert client.get("/api/fleet/session").json() == {"principal_id": "alice", "role": "viewer"}
    assert client.post("/api/fleet/estop", headers=ORIGIN).status_code == 403
    assert client.post(SESSION, headers=ORIGIN).status_code == 403
    assert client.post("/api/fleet/auth/logout", headers=ORIGIN).status_code == 204
    assert client.get("/api/fleet/session").status_code == 401
    assert client.get("/api/fleet/session", headers={"Authorization": "Bearer old-development-token"}).status_code == 401


def test_synthetic_name_cannot_satisfy_named_operator_guard():
    def authorize():
        return SitePrincipal("development-12345678", "operator")
    _, _, named, _ = build_role_guards(authorize, {})
    app = FastAPI()
    @app.post("/named")
    def route(principal=Depends(named)):
        return {}
    assert TestClient(app).post("/named").status_code == 403
