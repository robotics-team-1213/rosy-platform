from concurrent.futures import ThreadPoolExecutor

import pytest

from fleet.server.physical_transfer_observations import _document
from test_physical_transfer_observer_api import (
    rig, geometry, policy, installation, approved, measured as normal_measured, OBSERVER, CONTEXT,
)
from test_arm_transfer_job_api import PATH, headers
from test_physical_transfer_recovery import measured
from test_physical_transfer_store import NOW, claims

RECOVERY_CONTEXT = "/api/fleet/arm-transfers/recovery-context"


@pytest.fixture
def failed_api(rig):
    return fail_transfer(rig)


def fail_transfer(rig):
    parent = approved(rig)
    url = PATH + "/" + parent
    context = rig.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    assert rig.client.post(url + "/observations", headers=OBSERVER,
        json=normal_measured(rig, context, phase="PRE_DISPATCH")).status_code == 200
    result = rig.port.result
    rig.port.get = lambda grant: result(grant, "FAILED", 5)
    rig.app.state.arm_transfer_dispatcher.tick()
    assert rig.client.get(url, headers=headers("harbor")).json()["job"]["status"] == "HOLD"
    rig.port.result = lambda grant, state, event: result(grant, state, event if grant.mission_id == parent else event + 10)
    rig.port.get = lambda grant: rig.port.result(grant, "SUCCEEDED", 6)
    rig.clock[0] = NOW + 1_000_000_000
    rig.parent, rig.url = parent, url
    return rig


def request_recovery(case, key="recovery-one"):
    response = case.client.get(case.url + "/recovery", headers=headers("harbor"))
    assert response.status_code == 200, response.text
    view = response.json()["recovery"]
    response = case.client.post(case.url + "/recovery", headers=headers("harbor"),
        json=dict(request_key=key, expected_context_digest=view["context_digest"]))
    assert response.status_code == 200, response.text
    return response.json()["request"]


def observe_recovery(case, intent):
    response = case.client.get(RECOVERY_CONTEXT, headers=OBSERVER)
    assert response.status_code == 200, response.text
    context = response.json()["context"]
    assert context["request_id"] == intent["request_id"] and context["execution_authorized"] is False
    snapshot = case.app.state.arm_transfer_dispatcher.execution.snapshot(case.parent)
    raw = measured(case.store, snapshot, offset=1_200_000_000, sequence=20)
    case.clock[0] = NOW + 1_500_000_000
    response = case.client.post(case.url + "/recovery/" + intent["request_id"] + "/observations", headers=OBSERVER,
        json=dict(purpose="RECOVERY_RESET", expected_proposal_digest=intent["proposal_digest"], observations=_document(raw)))
    assert response.status_code == 200, response.text
    return response.json()["evidence_digest"]


def approval(case, intent, evidence):
    return dict(expected_proposal_digest=intent["proposal_digest"], expected_evidence_digest=evidence,
                expected_generation=case.tasks.dispatch_control()["generation"])


