"""D-977: device_trial opens the neutral ARM transfer path for one arm; the real owner still moves nothing."""
from datetime import datetime, timezone
from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.local_action_transport import LocalActionUnavailable
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.work.physical_transfer_observer import PhysicalTransferObserver
from test_arm_transfer_job_api import CapabilityPort, PATH, body, headers
from test_physical_transfer_evidence import geometry, policy  # noqa: F401  (fixtures)
from test_physical_transfer_store import installation  # noqa: F401

REVISION = "commission-1"
TOKEN = "device-trial-observer-token-0123456789abcdef"


class Owner(CapabilityPort):
    """Real-owner stand-in: reports a device identity, advertises a capability, refuses every goal."""

    def __init__(self, *a):
        super().__init__(*a)
        self.submits = []

    def owner_identity(self, instance_id):
        cap = next(c for c in self.capabilities if c.instance_id == instance_id)
        return dict(device=True, workcell_id=cap.workcell_id, instance_id=instance_id, journal_id=cap.journal_id,
                    commissioning_revision=REVISION)

    def submit(self, grant):
        self.submits.append(grant)
        raise LocalActionUnavailable("owner does not accept goals")


def build(tmp_path, installation, *, profile="device_trial", revisions=True):
    db = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskStore(db)
    port = Owner(installation, db)
    users = {sha256((n + "-secret").encode()).hexdigest(): {"principal_id": n, "role": r}
             for n, r in (("harbor", "service"), ("op-a", "operator"), ("op-b", "operator"), ("viewer", "viewer"))}
    instance = installation.policy.primary[1]
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(tasks, robot_ids=()),
        mission_service=MissionService(MissionStore(db)), proposal_store=ProposalStore(db), site_users=users,
        deployment_profile=profile, omx_action_transport=port, arm_transfer_installation=installation,
        arm_transfer_observer=PhysicalTransferObserver(producer_id=installation.policy.producer_id, token=TOKEN,
                                                       valid_until=datetime(2035, 1, 1, tzinfo=timezone.utc)),
        omx_cell_grant_revisions={instance: dict(capability_revision="c", config_revision="k",
                                                 commissioning_revision=REVISION)} if revisions else None)
    tasks.rearm_dispatch(expected_generation=tasks.dispatch_control()["generation"], actor_id="op-a")
    return TestClient(app), tasks, port


def propose_and_admit(client, tasks, installed):
    job = client.post(PATH, headers=headers("harbor"), json=body(installed)).json()["job"]
    admitted = client.post(PATH + "/" + job["mission_id"] + "/admit", headers=headers("op-a"), json={
        "expected_proposal_digest": job["proposal_digest"], "expected_generation": tasks.dispatch_control()["generation"]})
    return job, admitted


def test_device_trial_prepares_for_a_device_owner_and_submits_nothing(tmp_path, installation):
    client, tasks, port = build(tmp_path, installation)
    _, admitted = propose_and_admit(client, tasks, installation)
    assert admitted.status_code == 200 and admitted.json()["job"]["status"] == "READY"
    assert port.submits == []
    # D-977: a real arm is never approved by the unattended policy worker.
    assert not hasattr(client.app.state, "arm_transfer_policy_task")


def test_simulation_owner_is_refused_by_device_trial_and_the_job_is_held_without_retry(tmp_path, installation):
    client, tasks, port = build(tmp_path, installation)
    port.owner_identity = lambda i: dict(simulation=True, workcell_id=installation.policy.primary[0], instance_id=i,
                                         journal_id="journal-" + i)
    job, admitted = propose_and_admit(client, tasks, installation)
    assert admitted.status_code == 503
    assert client.get(f"{PATH}/{job['mission_id']}", headers=headers("op-a")).json()["job"]["status"] == "HOLD"
    assert client.app.state.arm_transfer_job_store.peek(job["mission_id"])["reason"] == "PHYSICAL_PREPARATION_UNAVAILABLE"
    assert port.submits == []


def test_wrong_commissioning_revision_is_refused(tmp_path, installation):
    client, _, port = build(tmp_path, installation)
    inner = port.owner_identity
    port.owner_identity = lambda i: {**inner(i), "commissioning_revision": "other"}
    with pytest.raises(LocalActionUnavailable):
        client.app.state.arm_transfer_dispatcher._capabilities()


def test_production_and_missing_revision_stay_closed(tmp_path, installation):
    with pytest.raises(ValueError):
        build(tmp_path, installation, profile="production")
    with pytest.raises(ValueError, match="commissioning_revision"):
        build(tmp_path, installation, revisions=False)


def test_simulation_still_requires_a_simulation_owner(tmp_path, installation):
    client, _, _ = build(tmp_path, installation, profile="simulation")
    with pytest.raises(LocalActionUnavailable):
        client.app.state.arm_transfer_dispatcher._capabilities()


def att(client, mission_id, who, job, kind="SOURCE_CLEAR", **changes):
    return client.post(f"{PATH}/{mission_id}/operator-attestations", headers=headers(who), json={
        "kind": kind, "expected_request_digest": job["request_digest"],
        "expected_proposal_digest": job["proposal_digest"], **changes})


def test_operator_attestation_is_single_use_role_separated_and_never_confirms_the_goal(tmp_path, installation):
    client, tasks, port = build(tmp_path, installation)
    job, admitted = propose_and_admit(client, tasks, installation)
    mid = job["mission_id"]
    assert admitted.json()["job"]["status"] == "READY"
    assert att(client, mid, "op-a", job).status_code == 403  # the approver
    assert att(client, mid, "harbor", job).status_code == 403  # service token / proposer
    assert att(client, mid, "viewer", job).status_code == 403
    assert att(client, mid, "op-b", job, expected_request_digest="0" * 64).status_code == 409
    assert att(client, mid, "op-b", job, kind="TARGET_PLACED").status_code == 409  # wrong state
    ok = att(client, mid, "op-b", job)
    assert ok.status_code == 200
    record = ok.json()["attestation"]
    assert record["evidence_source"] == "operator_attested" and record["goal_confirmed"] is False
    assert record["attested_by"] == "op-b" and record["job_status"] == "READY"
    assert 0 < record["expires_at_ns"] - record["attested_at_ns"] < 60_000_000_000
    assert att(client, mid, "op-b", job).status_code == 409  # single use
    assert client.get(f"{PATH}/{mid}/operator-attestations", headers=headers("viewer")).status_code == 403
    listed = client.get(f"{PATH}/{mid}/operator-attestations", headers=headers("op-b")).json()["attestations"]
    assert [a["kind"] for a in listed] == ["SOURCE_CLEAR"]
    assert client.get(f"{PATH}/{mid}", headers=headers("op-b")).json()["job"]["status"] == "READY"
    assert port.submits == []


def test_attestation_route_is_absent_in_simulation(tmp_path, installation):
    client, _, _ = build(tmp_path, installation, profile="simulation")
    assert client.post(f"{PATH}/x/operator-attestations", headers=headers("op-b"), json={}).status_code in {404, 405}
