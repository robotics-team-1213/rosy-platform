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
    """A model of CORE's one-request holder plus the only calls a person request may make: show, read, clear.
    Anything else (goal, cancel, estop, release, mode, ...) raises AssertionError."""

    def __init__(self, fail=False):
        self.calls, self.fail, self.held, self.on_put = [], fail, None, None

    async def put(self, robot_id, record):
        if self.fail:
            raise ConnectionError("no route")
        if self.on_put:
            self.on_put(record)   # something happens while the PUT is in flight
        self.calls.append(("put", robot_id, record["id"]))
        self.held = {"id": record["id"]}   # CORE keeps one: a new id replaces the old

    async def clear(self, robot_id, request_id):
        if self.fail:
            raise ConnectionError("no route")
        self.calls.append(("clear", robot_id, request_id))
        if self.held and self.held["id"] == request_id:
            self.held = None

    async def read(self, robot_id):
        if self.fail:
            raise ConnectionError("no route")
        return self.held

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
    install_person_request_routes(app, store, [Depends(viewer)], proposer, named, known, robots,
                                  monotonic=store._wall)
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

# ---- the robot's screen follows the newest open request, and "shown" is only what was read back -------------

def reconcile(client):
    import asyncio
    asyncio.run(client.app.state.person_request_reconcile())


def other_post(client, who="other", **over):
    return post(client, who, **over)


def test_only_the_newest_open_request_is_on_the_robot_and_an_older_one_waits():
    robots = Robots()
    client, _ = make(robots=robots)
    first = post(client).json()
    second = other_post(client, kind="move_robot").json()
    assert robots.held["id"] == second["id"]
    states = {r["id"]: r["delivery"]["state"] for r in client.get("/api/fleet/person-requests").json()["requests"]}
    assert states == {first["id"]: "waiting", second["id"]: "delivered"}
    # answering the newest brings the older one onto the screen
    client.post(f"/api/fleet/person-requests/{second['id']}/answer", json={"answer": "done"})
    assert robots.held["id"] == first["id"]
    assert client.get(f"/api/fleet/person-requests/{first['id']}").json()["delivery"]["state"] == "delivered"


def test_a_core_restart_is_noticed_and_the_request_is_shown_again():
    clock = Clock()
    robots = Robots()
    client, _ = make(robots=robots, clock=clock)
    rid = post(client, expires_s=600).json()["id"]
    robots.held = None   # CORE restarted: the request is gone from the screen
    clock.now += 10
    reconcile(client)
    assert robots.held == {"id": rid}
    assert [c[0] for c in robots.calls] == ["put", "put"]
    assert client.get(f"/api/fleet/person-requests/{rid}").json()["delivery"]["state"] == "delivered"


def test_delivered_is_set_from_a_read_back_and_an_unreadable_robot_is_not_delivered():
    clock = Clock()
    robots = Robots()
    client, _ = make(robots=robots, clock=clock)
    rid = post(client).json()["id"]
    clock.now += 20
    assert client.get(f"/api/fleet/person-requests/{rid}").json()["delivery"]["age_s"] == 20.0   # old: the console says unknown
    reconcile(client)
    assert client.get(f"/api/fleet/person-requests/{rid}").json()["delivery"]["age_s"] == 0.0     # read back just now
    robots.fail = True
    clock.now += 10
    reconcile(client)
    assert client.get(f"/api/fleet/person-requests/{rid}").json()["delivery"]["state"] == "not_delivered"


def test_a_request_closed_while_the_put_is_in_flight_is_taken_back_and_never_marked_shown():
    robots = Robots()
    client, store = make(robots=robots)
    state = {}

    def closes(record):
        state["closed"] = store.close(record["id"], "withdrawn", by="alice")   # the requester withdraws mid-PUT

    robots.on_put = closes
    body = post(client).json()
    assert state["closed"] is not None
    assert robots.held is None   # the PUT landed and was cleared again
    final = client.get(f"/api/fleet/person-requests/{body['id']}").json()
    assert final["state"] == "withdrawn" and final["delivery"]["state"] == "cleared"


def test_a_closed_record_cannot_be_marked_delivered_and_an_open_one_cannot_be_marked_cleared():
    client, store = make()
    rid = post(client).json()["id"]
    assert store.set_delivery(rid, "cleared") is False   # still open
    store.close(rid, "withdrawn", by="alice")
    assert store.set_delivery(rid, "delivered") is False and store.set_delivery(rid, "waiting") is False
    assert store.get(rid)["delivery"]["state"] != "delivered"
    assert store.set_delivery(rid, "clear_failed", "X") is True


def test_a_failed_clear_is_retried_until_the_robot_lets_go():
    clock = Clock()
    robots = Robots()
    client, _ = make(robots=robots, clock=clock)
    rid = post(client).json()["id"]
    robots.fail = True
    client.post(f"/api/fleet/person-requests/{rid}/answer", json={"answer": "done"})
    assert client.get(f"/api/fleet/person-requests/{rid}").json()["delivery"]["state"] == "clear_failed"
    robots.fail = False
    assert robots.held == {"id": rid}   # still beeping on the robot
    clock.now += 10
    reconcile(client)
    assert robots.held is None
    assert client.get(f"/api/fleet/person-requests/{rid}").json()["delivery"]["state"] == "cleared"


def test_an_expired_request_is_not_shown_again_by_the_reconcile_step():
    clock = Clock()
    robots = Robots()
    client, _ = make(robots=robots, clock=clock)
    rid = post(client, expires_s=30).json()["id"]
    robots.held = None
    clock.now += 31
    reconcile(client)
    assert robots.held is None and [c[0] for c in robots.calls] == ["put"]
    assert client.get(f"/api/fleet/person-requests/{rid}").json()["state"] == "expired"


def test_a_repeat_from_the_same_requester_returns_the_same_request_without_another_beep():
    robots = Robots()
    client, _ = make(robots=robots)
    first = post(client).json()
    again = post(client, text="다시 부탁합니다").json()
    assert again["id"] == first["id"] and again["text"] == first["text"]
    assert [c[0] for c in robots.calls] == ["put"]   # one PUT: the screen was not asked again


def test_a_robot_holds_at_most_three_open_requests():
    client, _ = make()
    for who in ("operator", "other", "service"):
        assert post(client, who).status_code == 200
    PRINCIPALS["fourth"] = SitePrincipal("dave", "operator", grants=legacy_grants({}))
    try:
        capped = post(client, "fourth")
        elsewhere = post(client, "fourth", robot_id="r2")
    finally:
        del PRINCIPALS["fourth"]
    assert capped.status_code == 409 and capped.json()["detail"] == {"code": "TOO_MANY_OPEN_REQUESTS", "limit": 3}
    assert elsewhere.status_code == 200   # another robot is unaffected
