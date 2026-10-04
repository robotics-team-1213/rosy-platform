"""Markerless reference poses never dispatch motion or fabricate robot poses."""
from hashlib import sha256

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.site_auth import build_authorize, build_role_guards, SitePrincipal
from fleet.server.sightings import SightingSource
from fleet.server.tracking import TrackingService, TrackingError
from fleet.server.tracking_calibration import TrackingCalibrationStore
from fleet.server.start_points import StartPointService
from fleet.server.start_point_routes import install_start_point_routes
from test_overhead_tracking_api import APPROVAL


def service(tmp_path):
    source = SightingSource(source_id="north", token="source-token", robot_ids=(), map_id="track",
                            calibration_revision="corners", corner_marker_ids=(30, 31, 32, 33))
    tracking = TrackingService([source], calibrations=TrackingCalibrationStore(tmp_path / "cal.sqlite3"))
    tracking.approve({**APPROVAL, "source_id": "north", "map_id": "track"}, approved_by="operator")
    return StartPointService(tracking), tracking


def body(tracking, **changes):
    return {"map_id": "track", "calibration_revision": tracking.calibrations.get("north").calibration_revision,
            "expected_revision": None, "x": 1.0, "y": 0.5, "yaw": 0.0, **changes}


def test_restart_and_calibration_change_keep_reference_but_invalidate_use(tmp_path):
    points, tracking = service(tmp_path)
    saved = points.save("north", body(tracking), principal_id="op")
    assert saved["valid"] is True
    assert saved["use"] == "reference-only"
    restarted = StartPointService(tracking)
    assert restarted.listing()["start_points"] == [saved]
    tracking.approve({**APPROVAL, "source_id": "north", "map_id": "track", "frame_seq": 99}, approved_by="op")
    assert restarted.listing()["start_points"][0]["valid"] is False


def test_outside_stale_calibration_and_concurrent_edit_are_rejected(tmp_path):
    points, tracking = service(tmp_path)
    for changes, code in [({"x": -1}, "START_POINT_OUT_OF_BOUNDS"),
                          ({"calibration_revision": "old"}, "CALIBRATION_CHANGED"),
                          ({"map_id": "other"}, "MAP_MISMATCH")]:
        with pytest.raises(TrackingError) as error:
            points.save("north", body(tracking, **changes), principal_id="op")
        assert error.value.code == code
    saved = points.save("north", body(tracking), principal_id="op")
    with pytest.raises(TrackingError) as error:
        points.save("north", body(tracking, x=2), principal_id="other")
    assert error.value.code == "START_POINT_CHANGED"
    updated = points.save("north", body(tracking, expected_revision=saved["revision"], x=2), principal_id="op")
    assert updated["x"] == 2
    points.delete("north", expected_revision=updated["revision"], principal_id="op")
    assert points.listing()["start_points"] == []


def test_routes_require_operator_and_reject_boolean_or_nonfinite_pose(tmp_path):
    from fastapi import Depends
    points, tracking = service(tmp_path)
    app = FastAPI()
    users = {sha256(token.encode()).hexdigest(): {"principal_id": token, "role": role}
             for token, role in [("read", "viewer"), ("write", "operator")]}
    principals = {digest: SitePrincipal(**details) for digest, details in users.items()}
    authorize = build_authorize(console_token=None, principals=principals, task_service=None)
    viewer, operator, *_ = build_role_guards(authorize, principals)
    install_start_point_routes(app, service=points, read_guard=[Depends(viewer)], require_operator=operator)
    with TestClient(app) as client:
        path = "/api/fleet/start-points/north"
        assert client.put(path, json=body(tracking)).status_code == 401
        assert client.put(path, json=body(tracking), headers={"Authorization": "Bearer read"}).status_code == 403
        auth = {"Authorization": "Bearer write"}
        assert client.put(path, json=body(tracking, x=True), headers=auth).status_code == 422
        saved = client.put(path, json=body(tracking), headers=auth)
        assert saved.status_code == 200, saved.text
        assert client.get("/api/fleet/start-points", headers={"Authorization": "Bearer read"}).json()["start_points"][0]["x"] == 1
        assert client.delete(path+"?expected_revision=old", headers=auth).status_code == 409
