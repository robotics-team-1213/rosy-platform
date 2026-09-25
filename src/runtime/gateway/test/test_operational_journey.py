"""Local single-robot journey. Real API/managers, recording ROS port; not physical acceptance."""
import time

from core_features.command.manager import Twist

ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


class NavigationPort:
    def __init__(self):
        self.goals, self.cancels = [], 0

    def send_goal(self, goal):
        self.goals.append(goal)

    def cancel_goal(self):
        self.cancels += 1


def test_boot_teleop_disconnect_navigation_estop_and_restart(core_client):
    client, services = core_client()
    port = NavigationPort()
    services.nav.executor = port
    assert client.get("/api/v1/system/info", headers=VIEWER).status_code == 200
    assert services.command.select_output() == Twist()
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=VIEWER).status_code == 403
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert client.post("/api/v1/teleop", json={"linear": 0.05, "angular": 0}, headers=OPERATOR).status_code == 200
    assert services.command.select_output().linear == 0.05
    assert services.command.select_output(now=time.monotonic() + 0.6) == Twist()
    goal = client.post("/api/v1/navigation/goal", json={"x": 1, "y": 0, "yaw": 0}, headers=OPERATOR)
    assert goal.status_code == 200, goal.text
    assert len(port.goals) == 1 and port.goals[0].x == 1
    services.command.set_nav_twist(Twist(0.05, 0))
    assert services.command.select_output().linear == 0.05
    assert client.post("/api/v1/safety/stop", headers=VIEWER).status_code == 200
    assert services.command.select_output() == Twist()
    assert client.post("/api/v1/safety/release", headers=OPERATOR).status_code == 403
    assert client.post("/api/v1/safety/release", headers=ADMIN).status_code == 200
    assert services.command.select_output() == Twist()
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert port.cancels >= 1
    restarted_client, restarted = core_client()
    assert restarted_client.get("/api/v1/system/info", headers=VIEWER).status_code == 200
    assert restarted.command.select_output() == Twist()
