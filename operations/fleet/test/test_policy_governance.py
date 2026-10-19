"""D-793: a trained policy reaches the arm only through recorded human approval, and stops on doubt."""

from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.policy_governance import GovernanceError, PolicyGovernanceStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


class Transport:
    def __init__(self, state="hold"):
        self.state = state

    def owner_state(self, *, workcell_id, instance_id):
        return {"version": 1, "status": 200, "workcell_id": workcell_id, "instance_id": instance_id,
                "owner": {"state": self.state, "reason": "policy_lease_expired_or_invalid", "observed_sequence": 7}}


TOKENS = {"admin-a": "policy-admin", "admin-b": "policy-admin", "operator-a": "operator", "viewer-a": "viewer"}
BASE = "/api/fleet/workcells/cell-1/policy"
DIGEST = "a" * 64
REV = dict(rig_revision="rig-1", calibration_revision="cal-1")


def auth(name):
    return {"Authorization": f"Bearer {name}-token"}


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "fleet.db"
    tasks = FleetTaskService(FleetTaskStore(db), robot_ids=())
    users = {sha256(f"{name}-token".encode()).hexdigest(): {"principal_id": name, "role": role}
             for name, role in TOKENS.items()}
    app = create_app(FleetConsole([], []), task_service=tasks, site_users=users,
                     mission_service=MissionService(MissionStore(db)), proposal_store=ProposalStore(db),
                     omx_instances={"cell-1": "arm-1"}, omx_stop_transport=Transport(),
                     start_task_dispatcher=False)
    return TestClient(app)


def propose(client, stage, who="admin-a", **extra):
    body = dict(operator_confirmed=True, policy_revision="act-r1", to_stage=stage, evidence_sha256=DIGEST,
                note="offline eval receipt", **REV) | extra
    return client.post(BASE + "/proposals", headers=auth(who), json=body)


def decide(client, proposal, who, approve=True):
    return client.post(f"{BASE}/proposals/{proposal['proposal_id']}/decision", headers=auth(who),
                       json=dict(operator_confirmed=True, approve=approve))


def promote(client, stage, proposer="admin-a", approver="admin-b"):
    proposal = propose(client, stage, proposer)
    assert proposal.status_code == 200, proposal.text
    result = decide(client, proposal.json(), approver)
    assert result.status_code == 200, result.text


def to_l3(client):
    for stage in ("L0", "L1", "L2", "L3"):
        promote(client, stage)


def open_window(client, kind="supervised", minutes=None):
    window = client.post(BASE + "/windows", headers=auth("admin-a"), json=dict(
        operator_confirmed=True, policy_revision="act-r1", kind=kind, minutes=minutes, scope="pick strawberry",
        **REV))
    assert window.status_code == 200, window.text
    approved = client.post(f"{BASE}/windows/{window.json()['window_id']}/approve", headers=auth("admin-b"),
                           json=dict(operator_confirmed=True))
    assert approved.status_code == 200, approved.text
    return approved.json()


def lease(client, **extra):
    return client.post(BASE + "/lease", headers=auth("operator-a"),
                       json=dict(episode_id="ep-1", owner_session_id="owner-1") | extra)


def test_training_alone_grants_nothing_and_stages_move_one_step(client):
    state = client.get(BASE, headers=auth("viewer-a")).json()
    assert state["policies"] == [] and state["rules"]["lease_max_ms"] == 2000
    assert propose(client, "L1").json()["detail"]["code"] == "STAGE_SKIP_REFUSED"
    promote(client, "L0", "admin-a", "admin-a")
    assert propose(client, "L2").json()["detail"]["code"] == "STAGE_SKIP_REFUSED"
    promote(client, "L1", "admin-a", "admin-a")
    promote(client, "L2", "admin-a", "admin-a")
    assert lease(client).json()["detail"]["code"] == "NO_ACTIVE_EXECUTION_WINDOW"


