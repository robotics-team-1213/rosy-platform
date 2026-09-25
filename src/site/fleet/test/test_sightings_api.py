"""D-257 sighting ingress is source-scoped, stale-aware, and cannot issue commands."""

from fastapi.testclient import TestClient
import pytest

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.sighting_store import SightingStore
from fleet.swarm.robots import RobotEndpoint

NOW = 1_790_000_000.0
SOURCE_TOKEN = "source-camera-secret"
OPERATOR_TOKEN = "operator-secret"


class _Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def _payload(**changes):
    body = {
        "robot_id": "rosy_01",
        "x": 1.25,
        "y": -0.5,
        "yaw": 0.2,
        "captured_at": NOW - 0.1,
        "seq": 42,
        "map_id": "lane-map:sha256:abc",
        "calibration_revision": "ceiling-1-v2",
        "processor_revision": "aruco-map-v1",
        "quality": 0.98,
        "corner_marker_ids": [30, 31, 32, 33],
    }
    body.update(changes)
    return body


def _client(*, with_source=True, source_token=SOURCE_TOKEN, store_path=None):
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    endpoints = [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest")]
    console = FleetConsole(endpoints, [robot])
    clock = _Clock()
    sources = [SightingSource(
        source_id="ceiling-east",
        token=source_token,
        robot_ids=("rosy_01",),
        map_id="lane-map:sha256:abc",
        calibration_revision="ceiling-1-v2",
        corner_marker_ids=(30, 31, 32, 33),
    )] if with_source else []
    store = SightingStore(store_path) if store_path is not None else None
    service = SightingService(sources, known_robot_ids=console.robot_ids, clock=clock, store=store)
    app = create_app(console, console_token=OPERATOR_TOKEN, sightings=service)
    return TestClient(app), clock


def test_sighting_source_can_write_derived_pose_but_cannot_read_or_command():
    client, _ = _client()
    accepted = client.post("/api/fleet/sightings", json=_payload(),
                           headers={"Authorization": f"Bearer {SOURCE_TOKEN}"})
    assert accepted.status_code == 200, accepted.text
    row = accepted.json()
    assert row["source_id"] == "ceiling-east"
    assert row["robot_id"] == "rosy_01"
    assert row["seq"] == 42
    assert "jpeg" not in row and "image_url" not in row

    assert client.get("/api/fleet/sightings").status_code == 401
    assert client.get("/api/fleet/state",
                      headers={"Authorization": f"Bearer {SOURCE_TOKEN}"}).status_code == 401
    assert client.post("/api/fleet/estop",
                       headers={"Authorization": f"Bearer {SOURCE_TOKEN}"}).status_code == 401


def test_console_and_robot_tokens_cannot_write_sightings():
    client, _ = _client()
    for token in (OPERATOR_TOKEN, "robot-rest", "wrong-source"):
        response = client.post("/api/fleet/sightings", json=_payload(),
                               headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401


def test_sightings_require_configured_source_and_target_robot():
    client, _ = _client(with_source=False)
    assert client.post("/api/fleet/sightings", json=_payload(),
                       headers={"Authorization": f"Bearer {SOURCE_TOKEN}"}).status_code == 404

    client, _ = _client()
    response = client.post("/api/fleet/sightings", json=_payload(robot_id="rosy_99"),
                           headers={"Authorization": f"Bearer {SOURCE_TOKEN}"})
    assert response.status_code == 403


def test_source_credential_must_not_be_reused_as_console_credential():
    from fleet.server.sightings import SightingSource

    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest")], [robot])
    source = SightingSource("ceiling-east", OPERATOR_TOKEN, ("rosy_01",),
                            "lane-map:sha256:abc", "ceiling-1-v2", (30, 31, 32, 33))
    service = SightingService([source], known_robot_ids=console.robot_ids, clock=_Clock())
    with pytest.raises(ValueError, match="differ from the console token"):
        create_app(console, console_token=OPERATOR_TOKEN, sightings=service)

    reused_robot_token = SightingSource("ceiling-east", "rest", ("rosy_01",),
                                        "lane-map:sha256:abc", "ceiling-1-v2", (30, 31, 32, 33))
    service = SightingService([reused_robot_token], known_robot_ids=console.robot_ids, clock=_Clock())
    with pytest.raises(ValueError, match="differ from robot REST tokens"):
        create_app(console, console_token=OPERATOR_TOKEN, sightings=service)

    endpoint = RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest", "agent-pair")
    paired_console = FleetConsole([endpoint], [robot])
    reused_pair = SightingSource("ceiling-east", "agent-pair", ("rosy_01",),
                                 "lane-map:sha256:abc", "ceiling-1-v2", (30, 31, 32, 33))
    service = SightingService([reused_pair], known_robot_ids=paired_console.robot_ids, clock=_Clock())
    with pytest.raises(ValueError, match="differ from CORE Agent pairing tokens"):
        create_app(paired_console, console_token=OPERATOR_TOKEN, sightings=service)


def test_map_calibration_stale_and_future_sightings_are_rejected():
    client, _ = _client()
    headers = {"Authorization": f"Bearer {SOURCE_TOKEN}"}
    cases = [
        (_payload(map_id="other-map"), "MAP_MISMATCH"),
        (_payload(calibration_revision="old-calibration"), "CALIBRATION_MISMATCH"),
        (_payload(captured_at=NOW - 2.0), "SIGHTING_STALE"),
        (_payload(captured_at=NOW + 1.0), "SIGHTING_FUTURE"),
        (_payload(corner_marker_ids=[1, 2, 3, 4]), "CALIBRATION_MISMATCH"),
    ]
    for body, code in cases:
        response = client.post("/api/fleet/sightings", json=body, headers=headers)
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == code


def test_readback_marks_the_latest_sighting_stale_after_its_one_second_lease():
    client, clock = _client()
    headers = {"Authorization": f"Bearer {SOURCE_TOKEN}"}
    client.post("/api/fleet/sightings", json=_payload(), headers=headers)
    operator = {"Authorization": f"Bearer {OPERATOR_TOKEN}"}
    fresh = client.get("/api/fleet/sightings", headers=operator).json()["sightings"][0]
    assert fresh["stale"] is False

    clock.now += 1.2
    stale = client.get("/api/fleet/sightings", headers=operator).json()["sightings"][0]
    assert stale["stale"] is True


def test_older_capture_cannot_replace_a_newer_readback():
    client, _ = _client()
    headers = {"Authorization": f"Bearer {SOURCE_TOKEN}"}
    first = client.post("/api/fleet/sightings", json=_payload(), headers=headers)
    assert first.status_code == 200
    older = client.post("/api/fleet/sightings", json=_payload(captured_at=NOW - 0.2),
                        headers=headers)
    assert older.status_code == 409
    assert older.json()["detail"]["code"] == "SIGHTING_OUT_OF_ORDER"


def test_sighting_readback_survives_service_restart(tmp_path):
    database = tmp_path / "fleet.sqlite3"
    writer, _ = _client(store_path=database)
    accepted = writer.post("/api/fleet/sightings", json=_payload(),
                           headers={"Authorization": f"Bearer {SOURCE_TOKEN}"})
    assert accepted.status_code == 200

    restarted, _ = _client(store_path=database)
    readback = restarted.get("/api/fleet/sightings",
                             headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"})

    assert readback.status_code == 200
    row = readback.json()["sightings"][0]
    assert (row["source_id"], row["seq"], row["map_id"]) == (
        "ceiling-east", 42, "lane-map:sha256:abc")
    assert SOURCE_TOKEN.encode() not in database.read_bytes()
