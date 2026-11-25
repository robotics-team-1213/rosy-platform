"""Tests for Phase 4 calibration drift evaluation, shadow rollback, and HTTP routes."""

from __future__ import annotations

from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.recalibration import RecalibrationPipeline, evaluate_candidate_drift
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.tracking import TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore, build_record
from fleet.swarm.robots import RobotEndpoint

BOUNDS = {"min_x": -1.2, "min_y": -0.6, "max_x": 1.2, "max_y": 0.6}
BASE_M2I = [320.0, 0.0, 640.0, 0.0, -320.0, 360.0, 0.0, 0.0, 1.0]
LENS_PROFILE = {
    "model": "pinhole",
    "K": [[640.0, 0.0, 640.0], [0.0, 640.0, 360.0], [0.0, 0.0, 1.0]],
    "D": [-0.15, 0.02, 0.0, 0.0, 0.0],
    "image_size": [1280, 720],
    "source": "measured",
}


def _shifted_m2i(dx_m: float, dy_m: float = 0.0) -> list[float]:
    return [320.0, 0.0, 640.0 - 320.0 * dx_m, 0.0, -320.0, 360.0 + 320.0 * dy_m, 0.0, 0.0, 1.0]


def _make_record(m2i=BASE_M2I, *, frozen=False, lens_profile=None):
    return build_record(
        source_id="ceiling_north", map_id="world_261026", map_to_image=m2i,
        image_width=1280, image_height=720, track_bounds_m=(-1.2, -0.6, 1.2, 0.6),
        lens=None, fit_score=0.98, frame_seq=1, approved_by="op", approved_at=100.0,
        lens_profile=lens_profile, frozen=frozen,
    )


def _cand(m2i, *, rms_m=0.003, spread_m=0.004, lens_profile=None, hold_reason=None):
    return {
        "map_id": "world_261026", "map_to_image": m2i,
        "image": {"width": 1280, "height": 720}, "track_bounds_m": BOUNDS,
        "fit_score": 0.98, "lens_profile": lens_profile, "rms_m": rms_m,
        "spread_m": spread_m, "hold_reason": hold_reason,
    }


def _tracking_service():
    src = SightingSource(
        source_id="ceiling_north", token="tok-src", map_id="world_261026",
        robot_ids=("rosy_45",), robot_markers={"rosy_45": 45},
    )
    return TrackingService([src], calibrations=TrackingCalibrationStore(), clock=lambda: 1000.0)


def test_evaluate_candidate_drift_supports_lens_profile():
    rec = _make_record(lens_profile=LENS_PROFILE)
    metrics = evaluate_candidate_drift(rec, _shifted_m2i(0.05), candidate_lens_profile=LENS_PROFILE)
    assert metrics is not None
    assert abs(metrics["move_m"] - 0.05) < 0.003
    assert metrics["rotation_deg"] < 0.5


def test_recalibration_auto_applies_holds_and_rolls_back_on_shadow_regression():
    now = [1000.0]
    svc = _tracking_service()
    svc.calibrations.put(_make_record())

    # 1. Small drift within cap auto-applies and arms shadow watch.
    res = svc.submit_recalibration_candidate("ceiling_north", _cand(_shifted_m2i(0.06)), principal_id="auto-cal")
    assert res["action"] == "auto_applied" and res["state"] == "AUTO_APPLIED"
    rev_auto = res["record"]["calibration_revision"]

    # 2. Two consecutive drifting health observations auto-rollback to previous revision.
    assert svc.observe_recalibration_health("ceiling_north", {"state": "drifting", "calibration_revision": rev_auto, "last": {"move_m": 0.4}}) is None
    restored = svc.observe_recalibration_health("ceiling_north", {"state": "mismatch", "calibration_revision": rev_auto, "last": {"move_m": 0.5}})
    assert restored is not None and restored["method"] == "rollback"
    assert svc.recalibration.status("ceiling_north")["state"] == "ROLLED_BACK"

    # 3. After rollback, another candidate is held for operator review rather than re-applying.
    held = svc.submit_recalibration_candidate("ceiling_north", _cand(_shifted_m2i(0.04)), principal_id="auto-cal")
    assert held["action"] == "held" and held["state"] == "ROLLED_BACK"
    assert held["pending_candidate"] is not None

    # 4. Operator accepts pending candidate -> returns to IDLE; large drift (>0.25m) is held as NEEDS_OPERATOR.
    accepted = svc.accept_recalibration_candidate("ceiling_north", approved_by="alice")
    assert accepted["recalibration"]["state"] == "IDLE"
    now[0] += 1000.0
    pipe = RecalibrationPipeline(clock=lambda: now[0])
    big = pipe.submit_candidate("ceiling_north", _cand(_shifted_m2i(0.35)), approved=_make_record(), approve_fn=lambda p: p)
    assert big["action"] == "held" and big["state"] == "NEEDS_OPERATOR" and big["reason"] == "drift_exceeds_auto_cap"


