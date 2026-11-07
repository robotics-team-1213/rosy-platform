"""D-721 Amendment: 사람 부탁 - the durable record, its routes, and the rule that an answer moves nothing."""
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from fleet.server.auth.site_auth import build_role_guards
from fleet.server.person_request_routes import install_person_request_routes
from fleet.server.person_request_store import PersonRequestStore
from rosy_account.principal import SitePrincipal, legacy_grants

PRINCIPALS = {name: SitePrincipal(pid, role, grants=legacy_grants({}))
              for name, (pid, role) in {"operator": ("alice", "operator"), "other": ("bob", "operator"),
                                        "service": ("tool-1", "service"), "viewer": ("vera", "viewer")}.items()}


class Clock:
    now = 1_800_000_000.0

    def __call__(self):
        return self.now


class Robots:
    """Only what a person request may do to a robot: show one and stop showing it. Anything else is an error."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def put(self, robot_id, record):
        if self.fail:
            raise ConnectionError("no route")
        self.calls.append(("put", robot_id, record["id"]))

    async def clear(self, robot_id, request_id):
        if self.fail:
            raise ConnectionError("no route")
        self.calls.append(("clear", robot_id, request_id))

    def __getattr__(self, name):   # goal, cancel, estop, release, mode, ... must never be reached
        raise AssertionError(f"a person request tried to call the robot: {name}")


def make(path=None, robots=None, clock=None):
    app = FastAPI()
    store = PersonRequestStore(path, wall=clock or Clock())

    def authorize(request: Request):
        return PRINCIPALS[request.headers.get("x-who", "operator")]

    viewer, _, named, proposer = build_role_guards(authorize, {"t": PRINCIPALS["operator"]})

    async def known():
        return {"r1", "r2"}
    install_person_request_routes(app, store, [Depends(viewer)], proposer, named, known, robots)
    return TestClient(app), store


def post(client, who="operator", **over):
    body = {"robot_id": "r1", "kind": "unplug_charger", "text": "충전기를 뽑아 주세요", "why": "주행을 시작해야 합니다", **over}
    return client.post("/api/fleet/person-requests", json=body, headers={"x-who": who})


def test_an_operator_or_a_service_credential_creates_a_request_a_viewer_cannot():
    client, _ = make()
    for who in ("operator", "service"):
        made = post(client, who)
        assert made.status_code == 200
        body = made.json()
        assert (body["state"], body["requested_by"], body["robot_id"]) == ("open", PRINCIPALS[who].principal_id, "r1")
        assert body["expires_at"] - body["created_at"] == pytest.approx(600.0)
    assert post(client, "viewer").status_code == 403


@pytest.mark.parametrize("over, status", [({"kind": "fly"}, 422), ({"text": ""}, 422), ({"text": "a\x00b"}, 422),
                                          ({"expires_s": 99999}, 422), ({"robot_id": "ghost"}, 404),
                                          ({"extra": 1}, 422)])
def test_a_bad_request_is_refused_and_nothing_is_stored(over, status):
    client, store = make()
    assert post(client, **over).status_code == status
    assert store.list() == []


def test_a_request_without_a_robot_is_allowed_and_a_tool_can_poll_it_by_id():
    client, _ = make()
    made = post(client, robot_id=None, kind="other").json()
    got = client.get(f"/api/fleet/person-requests/{made['id']}").json()
    assert got["state"] == "open" and got["robot_id"] is None and got["delivery"]["state"] == "no_robot"
    listed = client.get("/api/fleet/person-requests", params={"state": "open"}).json()
    assert [r["id"] for r in listed["requests"]] == [made["id"]] and listed["motion"] is False
    assert client.get("/api/fleet/person-requests/nope").status_code == 404
    assert client.get("/api/fleet/person-requests", params={"state": "bogus"}).status_code == 422


def test_only_a_named_operator_answers_and_the_answer_is_final():
    client, _ = make()
    rid = post(client).json()["id"]
    url = f"/api/fleet/person-requests/{rid}/answer"
    assert client.post(url, json={"answer": "done"}, headers={"x-who": "viewer"}).status_code == 403
    assert client.post(url, json={"answer": "done"}, headers={"x-who": "service"}).status_code == 403
    assert client.post(url, json={"answer": "start"}).status_code == 422
    done = client.post(url, json={"answer": "cannot", "note": "손이 닿지 않습니다"}).json()
    assert (done["state"], done["answered_by"], done["answer_note"], done["motion"]) == (
        "cannot", "alice", "손이 닿지 않습니다", False)
    again = client.post(url, json={"answer": "done"})
    assert again.status_code == 409 and again.json()["detail"] == {"code": "PERSON_REQUEST_NOT_OPEN", "state": "cannot"}
    assert client.post("/api/fleet/person-requests/zzz/answer", json={"answer": "done"}).status_code == 404


def test_only_the_requester_withdraws_and_only_while_open():
    client, _ = make()
    rid = post(client, "service").json()["id"]
    url = f"/api/fleet/person-requests/{rid}/withdraw"
    assert client.post(url, headers={"x-who": "operator"}).json()["detail"]["code"] == "NOT_THE_REQUESTER"
    assert client.post(url, headers={"x-who": "viewer"}).status_code == 403
    assert client.post(url, headers={"x-who": "service"}).json()["state"] == "withdrawn"
    assert client.post(url, headers={"x-who": "service"}).status_code == 409
    assert client.post(f"/api/fleet/person-requests/{rid}/answer", json={"answer": "done"}).status_code == 409


def test_an_expired_request_cannot_be_answered_and_reads_expired():
    clock = Clock()
    client, _ = make(clock=clock)
    rid = post(client, expires_s=30).json()["id"]
    clock.now += 31
    assert client.get(f"/api/fleet/person-requests/{rid}").json()["state"] == "expired"
    refused = client.post(f"/api/fleet/person-requests/{rid}/answer", json={"answer": "done"})
    assert refused.status_code == 409 and refused.json()["detail"]["state"] == "expired"


def test_requests_and_answers_survive_a_restart(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    client, _ = make(path)
    keep, answered = post(client).json()["id"], post(client, kind="plug_charger").json()["id"]
    client.post(f"/api/fleet/person-requests/{answered}/answer", json={"answer": "done"})
    client2, _ = make(path)   # a new process on the same database
    assert client2.get(f"/api/fleet/person-requests/{keep}").json()["state"] == "open"
    assert client2.get(f"/api/fleet/person-requests/{answered}").json()["state"] == "done"


def test_answering_commands_no_robot_it_only_stops_the_robot_showing_the_request():
    robots = Robots()
    client, _ = make(robots=robots)
    rid = post(client).json()["id"]
    assert robots.calls == [("put", "r1", rid)]
    answer = client.post(f"/api/fleet/person-requests/{rid}/answer", json={"answer": "done"})
    assert answer.status_code == 200 and answer.json()["delivery"]["state"] == "cleared"
    # a strict fake: goal, cancel, estop, release, mode or any other call raises AssertionError
    assert robots.calls == [("put", "r1", rid), ("clear", "r1", rid)]


def test_withdrawing_reaches_nothing_but_the_request_holder():
    robots = Robots()
    client, _ = make(robots=robots)
    rid = post(client, "service").json()["id"]
    client.post(f"/api/fleet/person-requests/{rid}/withdraw", headers={"x-who": "service"})
    assert [c[0] for c in robots.calls] == ["put", "clear"]


def test_a_failed_delivery_is_shown_as_not_delivered_not_as_delivered():
    client, _ = make(robots=Robots(fail=True))
    body = post(client).json()
    assert body["state"] == "open"   # the console still asks the person
    assert body["delivery"]["state"] == "not_delivered" and body["delivery"]["error"] == "ConnectionError"
    answered = client.post(f"/api/fleet/person-requests/{body['id']}/answer", json={"answer": "done"}).json()
    assert answered["delivery"]["state"] == "clear_failed"   # the robot may still hold it; CORE drops it at expiry


def test_without_a_robot_gateway_a_request_is_not_sent_and_says_so():
    client, _ = make()
    assert post(client).json()["delivery"]["state"] == "not_sent"


# ---- delivery to the robot over the real client ---------------------------------------------

def test_the_robot_client_puts_and_clears_only_the_request_holder_with_its_own_token():
    import asyncio
    import httpx
    from fleet.server.station_recovery_routes import RobotRequests
    from fleet.swarm.robots import RobotEndpoint
    from fleet.swarm.transport import HttpRobotClient

    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, request.headers["authorization"],
                     request.content.decode() if request.content else ""))
        return httpx.Response(200, json={"ok": True})

    endpoint = RobotEndpoint("r1", "http://robot:8080", "fleet-token")
    client = HttpRobotClient(endpoint, http=httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                                              base_url=endpoint.base_url))
    gateway = RobotRequests({"r1": client}, wall=lambda: 100.0)
    record = {"id": "a" * 32, "kind": "plug_charger", "text": "t", "why": "w", "expires_at": 160.0}
    asyncio.run(gateway.put("r1", record))
    asyncio.run(gateway.clear("r1", record["id"]))
    assert [(m, p, a) for m, p, a, _ in seen] == [("PUT", "/api/v1/person-request", "Bearer fleet-token"),
                                                  ("DELETE", f"/api/v1/person-request/{'a' * 32}", "Bearer fleet-token")]
    import json
    assert json.loads(seen[0][3]) == {"request_id": "a" * 32, "kind": "plug_charger", "text": "t", "why": "w",
                                      "ttl_s": 60.0}
    with pytest.raises(KeyError):   # a robot with no client is a failed delivery, not a delivered one
        asyncio.run(gateway.put("ghost", record))


def test_an_unreachable_robot_through_the_real_gateway_reads_not_delivered():
    from fleet.server.station_recovery_routes import RobotRequests

    class Down:
        async def person_request_put(self, body):
            raise ConnectionError("down")

    client, _ = make(robots=RobotRequests({"r1": Down()}))
    body = post(client).json()
    assert body["delivery"]["state"] == "not_delivered" and body["state"] == "open"
