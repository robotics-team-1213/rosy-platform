"""D-793: a users-file operator with policy_admin approves policies; a plain operator cannot."""
from fastapi.testclient import TestClient

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.site_users import hash_password
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore

from test_password_session import TYPED as PASSWORD  # noqa: E402  shared fixture value
HASH = hash_password(PASSWORD)
BASE = "https://rosy-site.local:8443"
ORIGIN = {"Origin": BASE}


def _client(tmp_path):
    db = tmp_path / "fleet.db"
    logins = {name: {"principal_id": name, "role": "operator", "password_scrypt": HASH, **extra}
              for name, extra in (("alice", {"policy_admin": True}), ("carol", {}))}
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(FleetTaskStore(db), robot_ids=()),
                     site_users={}, site_logins=logins, mission_service=MissionService(MissionStore(db)),
                     proposal_store=ProposalStore(db), omx_instances={"cell-1": "arm-1"},
                     omx_stop_transport=object(), start_task_dispatcher=False)
    return TestClient(app, base_url=BASE)


def _login(client, login):
    response = client.post("/api/fleet/auth/login", headers=ORIGIN,
                           json={"login": login, "password": PASSWORD, "remember": False})
    assert response.status_code == 204, response.text


def test_policy_admin_flag_grants_policy_decisions_beside_operate(tmp_path):
    body = dict(operator_confirmed=True, policy_revision="act-r1", to_stage="L0", rig_revision="rig-1",
                calibration_revision="cal-1", evidence_sha256="a" * 64, note="first training receipt")
    alice = _client(tmp_path)
    _login(alice, "alice")
    assert alice.get("/api/fleet/auth/session").json()["policy_admin"] is True
    assert alice.post("/api/fleet/workcells/cell-1/policy/proposals", headers=ORIGIN, json=body).status_code == 200
    carol = TestClient(alice.app, base_url=BASE)
    _login(carol, "carol")
    assert "policy_admin" not in carol.get("/api/fleet/auth/session").json()
    refused = carol.post("/api/fleet/workcells/cell-1/policy/proposals", headers=ORIGIN,
                         json=dict(body, policy_revision="act-r2"))
    assert refused.status_code == 403
    incident = carol.post("/api/fleet/workcells/cell-1/policy/incidents", headers=ORIGIN,
                          json=dict(operator_confirmed=True, description="gripper hit the bowl"))
    assert incident.status_code == 200
