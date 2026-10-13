"""D-257 sighting ingress is source-scoped, stale-aware, and cannot issue commands."""

from fastapi.testclient import TestClient
from hashlib import sha256
import pytest

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.sighting_store import SightingStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
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


def _field_payload(**changes):
    body = _payload(corner_marker_ids=None, calibration_source="field_boundary")
    body.update(changes)
    return body


def _client(*, with_source=True, source_token=SOURCE_TOKEN, store_path=None,
            field_source=False):
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    endpoints = [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest")]
    console = FleetConsole(endpoints, [robot])
    clock = _Clock()
    if with_source and field_source:
        sources = [SightingSource(
            source_id="ceiling-east",
            token=source_token,
            robot_ids=("rosy_01",),
            map_id="lane-map:sha256:abc",
            calibration_revision="ceiling-1-v2",
            corner_marker_ids=None,
            corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)),
            calibration_source="field_boundary",
        )]
    elif with_source:
        sources = [SightingSource(
            source_id="ceiling-east",
            token=source_token,
            robot_ids=("rosy_01",),
            map_id="lane-map:sha256:abc",
            calibration_revision="ceiling-1-v2",
            corner_marker_ids=(30, 31, 32, 33),
        )]
    else:
        sources = []
    store = SightingStore(store_path) if store_path is not None else None
    service = SightingService(sources, known_robot_ids=console.robot_ids, clock=clock, store=store)
    app = create_app(console, console_token=OPERATOR_TOKEN, sightings=service)
    return TestClient(app), clock


def test_field_boundary_source_accepts_markerless_sightings():
    client, _ = _client(field_source=True)
    accepted = client.post("/api/fleet/sightings", json=_field_payload(),
                           headers={"Authorization": f"Bearer {SOURCE_TOKEN}"})
    assert accepted.status_code == 200, accepted.text
    row = accepted.json()
    assert row["calibration_source"] == "field_boundary"
    assert row["corner_marker_ids"] is None

    # A marker payload on a field source is a calibration mismatch, and so is
    # a field payload on a marker source.
    marker_on_field = client.post("/api/fleet/sightings", json=_payload(seq=43),
                                  headers={"Authorization": f"Bearer {SOURCE_TOKEN}"})
    assert (marker_on_field.status_code,
            marker_on_field.json()["detail"]["code"]) == (409, "CALIBRATION_MISMATCH")


def test_field_payload_on_a_marker_source_is_a_calibration_mismatch():
    client, _ = _client()
    rejected = client.post("/api/fleet/sightings", json=_field_payload(),
                           headers={"Authorization": f"Bearer {SOURCE_TOKEN}"})
    assert (rejected.status_code,
            rejected.json()["detail"]["code"]) == (409, "CALIBRATION_MISMATCH")


def _approved_service(approved, clock):
    source = SightingSource(source_id="ceiling-east", token=SOURCE_TOKEN, robot_ids=("rosy_01",),
                            map_id="lane-map:sha256:abc", calibration_revision="ceiling-1-v2",
                            corner_marker_ids=None,
                            corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)),
                            calibration_source="field_boundary")
    seen = []

    def revision(asked):
        seen.append(asked.source_id)
        return approved

    service = SightingService([source], known_robot_ids=["rosy_01"], clock=clock,
                              approved_revision=revision)
    return service, seen


def _approved_payload(**changes):
    body = _payload(corner_marker_ids=None, calibration_source="approved_record",
                    calibration_revision="paint-7b220d432c2a")
    body.update(changes)
    return body


def test_approved_record_sighting_passes_only_with_the_current_approved_revision():
    """D-587 2: an identified marker projected through the approved record is a sighting
    when its revision is the source's approved record now; otherwise CALIBRATION_MISMATCH."""
    from core_common.protocol.sightings import SiteSightingPayload
    auth = f"Bearer {SOURCE_TOKEN}"
    service, seen = _approved_service("paint-7b220d432c2a", _Clock())
    row = service.accept(auth, SiteSightingPayload(**_approved_payload()))
    assert (row["calibration_source"], row["source_id"], seen) == (
        "approved_record", "ceiling-east", ["ceiling-east"])

    for approved, body in (("paint-000000000000", _approved_payload(captured_at=NOW - 0.05)),
                           (None, _approved_payload(captured_at=NOW - 0.05))):
        service, _ = _approved_service(approved, _Clock())
        with pytest.raises(Exception) as error:
            service.accept(auth, SiteSightingPayload(**body))
        assert (error.value.status_code, error.value.code) == (409, "CALIBRATION_MISMATCH")

    # No approved-revision provider wired: never accepted.
    plain = SightingService(service.sources, known_robot_ids=["rosy_01"], clock=_Clock())
    with pytest.raises(Exception) as error:
        plain.accept(auth, SiteSightingPayload(**_approved_payload()))
    assert error.value.code == "CALIBRATION_MISMATCH"


def test_approved_record_payload_carries_no_corner_ids_and_keeps_the_static_check():
    from pydantic import ValidationError
    from core_common.protocol.sightings import SiteSightingPayload
    with pytest.raises(ValidationError, match="approved_record sighting carries no corner"):
        SiteSightingPayload(**_approved_payload(corner_marker_ids=[30, 31, 32, 33]))
    # The static revision is not an approved-record revision.
    service, _ = _approved_service("paint-7b220d432c2a", _Clock())
    with pytest.raises(Exception) as error:
        service.accept(f"Bearer {SOURCE_TOKEN}",
                       SiteSightingPayload(**_approved_payload(calibration_revision="ceiling-1-v2")))
    assert error.value.code == "CALIBRATION_MISMATCH"


def test_field_sources_must_not_carry_corner_ids_and_need_the_world_rectangle():
    def _service(source):
        return SightingService([source], known_robot_ids=["rosy_01"])

    with pytest.raises(ValueError, match="must not carry corner marker ids"):
        _service(SightingSource(source_id="s", token="t", robot_ids=("rosy_01",),
                                map_id="m", calibration_revision="r",
                                corner_marker_ids=(30, 31, 32, 33),
                                calibration_source="field_boundary"))
    with pytest.raises(ValueError, match="corner_world_m"):
        _service(SightingSource(source_id="s", token="t", robot_ids=("rosy_01",),
                                map_id="m", calibration_revision="r",
                                corner_marker_ids=None, calibration_source="field_boundary"))


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


def test_site_user_token_cannot_be_reused_as_a_sighting_source_credential(tmp_path):
    robot = FakeRobot("rosy_01")
    console = FleetConsole(
        [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest")], [robot])
    sightings = SightingService(
        [SightingSource("ceiling-east", SOURCE_TOKEN, ("rosy_01",),
                        "lane-map:sha256:abc", "ceiling-1-v2", (30, 31, 32, 33))],
        known_robot_ids=console.robot_ids,
    )
    task_service = FleetTaskService(
        FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})

    with pytest.raises(ValueError, match="site user and sighting credentials must differ"):
        create_app(
            console, sightings=sightings, task_service=task_service,
            site_users={sha256(SOURCE_TOKEN.encode()).hexdigest(): {
                "principal_id": "viewer-1", "role": "viewer",
            }},
        )


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