def test_recalibration_shadow_verifies_after_two_fresh_polls():
    svc = _tracking_service()
    svc.calibrations.put(_make_record())
    res = svc.submit_recalibration_candidate("ceiling_north", _cand(_shifted_m2i(0.04)), principal_id="auto-cal")
    rev = res["record"]["calibration_revision"]
    svc.observe_recalibration_health("ceiling_north", {"state": "fresh", "calibration_revision": rev, "last": {"move_m": 0.0}})
    assert svc.recalibration.status("ceiling_north")["state"] == "AUTO_APPLIED"
    svc.observe_recalibration_health("ceiling_north", {"state": "fresh", "calibration_revision": rev, "last": {"move_m": 0.0}})
    assert svc.recalibration.status("ceiling_north")["state"] == "IDLE"


def test_recalibration_candidate_accept_dismiss_and_listing_routes(tmp_path):
    src = SightingSource(source_id="ceiling_north", token="tok-src", map_id="world_261026",
                         robot_ids=("rosy_45",), robot_markers={"rosy_45": 45})
    robot = FakeRobot("rosy_45", state={"robot_id": "rosy_45", "map_id": "world_261026", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}})
    console = FleetConsole([RobotEndpoint("rosy_45", "http://127.0.0.1:8080", "robot-rest")], [robot])
    sightings = SightingService([src], known_robot_ids=console.robot_ids, clock=lambda: 1000.0)
    svc = TrackingService(sightings.sources, calibrations=TrackingCalibrationStore(), clock=lambda: 1000.0)
    svc.calibrations.put(_make_record(frozen=True))
    task_svc = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_45"})
    users = {sha256(b"op-tok").hexdigest(): {"principal_id": "op", "role": "operator"}}
    app = create_app(console, sightings=sightings, tracking=svc, task_service=task_svc, start_task_dispatcher=False, site_users=users)
    with TestClient(app) as client:
        h = {"Authorization": "Bearer op-tok"}
        r1 = client.post("/api/fleet/calibrations/ceiling_north/recalibrate/candidate", headers=h, json=_cand(_shifted_m2i(0.04)))
        assert r1.status_code == 200 and r1.json()["action"] == "held"
        assert r1.json()["reason"] == "calibration_frozen"

        listing = client.get("/api/fleet/calibrations?include_history=true", headers=h).json()
        assert listing["recalibration"]["ceiling_north"]["pending_candidate"] is not None

        r2 = client.post("/api/fleet/calibrations/ceiling_north/recalibrate/accept", headers=h)
        assert r2.status_code == 200 and r2.json()["record"]["method"] == "recal_approved"
        assert client.get("/api/fleet/calibrations?include_history=true", headers=h).json()["recalibration"]["ceiling_north"]["pending_candidate"] is None

        client.post("/api/fleet/calibrations/ceiling_north/recalibrate/candidate", headers=h, json=_cand(_shifted_m2i(0.40)))
        r3 = client.post("/api/fleet/calibrations/ceiling_north/recalibrate/dismiss", headers=h)
        assert r3.status_code == 200 and r3.json()["state"] == "IDLE" and r3.json()["pending_candidate"] is None
