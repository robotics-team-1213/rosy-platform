"""D-457 routes: Vision writes and reads with its source token; the console reads and approves."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.tracking import TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore
from fleet.swarm.robots import RobotEndpoint

NOW = 1_790_000_000.0
SOURCE_TOKEN = "north-source-secret"
OPERATOR_TOKEN = "operator-secret"
VIEWER_TOKEN = "viewer-secret"
FIXTURE = json.loads((Path(__file__).resolve().parents[3]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
OK = next(case for case in FIXTURE["cases"] if case["id"] == "ok_two_detections")["payload"]
APPROVAL = {
    "source_id": "ceiling_north",
    "map_to_image": [100.0, 0.0, 0.0, 0.0, -100.0, 360.0, 0.0, 0.0, 1.0],
    "image": {"width": 640, "height": 360},
    "track_bounds_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 6.4, "max_y": 3.6},
    "fit_score": 0.81, "lens": None, "frame_seq": 12,
}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _source():
    return SightingSource(source_id="ceiling_north", token=SOURCE_TOKEN, robot_ids=("rosy_01",),
                          map_id="map_v2_fleet", calibration_revision="cal-v3",
                          corner_marker_ids=(30, 31, 32, 33))


class _Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class _SlowRobot(FakeRobot):
    """A robot whose state read takes ``delay_s`` of the shared clock."""

    def __init__(self, *args, clock, delay_s, **kwargs):
        super().__init__(*args, **kwargs)
        self._clock = clock
        self._delay_s = delay_s

    async def state(self) -> dict:
        self._clock.now += self._delay_s
        return await super().state()


def _client(tmp_path, *, clock=None, delay_s=0.0):
    clock = clock or _Clock()
    robot = _SlowRobot("rosy_01", state={"robot_id": "rosy_01", "map_id": "map_v2_fleet",
                                         "pose": {"x": 1.2, "y": 0.4, "yaw": 0.0}},
                       clock=clock, delay_s=delay_s)
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest")], [robot])
    sightings = SightingService([_source()], known_robot_ids=console.robot_ids, clock=clock)
    tracking = TrackingService(sightings.sources, calibrations=TrackingCalibrationStore(), clock=clock)
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    users = {
        sha256(OPERATOR_TOKEN.encode()).hexdigest(): {"principal_id": "operator-1", "role": "operator"},
        sha256(VIEWER_TOKEN.encode()).hexdigest(): {"principal_id": "viewer-1", "role": "viewer"},
    }
    app = create_app(console, sightings=sightings, tracking=tracking, task_service=task_service,
                     start_task_dispatcher=False, site_users=users)
    return TestClient(app)


def _detections(**changes):
    return {**OK, "calibration_revision": "cal-v3", "captured_at": NOW - 0.1, **changes}


def test_vision_writes_detections_and_reads_only_its_own_config(tmp_path):
    with _client(tmp_path) as client:
        accepted = client.post("/api/fleet/detections", json=_detections(), headers=_auth(SOURCE_TOKEN))
        assert accepted.status_code == 200, accepted.text
        assert accepted.json() == {"accepted": True, "source_id": "ceiling_north", "seq": 41, "status": "OK"}
        config = client.get("/api/fleet/detections/config", headers=_auth(SOURCE_TOKEN))
        assert config.json() == {"source_id": "ceiling_north", "map_id": "map_v2_fleet",
                                 "calibration": None, "relearn_seq": 0}
        assert client.get("/api/fleet/detections/config").status_code == 401
        assert client.get("/api/fleet/tracking", headers=_auth(SOURCE_TOKEN)).status_code == 401
        assert client.post("/api/fleet/calibrations", json=APPROVAL,
                           headers=_auth(SOURCE_TOKEN)).status_code == 401


@pytest.mark.parametrize("extra", [{"robot_id": "rosy_01"}, {"image": "AAAA"}])
def test_payload_with_a_robot_id_or_image_is_refused(tmp_path, extra):
    with _client(tmp_path) as client:
        response = client.post("/api/fleet/detections", json=_detections(**extra),
                               headers=_auth(SOURCE_TOKEN))
    assert response.status_code == 422


def test_operator_approves_viewer_reads_and_vision_sees_the_record(tmp_path):
    with _client(tmp_path) as client:
        assert client.post("/api/fleet/calibrations", json=APPROVAL,
                           headers=_auth(VIEWER_TOKEN)).status_code == 403
        approved = client.post("/api/fleet/calibrations", json=APPROVAL, headers=_auth(OPERATOR_TOKEN))
        assert approved.status_code == 200, approved.text
        record = approved.json()
        assert record["approved_by"] == "operator-1" and record["use"] == "display-only"
        listing = client.get("/api/fleet/calibrations", headers=_auth(VIEWER_TOKEN)).json()
        assert listing == {"calibrations": [record], "use": "display-only"}
        assert client.get("/api/fleet/detections/config",
                          headers=_auth(SOURCE_TOKEN)).json()["calibration"] == record
        mismatch = client.post("/api/fleet/detections",
                               json=_detections(calibration_revision="paint-000000000000"),
                               headers=_auth(SOURCE_TOKEN))
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "CALIBRATION_MISMATCH"
        fitted = client.post("/api/fleet/detections",
                             json=_detections(calibration_revision=record["calibration_revision"]),
                             headers=_auth(SOURCE_TOKEN))
        assert fitted.status_code == 200, fitted.text
        assert client.delete("/api/fleet/calibrations/ceiling_north",
                             headers=_auth(VIEWER_TOKEN)).status_code == 403
        assert client.delete("/api/fleet/calibrations/ceiling_north",
                             headers=_auth(OPERATOR_TOKEN)).json() == {"source_id": "ceiling_north",
                                                                       "removed": True}


def test_bad_approval_bodies_are_refused(tmp_path):
    with _client(tmp_path) as client:
        for body, status in [({**APPROVAL, "map_to_image": [1.0] * 8}, 422),
                             ({**APPROVAL, "extra": 1}, 422),
                             ({**APPROVAL, "map_to_image": [0.0] * 9}, 422),
                             ({**APPROVAL, "source_id": "nope"}, 404),
                             ({**APPROVAL, "map_id": "other_map"}, 409)]:
            response = client.post("/api/fleet/calibrations", json=body, headers=_auth(OPERATOR_TOKEN))
            assert response.status_code == status, (body, response.text)


def test_tracking_pairs_the_console_state_with_detections(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/api/fleet/state", headers=_auth(VIEWER_TOKEN)).status_code == 200
        client.post("/api/fleet/detections", json=_detections(), headers=_auth(SOURCE_TOKEN))
        snap = client.get("/api/fleet/tracking", headers=_auth(VIEWER_TOKEN)).json()
    assert [(row["robot_id"], row["status"]) for row in snap["robots"]] == [("rosy_01", "MATCHED")]
    assert snap["robots"][0]["pose_frame_verified"] is False
    assert [(row["x"], row["y"]) for row in snap["unknown"]] == [(2.5, 1.0)]


def test_state_is_aged_from_before_the_robot_reads(tmp_path):
    clock = _Clock()
    with _client(tmp_path, clock=clock, delay_s=2.5) as client:
        assert client.get("/api/fleet/state", headers=_auth(VIEWER_TOKEN)).status_code == 200
        client.post("/api/fleet/detections", json=_detections(captured_at=clock.now - 0.1),
                    headers=_auth(SOURCE_TOKEN))
        snap = client.get("/api/fleet/tracking", headers=_auth(VIEWER_TOKEN)).json()
    assert [(row["robot_id"], row["status"]) for row in snap["robots"]] == [("rosy_01", "NO_POSE")]


def test_relearn_is_an_operator_action(tmp_path, caplog):
    caplog.set_level("INFO", logger="fleet.server.tracking_routes")
    with _client(tmp_path) as client:
        body = {"source_id": "ceiling_north"}
        assert client.post("/api/fleet/tracking/relearn", json=body,
                           headers=_auth(VIEWER_TOKEN)).status_code == 403
        response = client.post("/api/fleet/tracking/relearn", json=body, headers=_auth(OPERATOR_TOKEN))
        assert response.json() == {"source_id": "ceiling_north", "relearn_seq": 1}
        assert client.post("/api/fleet/tracking/relearn", json={"source_id": "nope"},
                           headers=_auth(OPERATOR_TOKEN)).status_code == 404
        assert client.get("/api/fleet/detections/config",
                          headers=_auth(SOURCE_TOKEN)).json()["relearn_seq"] == 1
    logged = [record.getMessage() for record in caplog.records
              if record.name == "fleet.server.tracking_routes"]
    assert any("ceiling_north" in line and "relearn_seq=1" in line and "operator-1" in line
               for line in logged), logged
    assert not any(token in line for line in logged
                   for token in (SOURCE_TOKEN, OPERATOR_TOKEN, VIEWER_TOKEN))


def test_tracking_routes_are_exactly_these_and_name_no_media(tmp_path):
    with _client(tmp_path) as client:
        paths = {route.path for route in client.app.routes if hasattr(route, "path")}
    ours = {path for path in paths
            if any(word in path for word in ("detections", "tracking", "calibrations"))}
    assert ours == {"/api/fleet/detections", "/api/fleet/detections/config", "/api/fleet/tracking",
                    "/api/fleet/tracking/relearn", "/api/fleet/calibrations",
                    "/api/fleet/calibrations/{source_id}"}


def test_tracking_needs_the_sighting_sources():
    tracking = TrackingService([_source()], calibrations=TrackingCalibrationStore())
    with pytest.raises(ValueError, match="sighting sources"):
        create_app(FleetConsole([], []), tracking=tracking)
