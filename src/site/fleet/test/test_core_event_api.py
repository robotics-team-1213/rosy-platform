from fastapi.testclient import TestClient

from core_common.protocol.schemas import Envelope, EnvelopeType, EventMessage, HelloPayload
from fakes import FakeRobot
from fleet.hub.hub import SiteHub
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.core_event_store import CoreEventStore
from fleet.swarm.robots import RobotEndpoint


def test_authenticated_event_history_survives_fleet_app_restart(tmp_path):
    endpoint = RobotEndpoint("rosy_01", "http://robot.local", "rest-token",
                             fleet_pairing_token="agent-token")
    database = tmp_path / "fleet.sqlite3"

    def make_client():
        store = CoreEventStore(database)
        hub = SiteHub([endpoint], event_store=store)
        console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
        app = create_app(console, console_token="console-token", hub=hub)
        return TestClient(app), hub

    client, hub = make_client()
    hello = HelloPayload(robot_id="rosy_01", pairing_token="agent-token")
    assert hub.handle(Envelope(type=EnvelopeType.HELLO,
                               payload=hello.model_dump())).type is EnvelopeType.WELCOME
    event = EventMessage(event_id="persisted-1", seq=1, robot_id="rosy_01",
                         type="nav.completed", source="navigation",
                         data={"goal_id": "goal-4"})
    accepted = hub.handle(Envelope(type=EnvelopeType.EVENT,
                                   payload=event.model_dump(mode="json")))
    assert accepted.payload == {"accepted": True}

    assert client.get("/api/fleet/events").status_code == 401
    response = client.get("/api/fleet/events?limit=1",
                          headers={"Authorization": "Bearer console-token"})
    assert response.status_code == 200
    assert response.json()["events"][0]["event"]["event_id"] == "persisted-1"
    assert response.json()["has_more"] is False

    client.close()
    restarted_client, _ = make_client()
    restarted = restarted_client.get(
        "/api/fleet/events?robot_id=rosy_01",
        headers={"Authorization": "Bearer console-token"},
    )
    assert restarted.status_code == 200
    assert restarted.json()["events"][0]["event"]["data"] == {"goal_id": "goal-4"}
    restarted_client.close()


def test_event_history_paginates_with_stable_audit_cursor(tmp_path):
    endpoint = RobotEndpoint("rosy_01", "http://robot.local", "rest-token",
                             fleet_pairing_token="agent-token")
    store = CoreEventStore(tmp_path / "fleet.sqlite3")
    for index in range(1, 4):
        store.append_event({
            "event_id": f"event-{index}", "seq": index, "robot_id": "rosy_01",
            "type": "nav.progress", "data": {"index": index},
        })
    hub = SiteHub([endpoint], event_store=store)
    app = create_app(FleetConsole([endpoint], [FakeRobot("rosy_01")]),
                     console_token="console-token", hub=hub)
    client = TestClient(app)
    auth = {"Authorization": "Bearer console-token"}

    first = client.get("/api/fleet/events?limit=2", headers=auth).json()
    second = client.get(f"/api/fleet/events?after_id={first['next_cursor']}&limit=2",
                        headers=auth).json()

    assert [row["event_id"] for row in first["events"]] == ["event-1", "event-2"]
    assert first["has_more"] is True
    assert [row["event_id"] for row in second["events"]] == ["event-3"]
    assert second["has_more"] is False
