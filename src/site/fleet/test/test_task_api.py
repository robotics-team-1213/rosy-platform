from threading import Event

from fastapi.testclient import TestClient

from core_common.protocol.schemas import FleetTaskStatus
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint


def test_console_goal_creates_authenticated_persistent_operator_task(tmp_path):
    endpoint = RobotEndpoint("rosy_01", "http://robot.local", "rest-token")
    task_store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    task_service = FleetTaskService(task_store, robot_ids={"rosy_01"})
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    app = create_app(console, console_token="operator-console", task_service=task_service,
                     start_task_dispatcher=False)
    client = TestClient(app)
    headers = {"Authorization": "Bearer operator-console", "Idempotency-Key": "ui-click-1"}

    response = client.post("/api/fleet/robots/rosy_01/goal",
                           json={"x": 1.0, "y": 2.0, "yaw": 0.0}, headers=headers)
    assert response.status_code == 200, response.text
    task = response.json()["task"]
    assert task["status"] == FleetTaskStatus.QUEUED.value
    assert response.json()["accepted"] is False
    assert response.json()["queued"] is True
    assert not console._client("rosy_01").calls
    assert task["source"] == "operator"
    assert task["actor_id"] == "site-console"

    assert client.get(f"/api/fleet/tasks/{task['task_id']}").status_code == 401
    readback = client.get(f"/api/fleet/tasks/{task['task_id']}",
                          headers={"Authorization": "Bearer operator-console"})
    assert readback.status_code == 200
    assert readback.json()["history"][-1]["status"] == "QUEUED"


def test_app_lifespan_dispatches_queued_task_and_readback_keeps_core_receipt_separate(tmp_path):
    endpoint = RobotEndpoint("rosy_01", "http://robot.local", "rest-token")
    robot = FakeRobot("rosy_01", state={
        "robot_id": "rosy_01", "navigation": "IDLE", "mode": "IDLE",
    })
    dispatched = Event()
    original_goal = robot.navigation_goal

    async def observe_goal(x, y, yaw=0.0):
        result = await original_goal(x, y, yaw)
        dispatched.set()
        return result

    robot.navigation_goal = observe_goal
    console = FleetConsole([endpoint], [robot])
    app = create_app(
        console, console_token="operator-console",
        task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                      robot_ids={"rosy_01"}),
    )

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer operator-console", "Idempotency-Key": "click-1"}
        response = client.post("/api/fleet/robots/rosy_01/goal", json={"x": 1, "y": 2},
                               headers=headers)
        task_id = response.json()["task"]["task_id"]

        assert response.status_code == 200
        assert response.json()["queued"] is True
        assert dispatched.wait(timeout=2)
        readback = client.get(f"/api/fleet/tasks/{task_id}", headers=headers)

    assert readback.json()["task"]["status"] == FleetTaskStatus.ACCEPTED.value
    assert readback.json()["task"]["receipt"] == {"accepted": True}
    assert [row["status"] for row in readback.json()["history"]] == [
        "REQUESTED", "QUEUED", "ACCEPTED",
    ]


def test_repeated_console_goal_with_same_key_does_not_send_second_robot_command(tmp_path):
    endpoint = RobotEndpoint("rosy_01", "http://robot.local", "rest-token")
    robot = FakeRobot("rosy_01")
    app = create_app(
        FleetConsole([endpoint], [robot]), console_token="operator-console",
        task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                      robot_ids={"rosy_01"}),
        start_task_dispatcher=False,
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer operator-console", "Idempotency-Key": "click-1"}
    body = {"x": 1.0, "y": 2.0, "yaw": 0.0}

    first = client.post("/api/fleet/robots/rosy_01/goal", json=body, headers=headers)
    second = client.post("/api/fleet/robots/rosy_01/goal", json=body, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["task"]["task_id"] == second.json()["task"]["task_id"]
    assert sum(call[0] == "navigation_goal" for call in robot.calls) == 0


def test_console_goal_requires_idempotency_key_when_task_service_is_enabled(tmp_path):
    endpoint = RobotEndpoint("rosy_01", "http://robot.local", "rest-token")
    robot = FakeRobot("rosy_01")
    client = TestClient(create_app(
        FleetConsole([endpoint], [robot]), console_token="operator-console",
        task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                      robot_ids={"rosy_01"}),
        start_task_dispatcher=False,
    ))

    response = client.post("/api/fleet/robots/rosy_01/goal",
                           json={"x": 1.0, "y": 2.0},
                           headers={"Authorization": "Bearer operator-console"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert not robot.calls


def test_reusing_console_key_for_a_different_goal_is_a_conflict(tmp_path):
    endpoint = RobotEndpoint("rosy_01", "http://robot.local", "rest-token")
    robot = FakeRobot("rosy_01")
    client = TestClient(create_app(
        FleetConsole([endpoint], [robot]), console_token="operator-console",
        task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                      robot_ids={"rosy_01"}),
        start_task_dispatcher=False,
    ))
    headers = {"Authorization": "Bearer operator-console", "Idempotency-Key": "click-1"}
    first = client.post("/api/fleet/robots/rosy_01/goal", json={"x": 1, "y": 2},
                        headers=headers)
    conflict = client.post("/api/fleet/robots/rosy_01/goal", json={"x": 9, "y": 2},
                           headers=headers)

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert sum(call[0] == "navigation_goal" for call in robot.calls) == 0


def test_intent_navigation_cannot_bypass_task_audit_or_idempotency(tmp_path):
    endpoint = RobotEndpoint("rosy_01", "http://robot.local", "rest-token")
    robot = FakeRobot("rosy_01")
    client = TestClient(create_app(
        FleetConsole([endpoint], [robot]), console_token="operator-console",
        task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                      robot_ids={"rosy_01"}),
        start_task_dispatcher=False,
    ))
    headers = {"Authorization": "Bearer operator-console", "Idempotency-Key": "intent-1"}
    body = {"do": "navigate", "robot": "rosy_01", "x": 1.0, "y": 2.0, "yaw": 0.0}

    first = client.post("/api/fleet/do", json=body, headers=headers)
    replay = client.post("/api/fleet/do", json=body, headers=headers)

    assert first.status_code == replay.status_code == 200
    first_task = first.json()["steps"][0]["result"]["task"]
    assert first_task["status"] == FleetTaskStatus.QUEUED.value
    assert first.json()["accepted"] is False and first.json()["queued"] is True
    assert replay.json()["steps"][0]["result"]["task"]["task_id"] == first_task["task_id"]
    assert sum(call[0] == "navigation_goal" for call in robot.calls) == 0


def test_intent_navigation_requires_idempotency_key_when_task_store_is_enabled(tmp_path):
    endpoint = RobotEndpoint("rosy_01", "http://robot.local", "rest-token")
    robot = FakeRobot("rosy_01")
    client = TestClient(create_app(
        FleetConsole([endpoint], [robot]), console_token="operator-console",
        task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                      robot_ids={"rosy_01"}),
        start_task_dispatcher=False,
    ))

    response = client.post("/api/fleet/do", json={
        "do": "navigate", "robot": "rosy_01", "x": 1.0, "y": 2.0,
    }, headers={"Authorization": "Bearer operator-console"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert not robot.calls
