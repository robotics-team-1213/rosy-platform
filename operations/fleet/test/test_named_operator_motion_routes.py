"""D-540 9: a Fleet route that moves a robot needs a named operator; a stop stays open.

The shared console token (and anonymous loopback) is the unnamed `site-console`. It gets
403 OPERATOR_IDENTITY_REQUIRED on every moving route and still reaches every stop.
"""

from __future__ import annotations

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

R = "/api/fleet/robots/rosy_60"
SHARED = {"Authorization": "Bearer shared-token"}
NAMED = {"Authorization": "Bearer bob-token"}

MOVING = [
    (f"{R}/goal", {"x": 0.5, "y": 0.0, "yaw": 0.0}),
    (f"{R}/line-follow", {"mode": "IR_LINE"}),
    (f"{R}/route", {"edges": ["ab"]}),
    ("/api/fleet/formation/start", {"leader": "rosy_60"}),
    ("/api/fleet/formation/reform", {"formation": "COLUMN"}),
    ("/api/fleet/formation/resume", None),
    (f"{R}/line-stuck/decision", {"stuck_id": "stuck-1", "decision": "RESUME"}),
    (f"{R}/line-stuck/decision", {"stuck_id": "stuck-1", "decision": "BACK_AND_RETRY"}),
    (f"{R}/line-stuck/decision", {"stuck_id": "stuck-1", "decision": "MANUAL"}),
    ("/api/fleet/signals/sig-1/command", {"mode": "manual", "lamps": {"red": True}}),
    ("/api/fleet/signals/sig-1/command", {"mode": "cycle"}),
    ("/api/fleet/do", {"do": "navigate", "robot": "rosy_60", "x": 0.5, "y": 0.0}),
    (f"{R}/identify", {"color": "blue"}),
]

STOPS = [
    ("/api/fleet/estop", None),
    ("/api/fleet/cancel-all", None),
    (f"{R}/cancel", None),
    ("/api/fleet/trips/trip-unknown/cancel", None),
    ("/api/fleet/formation/stop", None),
    (f"{R}/line-follow", {"mode": "OFF"}),
    (f"{R}/line-stuck/decision", {"stuck_id": "stuck-1", "decision": "WAIT"}),
    (f"{R}/line-stuck/decision", {"stuck_id": "stuck-1", "decision": "ABORT"}),
    # The console claims before an ABORT confirm; a refused claim leaves the resolver answering.
    (f"{R}/line-stuck/claim", {"stuck_id": "stuck-1"}),
    ("/api/fleet/signals/sig-1/command", {"mode": "all_red"}),
    ("/api/fleet/do", {"do": "cancel", "robot": "rosy_60"}),
    ("/api/fleet/do", {"do": "estop"}),
    ("/api/fleet/do", {"do": "follow_cancel", "robot": "rosy_60"}),
]


class _Robot(FakeRobot):
    async def _post(self, path, body=None):  # /do generic robot verbs (follow_cancel)
        self.calls.append(("post", path))
        return {"accepted": True}


def _console():
    return FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")],
                        [_Robot("rosy_60")])


@pytest.fixture
def shared():
    return TestClient(create_app(_console(), console_token="shared-token"))


@pytest.fixture
def named(tmp_path):
    users = {sha256(b"bob-token").hexdigest(): {"principal_id": "bob", "role": "operator"}}
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    return TestClient(create_app(_console(), task_service=tasks, site_users=users))


def _post(client, path, body, headers):
    return client.post(path, json=body, headers=headers) if body is not None \
        else client.post(path, headers=headers)


@pytest.mark.parametrize(("path", "body"), MOVING)
def test_moving_route_refuses_the_shared_token(shared, path, body):
    response = _post(shared, path, body, SHARED)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"


@pytest.mark.parametrize(("path", "body"), MOVING)
def test_moving_route_admits_a_named_operator(named, path, body):
    response = _post(named, path, body, NAMED)
    assert response.status_code not in (401, 403), response.text


@pytest.mark.parametrize(("path", "body"), STOPS)
def test_stop_route_stays_open_to_the_shared_token(shared, path, body):
    response = _post(shared, path, body, SHARED)
    assert response.status_code not in (401, 403), response.text


def test_anonymous_loopback_is_unnamed_too():
    client = TestClient(create_app(_console()))
    assert client.post(f"{R}/goal", json={"x": 0.5, "y": 0.0}).status_code == 403
    assert client.post("/api/fleet/estop").status_code == 200


def test_dispatch_rearm_needs_a_named_operator(tmp_path):
    # Rearm reopens dispatch: queued tasks (also ones that survived a restart) start moving.
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    client = TestClient(create_app(_console(), console_token="shared-token", task_service=tasks,
                                   start_task_dispatcher=False))
    refused = client.post("/api/fleet/dispatch/rearm", json={"expected_generation": 1}, headers=SHARED)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"


def test_dispatch_rearm_admits_a_named_operator(named):
    response = named.post("/api/fleet/dispatch/rearm", json={"expected_generation": 1}, headers=NAMED)
    assert response.status_code not in (401, 403), response.text
