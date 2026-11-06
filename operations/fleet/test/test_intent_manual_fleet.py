"""Named Fleet direct control respects dispatch ownership while terminal zero remains safe."""
import asyncio

import httpx
import pytest

from fakes import FakeRobot
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient
from test_server_app import _client, _named_client

ROBOT = "rosy_01"


class RecordingRobot(FakeRobot):
    async def _post(self, path, body):
        from fleet.swarm.dispatch_guard import check_dispatch
        check_dispatch(path=path)
        self.calls.append((path, body))
        return {"accepted": True}


def _setup(tmp_path, *, armed=True):
    robot = RecordingRobot(ROBOT)
    client = _named_client(tmp_path, robot)
    store = client.app.state.task_service.store
    if armed:
        store.rearm_dispatch(expected_generation=store.dispatch_control()["generation"], actor_id="bob")
    return client, store, robot


def document(verb):
    return {"do": verb, "robot": ROBOT, **({"linear": 0.02, "angular": 0.0} if verb == "move" else {})}


def pending_task(store):
    store.create_task(task_id="waiting", robot_id=ROBOT, task_type="navigate",
                      source="operator", actor_id="bob", request_key="waiting",
                      request={"x": 1.0, "y": 0.0}, evidence=None)


def claim(store):
    assert store.reserve_resources(owner_kind="mission", owner_id="other",
                                   generation=store.dispatch_control()["generation"],
                                   resources=[("robot", ROBOT)])


def assert_refused(response):
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "COMMAND_REJECTED"


def test_named_manual_forwards_only_the_fixed_mode_body(tmp_path):
    client, _store, robot = _setup(tmp_path)
    response = client.post("/api/fleet/do", json=document("manual"))
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] is True
    assert robot.calls == [("/api/v1/mode", {"mode": "MANUAL"})]


@pytest.mark.parametrize("verb", ["manual", "move"])
def test_startup_latch_blocks_new_direct_control(tmp_path, verb):
    client, _store, robot = _setup(tmp_path, armed=False)
    assert_refused(client.post("/api/fleet/do", json=document(verb)))
    assert robot.calls == []


@pytest.mark.parametrize("verb", ["manual", "move"])
@pytest.mark.parametrize("busy", ["task", "claim", "trip", "goal_pending", "queued"])
def test_unfinished_work_and_pure_trip_ownership_block_direct_control(tmp_path, monkeypatch, verb, busy):
    client, store, robot = _setup(tmp_path)
    console = client.app.state.console
    if busy == "task":
        pending_task(store)
    elif busy == "claim":
        claim(store)
    elif busy == "trip":
        monkeypatch.setattr(client.app.state.trip_runner, "robot_busy", lambda _robot: True)
    elif busy == "goal_pending":
        console._goal_busy.add(ROBOT)
    else:
        console._queued[ROBOT] = {"x": 1.0, "y": 0.0}
    assert_refused(client.post("/api/fleet/do", json=document(verb)))
    assert robot.calls == []


def test_relative_manual_does_not_require_charge_work_admission(tmp_path, monkeypatch):
    client, _store, robot = _setup(tmp_path)
    # Charge bootstrap wraps this with absolute-pose and battery-policy admission.
    monkeypatch.setattr(client.app.state.console, "trip_busy", lambda _robot: True)
    response = client.post("/api/fleet/do", json=document("manual"))
    assert response.status_code == 200, response.text
    assert robot.calls == [("/api/v1/mode", {"mode": "MANUAL"})]


@pytest.mark.parametrize("busy", ["startup", "claim", "task", "queued"])
def test_terminal_zero_keeps_named_auth_but_bypasses_control_ownership(tmp_path, busy):
    client, store, robot = _setup(tmp_path, armed=busy != "startup")
    if busy == "claim":
        claim(store)
    elif busy == "task":
        pending_task(store)
    elif busy == "queued":
        client.app.state.console._queued[ROBOT] = {"x": 1.0, "y": 0.0}
    response = client.post("/api/fleet/do", json={"do": "move", "robot": ROBOT, "linear": 0, "angular": 0})
    assert response.status_code == 200, response.text
    assert robot.calls == [("/api/v1/teleop", {"linear": 0.0, "angular": 0.0})]


@pytest.mark.parametrize("verb", ["manual", "move"])
@pytest.mark.parametrize("changed", ["stop_rearm", "task", "claim", "trip"])
def test_direct_control_rechecks_at_the_real_http_transport_boundary(tmp_path, monkeypatch, verb, changed):
    client, store, _robot = _setup(tmp_path)
    sent = []

    def change_owner():
        if changed == "stop_rearm":
            stopped = store.trip_stop_latch(actor_id="bob")
            store.rearm_dispatch(expected_generation=stopped["generation"], actor_id="bob")
        elif changed == "task":
            pending_task(store)
        elif changed == "claim":
            claim(store)
        else:
            monkeypatch.setattr(client.app.state.trip_runner, "robot_busy", lambda _robot: True)

    class RacingClient(HttpRobotClient):
        async def _post(self, path, body):
            change_owner()
            return await super()._post(path, body)

    def receive(request):
        sent.append(request)
        return httpx.Response(200, json={"accepted": True})

    http = httpx.AsyncClient(transport=httpx.MockTransport(receive))
    endpoint = RobotEndpoint(ROBOT, "http://127.0.0.1:8080", "test-token")
    client.app.state.console._clients[ROBOT] = RacingClient(endpoint, http=http)
    try:
        assert_refused(client.post("/api/fleet/do", json=document(verb)))
        assert sent == []
    finally:
        asyncio.run(http.aclose())


@pytest.mark.parametrize("body", [{"do": "manual"}, {"do": "move", "linear": 0, "angular": 0}])
def test_new_mode_and_zero_do_not_become_unnamed_operator_exceptions(body):
    robot = RecordingRobot(ROBOT)
    client = _client(robot, token="shared-console")
    response = client.post("/api/fleet/do", headers={"Authorization": "Bearer shared-console"},
                           json={**body, "robot": ROBOT})
    assert response.status_code == 403, response.text
    assert robot.calls == []
