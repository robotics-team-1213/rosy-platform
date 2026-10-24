"""An independent raw observer closes a job; application credentials cannot attest facts."""
from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from test_arm_transfer_job_api import PATH, body, headers
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import NOW, installation, claims
from test_physical_transfer_dispatcher import Port
from test_physical_transfer_submission import observations

TOKEN = "independent-observer-test-credential-0001"
OBSERVER = {"X-Physical-Observation-Token": TOKEN}
CONTEXT = "/api/fleet/arm-transfers/observation-context"


def api():
    try:
        return import_module("fleet.server.physical_transfer_observer")
    except ModuleNotFoundError:
        pytest.fail("independent physical observer ingress is missing")


@pytest.fixture
def rig(tmp_path, installation, monkeypatch):
    db = tmp_path / "fleet.sqlite3"
    tasks, clock = FleetTaskStore(db), [NOW]
    port = Port(SimpleNamespace(installation=installation, _journal=SimpleNamespace(path=db)), clock)
    observer = api().PhysicalTransferObserver(producer_id=installation.policy.producer_id, token=TOKEN,
        valid_until=datetime(2035, 1, 1, tzinfo=timezone.utc))
    users = {sha256((name + "-secret").encode()).hexdigest(): {"principal_id": name, "role": role}
             for name, role in (("harbor", "service"), ("other", "service"), ("operator", "operator"))}
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(tasks, robot_ids=()),
        mission_service=MissionService(MissionStore(db)), proposal_store=ProposalStore(db), site_users=users,
        deployment_profile="simulation", omx_action_transport=port, arm_transfer_installation=installation,
        arm_transfer_observer=observer)
    store = app.state.arm_transfer_job_store
    store._clock_ns = lambda: clock[0]
    port.store = store
    monkeypatch.setattr("fleet.server.arm_transfer_job_routes.time.time_ns", lambda: clock[0])
    tasks.rearm_dispatch(expected_generation=tasks.dispatch_control()["generation"], actor_id="operator")
    return SimpleNamespace(client=TestClient(app), app=app, tasks=tasks, store=store, port=port, clock=clock,
                           installation=installation, db=db)


def approved(rig):
    response = rig.client.post(PATH, headers=headers("harbor"), json=body(rig.installation))
    assert response.status_code == 200
    job = response.json()["job"]
    response = rig.client.post(PATH + "/" + job["mission_id"] + "/admit", headers=headers("operator"),
        json=dict(expected_proposal_digest=job["proposal_digest"],
                  expected_generation=rig.tasks.dispatch_control()["generation"]))
    assert response.status_code == 200 and response.json()["job"]["status"] == "READY"
    return job["mission_id"]


def measured(rig, context, *, phase):
    from fleet.server.physical_transfer_observations import _document
    snapshot = rig.app.state.arm_transfer_dispatcher.execution.snapshot(context["mission_id"])
    raw = observations(rig.store, snapshot)
    if phase == "POST_ACTION":
        from dataclasses import replace
        boundary = context["not_before_ns"]
        raw = tuple(replace(sample, evidence_id="post-" + sample.evidence_id, sequence=sample.sequence + 10,
            object_pose=rig.installation.policy.target_pose, object_observed_at_ns=boundary + offset,
            owners=tuple(replace(owner, links_observed_at_ns=boundary + offset,
                gripper_observed_at_ns=boundary + offset) for owner in sample.owners))
            for sample, offset in zip(raw, (100_000_000, 300_000_000)))
        rig.clock[0] = boundary + 350_000_000
    else:
        rig.clock[0] += 350_000_000
    return dict(phase=phase, expected_request_digest=context["request_digest"], observations=_document(raw))


def test_independent_observer_facts_and_fleet_monitor_produce_a_physical_receipt(rig):
    client = rig.client
    assert client.get(CONTEXT, headers=OBSERVER).json() == {"context": None}
    mission = approved(rig)
    context = client.get(CONTEXT, headers=OBSERVER).json()["context"]
    assert context["mission_id"] == mission and context["phase"] == "PRE_DISPATCH"
    assert not {"source_pose", "target_pose", "resources", "token"} & set(context)
    url = PATH + "/" + mission
    assert client.get(url + "/physical-receipt", headers=headers("harbor")).status_code == 409
    request = measured(rig, context, phase="PRE_DISPATCH")
    assert client.post(url + "/observations", headers=headers("harbor"), json=request).status_code == 401
    response = client.post(url + "/observations", headers=OBSERVER, json=request)
    assert response.status_code == 200 and response.json()["receipt"] is None
    assert len(rig.port.submitted) == 1
    assert client.post(url + "/observations", headers=OBSERVER, json=request).status_code == 200
    request["observations"][0]["evidence_id"] = "different"
    assert client.post(url + "/observations", headers=OBSERVER, json=request).status_code == 409
    assert rig.app.state.arm_transfer_dispatcher.tick()["status"] == "ACTION_SUCCEEDED"
    assert {c["phase"] for c in claims(rig.db)} == {"HELD"}
    context = client.get(CONTEXT, headers=OBSERVER).json()["context"]
    post = measured(rig, context, phase="POST_ACTION")
    response = client.post(url + "/observations", headers=OBSERVER, json=post)
    assert response.status_code == 200
    confirmed = response.json()
    assert confirmed["job"]["status"] == "GOAL_CONFIRMED"
    assert confirmed["receipt"]["physical_status"] == "AT_TARGET_AND_CLEAR"
    assert client.post(url + "/observations", headers=OBSERVER, json=post).json() == confirmed
    assert client.get(url + "/physical-receipt", headers=headers("harbor")).json() == {"receipt": confirmed["receipt"]}
    assert client.get(url + "/physical-receipt", headers=headers("other")).status_code == 403
    assert len(rig.port.submitted) == 1
    assert client.get(CONTEXT, headers=OBSERVER).json() == {"context": None}
    assert not [c for c in claims(rig.db) if c["phase"] in {"CLAIMED", "DISPATCHING", "HELD", "UNKNOWN"}]
    audit = rig.tasks.api_audit()
    assert any(r["path"] == url + "/observations" and r["principal_id"] == rig.installation.policy.producer_id
               and r["status_code"] == 200 for r in audit)
    assert TOKEN not in repr(audit)


def test_cancel_and_closed_observation_errors_keep_claims_and_never_submit(rig):
    mission = approved(rig)
    context = rig.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    request = measured(rig, context, phase="PRE_DISPATCH")
    url = PATH + "/" + mission
    assert rig.client.post(url + "/observations", headers={**OBSERVER, "Origin": "https://evil.invalid"}, json=request).status_code == 403
    assert rig.client.post(url + "/observations", headers=OBSERVER, json={**request, "clear": True}).status_code == 422
    assert rig.client.post(url + "/cancel", headers=headers("other"), json={"reason": "cancel"}).status_code == 403
    response = rig.client.post(url + "/cancel", headers=headers("harbor"), json={"reason": "cancel"})
    assert response.status_code == 200 and response.json()["job"]["status"] == "HOLD"
    assert {c["phase"] for c in claims(rig.db)} == {"HELD"}
    assert rig.port.submitted == []


@pytest.mark.parametrize("token", ["", "short", " x" * 20, "a\n" * 20])
def test_observer_configuration_rejects_unsafe_tokens_without_echoing_them(token):
    with pytest.raises(ValueError) as failure:
        api().PhysicalTransferObserver(producer_id="observer", token=token,
            valid_until=datetime(2035, 1, 1, tzinfo=timezone.utc))
    assert not token or token not in str(failure.value)
