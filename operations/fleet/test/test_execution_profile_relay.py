"""P0-4: a device_trial parent with no local arm relays its child cells' execution profiles; production stays
closed (D-797/D-977), the relay is cached with the identity TTLs, and the child exposes it to its parent only."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from fleet.server.control_unit_information_routes import install_control_information_routes
from fleet.server.execution_profile_routes import install_execution_profile_routes
from fleet.server.site_auth import SitePrincipal

URL = "/api/fleet/execution-profile"
CHILD_URL = "/api/fleet/control-unit/execution-profile"
REV = "commissioning-r1"
GOOD = {"device": True, "commissioning_revision": REV, "instance_id": "arm-a", "workcell_id": "cell"}


def bare(profile, *, instances=None, revisions=None, transport=None, relay=None, now=None):
    app = FastAPI()
    app.state.goal_evidence_service = app.state.cell_goal_evidence_service = None
    install_execution_profile_routes(
        app, deployment_profile=profile,
        instances={"cell": "arm-a"} if instances is None else instances,
        grant_revisions={"arm-a": {"commissioning_revision": REV}} if revisions is None else revisions,
        transport=transport, workcell_observations=None, arm_transfer_observer=None,
        require_viewer=lambda: "viewer", relay_profile_fn=relay, **({} if now is None else {"monotonic": now}))
    return TestClient(app)


def test_a_child_physical_answer_lifts_the_parent_answer_with_its_revision():
    async def relay():
        return [{"arm_execution": "physical", "revision": "child-r2"}]
    body = bare("device_trial", instances={}, revisions={}, relay=relay).get(URL).json()
    assert body["arm_execution"] == "physical" and body["revision"] == "child-r2"


def test_a_child_that_is_not_physical_leaves_the_parent_closed():
    async def relay():
        return [{"arm_execution": "simulated"}, {"arm_execution": "closed"}]
    body = bare("device_trial", instances={}, revisions={}, relay=relay).get(URL).json()
    assert body["arm_execution"] == "closed"


def test_an_unreachable_child_leaves_the_parent_closed():
    async def relay():
        raise ConnectionError("child down")
    body = bare("device_trial", instances={}, revisions={}, relay=relay).get(URL).json()
    assert body["arm_execution"] == "closed" and body["revision"] is None


def test_production_stays_closed_and_never_relays():
    calls = []

    async def relay():
        calls.append(1)
        return [{"arm_execution": "physical", "revision": "child-r2"}]
    body = bare("production", instances={}, revisions={}, relay=relay).get(URL).json()
    assert body["arm_execution"] == "closed" and calls == []


def test_a_locally_proven_arm_answers_without_relay():
    class Owner:
        def owner_identity(self, instance_id):
            return GOOD

    async def relay():
        raise AssertionError("a proven local arm must not consult the children")
    body = bare("device_trial", transport=Owner(), relay=relay).get(URL).json()
    assert body["arm_execution"] == "physical" and body["revision"] == REV


def test_the_relay_answer_is_cached_with_the_identity_ttls():
    clock, calls = [0.0], []

    async def relay():
        calls.append(1)
        return [{"arm_execution": "physical", "revision": "child-r2"}]
    client = bare("device_trial", instances={}, revisions={}, relay=relay, now=lambda: clock[0])
    client.get(URL), client.get(URL)
    assert calls == [1]  # 10 s positive cache
    clock[0] = 11.0
    client.get(URL)
    assert calls == [1, 1]


def test_a_not_physical_answer_is_requeried_after_the_negative_ttl():
    clock, calls = [0.0], []

    async def relay():
        calls.append(1)
        return [{"arm_execution": "simulated"}]
    client = bare("device_trial", instances={}, revisions={}, relay=relay, now=lambda: clock[0])
    assert client.get(URL).json()["arm_execution"] == "closed"
    clock[0] = 4.0
    client.get(URL)
    assert calls == [1]  # 5 s negative cache
    clock[0] = 6.0
    client.get(URL)
    assert calls == [1, 1]


# --- the child side: the parent's control-unit credential reads it only when the child shares information ------
def _child_app(*, share=True, answer=None):
    app = FastAPI()
    if answer is not None:
        app.state.execution_profile_answer = answer
    collection = SimpleNamespace(config=SimpleNamespace(share_information_with_parent=share),
                                 unit=SimpleNamespace(parent="parent"), scope=frozenset({"child"}))
    parent = SitePrincipal("control-unit:parent", "service")

    def authorize(request: Request, authorization=None):
        request.state.site_principal = parent
        return parent

    install_control_information_routes(app, collection, authorize=authorize, require_viewer=lambda p: p)
    return TestClient(app)


async def _answer():
    return {"profile": "device_trial", "arm_execution": "physical", "revision": "child-r2",
            "observation_producers": [], "evidence_producers": [],
            "checked_at": "2026-11-25T00:00:00+00:00"}


def test_the_child_route_relays_its_own_profile_to_the_enabled_parent():
    body = _child_app(answer=_answer).get(CHILD_URL).json()
    assert body["arm_execution"] == "physical" and body["revision"] == "child-r2"


def test_the_child_route_stays_closed_without_information_sharing():
    res = _child_app(share=False, answer=_answer).get(CHILD_URL)
    assert res.status_code == 403 and res.json()["detail"]["code"] == "CONTROL_UNIT_PARENT_INFORMATION_NOT_ENABLED"


def test_the_child_route_reports_unavailable_without_the_profile_routes():
    res = _child_app().get(CHILD_URL)
    assert res.status_code == 503 and res.json()["detail"]["code"] == "CONTROL_UNIT_INFORMATION_UNAVAILABLE"