def test_real_arm_stages_need_a_second_person(client):
    for stage in ("L0", "L1", "L2"):
        promote(client, stage)
    proposal = propose(client, "L3").json()
    refused = decide(client, proposal, "admin-a")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "APPROVER_MUST_DIFFER_FROM_PROPOSER"
    assert decide(client, proposal, "admin-b").status_code == 200
    window = client.post(BASE + "/windows", headers=auth("admin-a"), json=dict(
        operator_confirmed=True, policy_revision="act-r1", kind="supervised", scope="s", **REV)).json()
    assert client.post(f"{BASE}/windows/{window['window_id']}/approve", headers=auth("admin-a"),
                       json=dict(operator_confirmed=True)).status_code == 403


@pytest.mark.parametrize("who", ["operator-a", "viewer-a"])
def test_only_policy_admins_change_stages(client, who):
    assert propose(client, "L0", who).status_code == 403


def test_supervised_window_bounds_and_leases(client):
    to_l3(client)
    too_long = client.post(BASE + "/windows", headers=auth("admin-a"), json=dict(
        operator_confirmed=True, policy_revision="act-r1", kind="supervised", minutes=31, scope="s", **REV))
    assert too_long.status_code == 422 and too_long.json()["detail"]["code"] == "WINDOW_TOO_LONG"
    window = open_window(client)
    assert window["expires_ns"] - window["starts_ns"] == 15 * 60 * 10**9
    first = lease(client)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["expires_ns"] - body["issued_ns"] == 1000 * 10**6 and body["device_delivery"] == "not_connected"
    assert lease(client, duration_ms=2001).status_code == 422
    renewed = lease(client, lease_id=body["lease_id"])
    assert renewed.status_code == 200 and renewed.json()["expires_ns"] > body["expires_ns"]
    assert lease(client, lease_id=body["lease_id"], episode_id="other").json()["detail"]["code"] == \
        "LEASE_RENEWAL_REFUSED"
    assert client.post(BASE + "/lease", headers=auth("viewer-a"),
                       json=dict(episode_id="e", owner_session_id="o")).status_code == 403


def test_shadow_window_never_issues_a_runtime_lease(client):
    for stage in ("L0", "L1", "L2"):
        promote(client, stage)
    assert client.post(BASE + "/windows", headers=auth("admin-a"), json=dict(
        operator_confirmed=True, policy_revision="act-r1", kind="supervised", scope="s", **REV)
    ).json()["detail"]["code"] == "STAGE_TOO_LOW"
    open_window(client, kind="shadow")
    assert lease(client).json()["detail"]["code"] == "NO_ACTIVE_EXECUTION_WINDOW"


def test_confirmation_blocks_leases_until_a_policy_admin_resolves_it(client):
    to_l3(client)
    open_window(client)
    opened = client.post(BASE + "/confirmations", headers=auth("operator-a"), json=dict(
        operator_confirmed=True, reason="target_not_reached", policy_revision="act-r1",
        evidence={"errors_rad": [0.3, 0, 0, 0, 0, 0]}))
    assert opened.status_code == 200, opened.text
    assert lease(client).json()["detail"]["code"] == "CONFIRMATION_PENDING"
    path = f"{BASE}/confirmations/{opened.json()['confirmation_id']}/resolve"
    assert client.post(path, headers=auth("operator-a"), json=dict(
        operator_confirmed=True, resolution="resume", note="checked")).status_code == 403
    resolved = client.post(path, headers=auth("admin-a"), json=dict(
        operator_confirmed=True, resolution="send_to_learning", note="regrasp failure"))
    assert resolved.status_code == 200 and resolved.json()["resolution"] == "send_to_learning"
    state = client.get(BASE, headers=auth("viewer-a")).json()
    assert state["policies"][0]["stage"] == "L1" and not any(w["active"] for w in state["windows"])
    assert lease(client).json()["detail"]["code"] == "NO_ACTIVE_EXECUTION_WINDOW"


