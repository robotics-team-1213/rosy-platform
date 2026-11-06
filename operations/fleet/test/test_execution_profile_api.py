"""v1.361: GET /api/fleet/execution-profile is a read-only signal; closed unless proven."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.execution_profile_routes import install_execution_profile_routes
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore

URL = "/api/fleet/execution-profile"
REV = "commissioning-r1"
GOOD = {"device": True, "commissioning_revision": REV, "instance_id": "arm-a", "workcell_id": "cell"}


class Owner:
    def __init__(self, identity):
        self.identity, self.calls = identity, 0

    def owner_identity(self, instance_id):
        self.calls += 1
        if isinstance(self.identity, Exception):
            raise self.identity
        return self.identity


def bare(profile, owner=None, *, instances=None, revisions=None, observations=None, observer=None,
         goal=None, cell=None, now=None):
    app = FastAPI()
    app.state.goal_evidence_service, app.state.cell_goal_evidence_service = goal, cell
    install_execution_profile_routes(
        app, deployment_profile=profile, instances={"cell": "arm-a"} if instances is None else instances,
        grant_revisions={"arm-a": {"commissioning_revision": REV}} if revisions is None else revisions,
        transport=owner, workcell_observations=observations, arm_transfer_observer=observer,
        require_viewer=lambda: "viewer", **({} if now is None else {"monotonic": now}))
    return TestClient(app)


def test_simulation_is_simulated_and_lists_no_producers():
    body = bare("simulation").get(URL).json()
    assert body["profile"] == "simulation" and body["arm_execution"] == "simulated"
    assert body["observation_producers"] == [] and body["evidence_producers"] == []
    assert body["revision"] == REV and datetime.fromisoformat(body["checked_at"]).tzinfo is not None


def test_production_is_closed():
    owner = Owner(GOOD)
    assert bare("production", owner).get(URL).json()["arm_execution"] == "closed"
    assert owner.calls == 0  # no owner contact outside device_trial


def test_device_trial_matching_identity_is_physical():
    assert bare("device_trial", Owner(GOOD)).get(URL).json()["arm_execution"] == "physical"


@pytest.mark.parametrize("identity", [
    {**GOOD, "commissioning_revision": "other"},          # revision mismatch
    {**GOOD, "device": False},
    {**GOOD, "device": True, "simulation": True},          # a simulation owner is never physical
    {**GOOD, "instance_id": "arm-b"},
    {k: v for k, v in GOOD.items() if k != "commissioning_revision"},
    ConnectionError("no owner socket"),
])
def test_device_trial_unproven_identity_is_closed(identity):
    assert bare("device_trial", Owner(identity)).get(URL).json()["arm_execution"] == "closed"


def test_device_trial_without_owner_or_revision_or_single_arm_is_closed():
    assert bare("device_trial", None).get(URL).json()["arm_execution"] == "closed"
    assert bare("device_trial", Owner(GOOD), revisions={"arm-a": {}}).get(URL).json()["arm_execution"] == "closed"
    two = bare("device_trial", Owner(GOOD), instances={"c1": "arm-a", "c2": "arm-b"})
    assert two.get(URL).json()["arm_execution"] == "closed"


def test_identity_answer_is_cached_not_requeried_per_poll():
    clock, owner = [0.0], Owner(GOOD)
    client = bare("device_trial", owner, now=lambda: clock[0])
    client.get(URL), client.get(URL)
    assert owner.calls == 1
    clock[0] = 11.0
    client.get(URL)
    assert owner.calls == 2


def test_only_registered_unexpired_producers_are_listed():
    future, past = (datetime.now(timezone.utc) + timedelta(hours=1), datetime.now(timezone.utc) - timedelta(hours=1))
    goal = SimpleNamespace(registry=SimpleNamespace(producers=(
        SimpleNamespace(producer_id="cam-1", evidence_source="camera_observation", valid_until=future),
        SimpleNamespace(producer_id="old", evidence_source="camera_observation", valid_until=past))))
    observations = SimpleNamespace(producers=lambda: [{"id": "arm-a-joints", "kind": "arm_joint"}])
    observer = SimpleNamespace(producer_id="obs", valid_until=past)
    body = bare("simulation", observations=observations, observer=observer, goal=goal).get(URL).json()
    assert body["evidence_producers"] == [{"id": "cam-1", "kind": "camera_observation", "authenticated": True}]
    assert body["observation_producers"] == [{"id": "arm-a-joints", "kind": "arm_joint", "authenticated": True}]


@pytest.mark.parametrize("profile,arm", [("simulation", "simulated"), ("production", "closed")])
def test_service_and_viewer_read_and_no_write_method(tmp_path, profile, arm):
    users = {sha256(token.encode()).hexdigest(): {"principal_id": token, "role": role}
             for token, role in (("svc", "service"), ("view", "viewer"))}
    app = create_app(FleetConsole([], []), deployment_profile=profile, site_users=users,
                     task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.db"), robot_ids=()))
    client = TestClient(app)
    assert client.get(URL).status_code in (401, 403)
    for token in ("svc", "view"):
        response = client.get(URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200 and response.json()["arm_execution"] == arm
        assert response.json()["observation_producers"] == [] and response.json()["evidence_producers"] == []
        for method in ("post", "put", "patch", "delete"):
            assert getattr(client, method)(URL, headers={"Authorization": f"Bearer {token}"}).status_code == 405