def test_http_recovery_preserves_failure_and_reserves_only_one_child(failed_api):
    c = failed_api
    view = c.client.get(c.url + "/recovery", headers=headers("harbor")).json()["recovery"]
    assert view["can_request"] and not view["can_approve"]
    review = view["execution_review"]
    assert review["action_outcome"] == "FAILED" and review["physical_failure_cause"] is None
    assert not {"action_id", "attempt_id", "recovery", "grant"} & set(review)
    intent = request_recovery(c)
    assert request_recovery(c) == intent
    assert c.client.get(c.url + "/recovery", headers=headers("operator")).json()["recovery"]["status"] == "WAITING_OBSERVATIONS"
    evidence = observe_recovery(c, intent)
    assert c.client.get(RECOVERY_CONTEXT, headers=OBSERVER).json() == {"context": None}
    route = c.url + "/recovery/" + intent["request_id"] + "/approve"
    body = approval(c, intent, evidence)
    before = len(c.port.submitted)
    assert c.client.post(route, headers=headers("harbor"), json=body).status_code == 403
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: c.client.post(route, headers=headers("operator"), json=body), range(2)))
    assert [r.status_code for r in replies] == [200, 200]
    assert replies[0].json() == replies[1].json()
    assert set(replies[0].json()) == {"job"}
    child = replies[0].json()["job"]["mission_id"]
    assert child != c.parent and len(c.port.submitted) == before
    view = c.client.get(c.url + "/recovery", headers=headers("operator")).json()["recovery"]
    assert view["status"] == "CHILD_CREATED" and view["child_mission_id"] == child
    assert not view["can_request"] and not view["can_approve"]
    child_view = c.client.get(PATH + "/" + child + "/recovery", headers=headers("harbor")).json()["recovery"]
    assert child_view["status"] == "UNAVAILABLE" and child_view["child_mission_id"] is None
    assert c.client.post(PATH + "/" + child + "/recovery", headers=headers("harbor"),
        json=dict(request_key="grandchild", expected_context_digest="a" * 64)).status_code == 409
    assert c.client.get(c.url, headers=headers("harbor")).json()["job"]["status"] == "HOLD"
    c.port.transfer_capability = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline"))
    assert c.client.post(route, headers=headers("operator"), json=body).json() == replies[0].json()
    assert {row["owner_id"] for row in claims(c.db)} == {child}


@pytest.mark.parametrize("name,expected", [(None, 401), ("other", 403), ("operator", 403)])
def test_request_requires_the_original_authenticated_proposer(failed_api, name, expected):
    c = failed_api
    view = c.client.get(c.url + "/recovery", headers=headers("harbor")).json()["recovery"]
    assert c.client.post(c.url + "/recovery", headers={} if name is None else headers(name),
        json=dict(request_key="forgery", expected_context_digest=view["context_digest"])).status_code == expected


def test_observer_credentials_and_origin_and_closed_bodies_are_enforced(failed_api):
    c = failed_api
    assert c.client.get(RECOVERY_CONTEXT, headers=headers("operator")).status_code == 401
    view = c.client.get(c.url + "/recovery", headers=headers("harbor")).json()["recovery"]
    body = dict(request_key="forgery", expected_context_digest=view["context_digest"])
    assert c.client.post(c.url + "/recovery", headers={**headers("harbor"), "Origin": "https://foreign.invalid"}, json=body).status_code == 403
    assert c.client.post(c.url + "/recovery", headers=headers("harbor"), json={**body, "proposed_by": "operator"}).status_code == 422
    intent = request_recovery(c)
    route = c.url + "/recovery/" + intent["request_id"]
    assert c.client.post(route + "/observations", headers=headers("operator"), json={}).status_code == 401
    assert c.client.post(route + "/approve", headers=headers("operator"), json=approval(c, intent, "a" * 64)).status_code == 409


def test_stopped_dispatch_fence_blocks_capture_and_new_requests(failed_api):
    c = failed_api
    intent = request_recovery(c)
    c.tasks.close_dispatch_for_startup()
    view = c.client.get(c.url + "/recovery", headers=headers("harbor")).json()["recovery"]
    assert view["status"] == "UNAVAILABLE" and not view["can_request"]
    assert c.client.get(RECOVERY_CONTEXT, headers=OBSERVER).json() == {"context": None}
    assert c.client.post(c.url + "/recovery", headers=headers("harbor"),
        json=dict(request_key="after-stop", expected_context_digest=intent["context_digest"])).status_code == 409


