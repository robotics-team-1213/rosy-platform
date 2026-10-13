import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.console_routes import install_console_routes


class Robot:
    def __init__(self):
        self.colors = []

    async def identify_lamp(self, color=None, quiet=False):
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
    # The tracking stub supplies the robot state (D-596: moving or not, it is asked).
    tracking = SimpleNamespace(sources=(), robot_state=lambda _rid: {"velocity": velocity})
    install_console_routes(app, console=Console(robot), sightings=None, require_viewer=nobody,
                           read_guard=[], operator_guard=[], require_operator=nobody,
                           require_named_operator=nobody, tracking=tracking)
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
    assert robot.colors == ["blue"]  # D-596 7: Fleet names blue first


def test_a_parked_robot_is_asked_too():
    """D-596 1: identify never needs a move; the robot is not told to move."""
    robot = Robot()
    answer = _client(robot, moving=False).post("/api/fleet/robots/rosy_26/identify")
    assert answer.status_code == 200 and answer.json()["state"] == "pending_visual_confirmation"
    assert robot.colors == ["blue"]  # D-596 7: Fleet names blue first


def test_both_construction_paths_look_for_the_robot_at_fleet_map_pose():
    """D-596 amendment 2026-10-10: the identity service built by create_app and the one
    install_console_routes builds on its own both take the expected place from Fleet's map pose."""
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole

    app = create_app(FleetConsole([], []))
    assert app.state.identity.map_pose == app.state.map_pose.arbitrated_pose

    bridged = lambda robot_id: SimpleNamespace(x=0.962, y=-0.011, state="DEGRADED", dead_reckon_m=1.2)
    own = FastAPI()
    own.state.map_pose = SimpleNamespace(arbitrated_pose=bridged)
    nobody = lambda: None
    install_console_routes(own, console=Console(Robot()), sightings=None, require_viewer=nobody,
                           read_guard=[], operator_guard=[], require_operator=nobody,
                           require_named_operator=nobody,
                           tracking=SimpleNamespace(sources=(), robot_state=lambda _rid: {}))
    assert own.state.identity.map_pose is bridged
    assert own.state.identity.triggers.expected("rosy_26", bridged("rosy_26"))[:2] == (0.962, -0.011)
