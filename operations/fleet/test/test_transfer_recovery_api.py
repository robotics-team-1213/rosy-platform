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