def test_expired_proof_is_not_approved_or_silently_replaced(failed_api):
    c = failed_api
    intent = request_recovery(c)
    evidence = observe_recovery(c, intent)
    c.clock[0] += c.installation.policy.max_age_ns + 1
    view = c.client.get(c.url + "/recovery", headers=headers("operator")).json()["recovery"]
    assert view["status"] == "EXPIRED" and not view["can_approve"]
    assert c.client.get(RECOVERY_CONTEXT, headers=OBSERVER).json()["context"]["request_id"] == intent["request_id"]
    assert c.client.post(c.url + "/recovery/" + intent["request_id"] + "/approve", headers=headers("operator"),
                         json=approval(c, intent, evidence)).status_code == 409
    assert c.client.get(c.url + "/recovery", headers=headers("operator")).json()["recovery"]["child_mission_id"] is None


def test_http_restart_replays_retained_child_with_closed_fence_and_offline_sdk(failed_api):
    from datetime import datetime, timezone
    from hashlib import sha256
    from fastapi.testclient import TestClient
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.mission_service import MissionService
    from fleet.server.mission_store import MissionStore
    from fleet.server.proposal_store import ProposalStore
    from fleet.server.task_service import FleetTaskService
    from fleet.server.physical_transfer_observer import PhysicalTransferObserver
    from test_physical_transfer_observer_api import TOKEN

    c = failed_api
    intent = request_recovery(c)
    evidence = observe_recovery(c, intent)
    route = c.url + "/recovery/" + intent["request_id"] + "/approve"
    body = approval(c, intent, evidence)
    first = c.client.post(route, headers=headers("operator"), json=body)
    assert first.status_code == 200
    child = first.json()["job"]["mission_id"]
    users = {sha256((name + "-secret").encode()).hexdigest(): {"principal_id": name, "role": role}
             for name, role in (("harbor", "service"), ("operator", "operator"))}
    restarted = create_app(FleetConsole([], []), task_service=FleetTaskService(c.tasks, robot_ids=()),
        mission_service=MissionService(MissionStore(c.db)), proposal_store=ProposalStore(c.db), site_users=users,
        deployment_profile="simulation", omx_action_transport=c.port, arm_transfer_installation=c.installation,
        arm_transfer_observer=PhysicalTransferObserver(producer_id=c.installation.policy.producer_id,
            token=TOKEN, valid_until=datetime(2035, 1, 1, tzinfo=timezone.utc)))
    restarted.state.arm_transfer_job_store._clock_ns = lambda: c.clock[0]
    def offline(*args, **kwargs):
        raise OSError("SDK unavailable after restart")
    c.port.transfer_capability = c.port.owner_identity = offline
    assert not c.tasks.dispatch_control()["dispatch_enabled"]
    client = TestClient(restarted)
    response = client.post(route, headers=headers("operator"), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["job"]["mission_id"] == child
    view = client.get(c.url + "/recovery", headers=headers("operator")).json()["recovery"]
    assert view["status"] == "CHILD_CREATED" and view["child_mission_id"] == child
    assert not view["can_request"] and not view["can_approve"]
    assert len(c.port.submitted) == 1 and {r["owner_id"] for r in claims(c.db)} == {child}


def test_changed_task_assessment_expires_a_request_before_any_reset_proof(rig):
    c = rig
    c.parent = approved(c)
    c.url = PATH + "/" + c.parent
    context = c.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    assert c.client.post(c.url + "/observations", headers=OBSERVER,
        json=normal_measured(c, context, phase="PRE_DISPATCH")).status_code == 200
    assert c.app.state.arm_transfer_dispatcher.tick()["status"] == "ACTION_SUCCEEDED"
    state = c.app.state.arm_transfer_dispatcher.execution.snapshot(c.parent)
    def failed_assessment(offset, sequence):
        c.clock[0] = NOW + offset + 350_000_000
        return c.client.post(c.url + "/observations", headers=OBSERVER,
            json=dict(phase="POST_ACTION", expected_request_digest=state["grant"]["request_digest"],
                observations=_document(measured(c.store, state, offset=offset, sequence=sequence))))
    assert failed_assessment(800_000_000, 10).status_code == 409
    intent = request_recovery(c)
    assert failed_assessment(1_400_000_000, 12).status_code == 409
    view = c.client.get(c.url + "/recovery", headers=headers("harbor")).json()["recovery"]
    assert view["status"] == "EXPIRED" and view["reason"] == "RECOVERY_CONTEXT_CHANGED"
    assert view["context_digest"] != intent["context_digest"]
    assert view["execution_review"]["action_outcome"] == "SUCCEEDED"
    assert view["execution_review"]["task_outcome"] == "failed"
    assert c.client.get(RECOVERY_CONTEXT, headers=OBSERVER).json() == {"context": None}
    replacement = request_recovery(c, "fresh-assessment")
    assert replacement["request_id"] != intent["request_id"]


@pytest.mark.parametrize("change", ["disable", "grant"])
@pytest.mark.parametrize("created", [False, True])
def test_real_account_revocation_blocks_new_child_but_preserves_exact_replay(failed_api, change, created):
    from datetime import datetime, timezone
    from hashlib import sha256
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.mission_service import MissionService
    from fleet.server.mission_store import MissionStore
    from fleet.server.proposal_store import ProposalStore
    from fleet.server.physical_transfer_observer import PhysicalTransferObserver
    from test_physical_transfer_observer_api import TOKEN
    from test_password_session import _client, _login, HASH, ORIGIN

    c = failed_api
    users = {sha256((name + "-secret").encode()).hexdigest(): {"principal_id": name, "role": "operator"}
             for name in ("harbor", "operator")}
    logins = {name: {"principal_id": name, "role": "operator", "password_scrypt": HASH} for name in ("harbor", "manager")}
    app = create_app(FleetConsole([], []), task_service=c.app.state.task_service,
        mission_service=MissionService(MissionStore(c.db)), proposal_store=ProposalStore(c.db), site_users=users,
        site_logins=logins, accounts_bootstrap=("manager", "test-site"), deployment_profile="simulation",
        omx_action_transport=c.port, arm_transfer_installation=c.installation,
        arm_transfer_observer=PhysicalTransferObserver(producer_id=c.installation.policy.producer_id,
            token=TOKEN, valid_until=datetime(2035, 1, 1, tzinfo=timezone.utc)))
    c.app, c.client, manager = app, _client(app), _client(app)
    c.store = app.state.arm_transfer_job_store
    c.store._clock_ns = lambda: c.clock[0]
    c.port.store = c.store
    assert _login(c.client, login="harbor").status_code == 204
    assert _login(manager, login="manager").status_code == 204
    view = c.client.get(c.url + "/recovery").json()["recovery"]
    assert view["can_request"], view
    response = c.client.post(c.url + "/recovery", headers=ORIGIN,
        json=dict(request_key="account-recovery", expected_context_digest=view["context_digest"]))
    assert response.status_code == 200, response.text
    intent = response.json()["request"]
    evidence = observe_recovery(c, intent)
    route = c.url + "/recovery/" + intent["request_id"] + "/approve"
    body = approval(c, intent, evidence)
    original = None
    if created:
        response = c.client.post(route, headers={**headers("operator"), **ORIGIN}, json=body)
        assert response.status_code == 200, response.text
        original = response.json()
    row = next(r for r in manager.get("/api/fleet/auth/accounts", headers=ORIGIN).json() if r["principal_id"] == "harbor")
    changes = {"enabled": False} if change == "disable" else {"grants": [{"resource": "site:test-site", "capabilities": ["fleet.read"]}]}
    response = manager.patch("/api/fleet/auth/accounts/" + row["account_id"], headers=ORIGIN,
                              json={"revision": row["revision"], **changes})
    assert response.status_code == 200, response.text
    assert c.client.get(c.url, headers=headers("harbor")).status_code == 401
    response = c.client.post(route, headers={**headers("operator"), **ORIGIN}, json=body)
    if created:
        assert response.status_code == 200 and response.json() == original
    else:
        assert response.status_code == 403
        assert {r["owner_id"] for r in claims(c.db)} == {c.parent}
