from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.console_routes import install_console_routes


class Robot:
    def __init__(self):
        self.colors = []

    async def identify_lamp(self, color):
        self.colors.append(color)
        return {"accepted": True, "request_id": "test-request"}


class Console:
    def __init__(self, robot):
        self.robot = robot

    def clients(self):
        return {"rosy_26": self.robot}


def test_identify_is_bounded_to_one_known_robot_and_never_claims_visual_identity():
    robot = Robot()
    app = FastAPI()
    nobody = lambda: None
    install_console_routes(app, console=Console(robot), sightings=None, require_viewer=nobody,
                           read_guard=[], operator_guard=[], require_operator=nobody)
    client = TestClient(app)
    path = "/api/fleet/robots/rosy_26/identify"
    first = client.post(path, json={"color": "blue"})
    assert first.status_code == 200
    assert first.json() == {"robot_id": "rosy_26", "request_id": "test-request",
                            "state": "pending_visual_confirmation"}
    assert client.post(path, json={"color": "amber"}).status_code == 409
    assert client.post("/api/fleet/robots/rosy_60/identify", json={"color": "blue"}).status_code == 404
    assert client.post(path, json={"color": "red"}).status_code == 422
    assert robot.colors == ["blue"]
