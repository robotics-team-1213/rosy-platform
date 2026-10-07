import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.console_routes import install_console_routes


class Robot:
    def __init__(self):
        self.colors = []

    async def identify_lamp(self, color=None):
        self.colors.append(color)
        return {"accepted": True, "request_id": "test-request", "color": color or "blue"}


class Console:
    def __init__(self, robot):
        self.robot = robot
        # install_console_routes also builds the D-509 power-health display from these.
        self._clients = {"rosy_26": robot}
        self._clock = time.monotonic

    def clients(self):
        return dict(self._clients)


def _client(robot, moving=True):
    app = FastAPI()
    nobody = lambda: None
    velocity = {"linear": 0.1 if moving else 0.0, "angular": 0.0}
    # D-472 addendum 5: only a moving robot is asked; the tracking stub supplies its state.
    tracking = SimpleNamespace(sources=(), robot_state=lambda _rid: {"velocity": velocity})
    install_console_routes(app, console=Console(robot), sightings=None, require_viewer=nobody,
                           read_guard=[], operator_guard=[], require_operator=nobody, tracking=tracking)
    return TestClient(app)


def test_identify_is_bounded_to_one_known_robot_and_never_claims_visual_identity():
    robot = Robot()
    client = _client(robot)
    path = "/api/fleet/robots/rosy_26/identify"
    first = client.post(path)  # no body: the robot's configured colour
    assert first.status_code == 200
    assert {key: first.json()[key] for key in ("robot_id", "request_id", "color", "state")} == {
        "robot_id": "rosy_26", "request_id": "test-request", "color": "blue",
        "state": "pending_visual_confirmation"}
    busy = client.post(path, json={"color": "amber"})
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "IDENTIFY_BUSY"
    assert client.post("/api/fleet/robots/rosy_60/identify", json={"color": "blue"}).status_code == 404
    assert client.post(path, json={"color": "red"}).status_code == 422
    assert robot.colors == [None]


def test_a_parked_robot_is_not_asked():
    robot = Robot()
    answer = _client(robot, moving=False).post("/api/fleet/robots/rosy_26/identify")
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "IDENTIFY_NOT_MOVING"
    assert robot.colors == []