def test_incident_closes_windows_and_blocks_real_arm_approval(client):
    to_l3(client)
    open_window(client)
    incident = client.post(BASE + "/incidents", headers=auth("operator-a"),
                           json=dict(operator_confirmed=True, description="gripper hit the bowl"))
    assert incident.status_code == 200
    assert lease(client).json()["detail"]["code"] == "NO_ACTIVE_EXECUTION_WINDOW"
    assert propose(client, "LIMITED").json()["detail"]["code"] == "INCIDENT_OPEN"
    assert client.post(BASE + "/windows", headers=auth("admin-a"), json=dict(
        operator_confirmed=True, policy_revision="act-r1", kind="supervised", scope="s", **REV)
    ).json()["detail"]["code"] == "INCIDENT_OPEN"
    cleared = client.post(f"{BASE}/incidents/{incident.json()['incident_id']}/clear", headers=auth("admin-a"),
                          json=dict(operator_confirmed=True, note="bowl moved, limits rechecked"))
    assert cleared.status_code == 200
    open_window(client)


def test_owner_hold_becomes_one_confirmation(client):
    first = client.post(BASE + "/confirmations/sync-owner", headers=auth("operator-a")).json()
    second = client.post(BASE + "/confirmations/sync-owner", headers=auth("operator-a")).json()
    assert first["created"]["reason"] == "owner_hold" and second["created"] is None
    assert len(client.get(BASE, headers=auth("viewer-a")).json()["confirmations"]) == 1


def test_changed_rig_needs_reapproval(client):
    to_l3(client)
    changed = client.post(BASE + "/windows", headers=auth("admin-a"), json=dict(
        operator_confirmed=True, policy_revision="act-r1", kind="supervised", scope="s",
        rig_revision="rig-2", calibration_revision="cal-1"))
    assert changed.json()["detail"]["code"] == "REVISION_CHANGED_REAPPROVAL_REQUIRED"


def test_governance_is_installed_without_the_mission_api(tmp_path):
    """The site Fleet runs with --tasks-db but without --mission-api (2026-10-19)."""
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.db"), robot_ids=())
    users = {sha256(b"viewer-a-token").hexdigest(): {"principal_id": "viewer-a", "role": "viewer"}}
    app = create_app(FleetConsole([], []), task_service=tasks, site_users=users,
                     omx_instances={"cell-1": "arm-1"}, omx_stop_transport=Transport(), start_task_dispatcher=False)
    client = TestClient(app)
    assert client.get("/api/fleet/policy-governance/workcells", headers=auth("viewer-a")).json() == {
        "workcells": ["cell-1"]}
    assert client.get(BASE, headers=auth("viewer-a")).status_code == 200


def test_unknown_workcell_and_unconfirmed_bodies_are_refused(client):
    assert client.get("/api/fleet/workcells/other/policy", headers=auth("viewer-a")).status_code == 404
    assert client.post(BASE + "/incidents", headers=auth("operator-a"),
                       json=dict(operator_confirmed=False, description="x")).status_code == 422


def test_lease_never_outlives_its_window_and_reporter_cannot_clear(tmp_path):
    now = [10**12]
    store = PolicyGovernanceStore(tmp_path / "g.db", clock=lambda: now[0])
    for stage in ("L0", "L1", "L2", "L3"):
        proposal = store.propose(workcell_id="c", policy_revision="p", to_stage=stage, evidence_sha256=DIGEST,
                                 note="n", principal_id="a", **REV)
        store.decide(proposal_id=proposal["proposal_id"], approve=True, principal_id="b")
    window = store.request_window(workcell_id="c", policy_revision="p", kind="supervised", minutes=1, scope="s",
                                  principal_id="a", **REV)
    store.approve_window(window_id=window["window_id"], principal_id="b")
    now[0] += 60 * 10**9 - 500 * 10**6
    issued = store.issue_lease(workcell_id="c", episode_id="e", owner_session_id="o", duration_ms=2000)
    assert issued["expires_ns"] == window["requested_ns"] + 60 * 10**9
    now[0] += 500 * 10**6
    with pytest.raises(GovernanceError, match="NO_ACTIVE_EXECUTION_WINDOW"):
        store.issue_lease(workcell_id="c", episode_id="e", owner_session_id="o", duration_ms=1000)
    incident = store.report_incident(workcell_id="c", description="d", principal_id="a")
    with pytest.raises(GovernanceError, match="APPROVER_MUST_DIFFER"):
        store.clear_incident(incident_id=incident["incident_id"], note="n", principal_id="a")
