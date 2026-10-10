"""Calibration-drift watch: approved record vs a fresh D-375 proposal, robots not required.

Pure verdict math (move/rotation/boundaries), the watch's keep/skip/reset lifecycle, the
Vision reader's skip paths, and the verdict riding ``/api/fleet/tracking`` source rows.
Display only (D-457): nothing here feeds sightings, goals or motion.
"""

import asyncio
import math
from hashlib import sha256

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.tracking import TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore, build_record
from fleet.server.tracking_drift import (
    CalibrationDriftWatch,
    VisionMapProposalReader,
    calibration_drift_verdict,
)
from fleet.swarm.robots import RobotEndpoint

NOW = 1_790_000_000.0
VIEWER_TOKEN = "viewer-secret"

# 640x360 image over a 6.4x3.6 m track: 100 px/m, y down.
MAP_TO_IMAGE = (100.0, 0.0, 0.0, 0.0, -100.0, 360.0, 0.0, 0.0, 1.0)
IDENTITY_I2M = ((0.01, 0.0, 0.0), (0.0, -0.01, 3.6), (0.0, 0.0, 1.0))


class _Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def _record(approved_at=1.0):
    return build_record(
        source_id="ceiling_north", map_id="map_v2_fleet", map_to_image=MAP_TO_IMAGE,
        image_width=640, image_height=360, track_bounds_m=(0.0, 0.0, 6.4, 3.6),
        lens=None, fit_score=0.81, frame_seq=12, approved_by="operator-1",
        approved_at=approved_at)


def _body(image_to_map, *, accepted=True, width=640, height=360, frame_seq=77):
    return {"source": "ceiling_north", "frame_seq": frame_seq,
            "frame_age_ms": 400, "image": {"width": width, "height": height},
            "map_frame": "map", "accepted": accepted,
            "proposal": None if not accepted else {
                "image_to_map": [list(row) for row in image_to_map],
                "map_to_image": [list(row) for row in IDENTITY_I2M],
                "score": 0.9, "precision": 0.94, "coverage": 0.9},
            "reason": "ok" if accepted else "weak paint match (0.4)"}


def _translated(metres):
    rows = [list(row) for row in IDENTITY_I2M]
    rows[0][2] += metres
    return tuple(tuple(row) for row in rows)


def _rotated_about_view_centre(degrees):
    """The same view, yawed ``degrees`` about the image centre (map point 3.2, 1.8)."""
    theta = math.radians(degrees)
    cos, sin = math.cos(theta), math.sin(theta)
    cx, cy = 3.2, 1.8

    def compose(point):
        # IDENTITY_I2M applied to the point, then the yaw about (cx, cy) in map metres.
        x = sum(a * b for a, b in zip(IDENTITY_I2M[0], (*point, 1.0)))
        y = sum(a * b for a, b in zip(IDENTITY_I2M[1], (*point, 1.0)))
        return (cos * (x - cx) - sin * (y - cy) + cx, sin * (x - cx) + cos * (y - cy) + cy)

    origin = compose((0.0, 0.0))
    ex = compose((1.0, 0.0))
    ey = compose((0.0, 1.0))
    return ((ex[0] - origin[0], ey[0] - origin[0], origin[0]),
            (ex[1] - origin[1], ey[1] - origin[1], origin[1]),
            (0.0, 0.0, 1.0))


def _source():
    return SightingSource(source_id="ceiling_north", token="source-secret",
                          robot_ids=("rosy_01",), map_id="map_v2_fleet",
                          calibration_revision="cal-v3", corner_marker_ids=(30, 31, 32, 33))


# -- pure verdict --------------------------------------------------------------


def test_an_identical_fit_is_ok():
    verdict = calibration_drift_verdict(_record(), _body(IDENTITY_I2M))
    assert verdict == {"state": "ok", "max_move_m": pytest.approx(0.0, abs=1e-6),
                       "rotation_deg": pytest.approx(0.0, abs=1e-6)}


def test_a_translated_fit_is_stale_by_move():
    verdict = calibration_drift_verdict(_record(), _body(_translated(0.5)))
    assert verdict["state"] == "stale"
    assert verdict["max_move_m"] == pytest.approx(0.5, abs=0.005)
    assert verdict["rotation_deg"] == pytest.approx(0.0, abs=0.05)


def test_a_rotated_fit_is_stale_by_rotation_before_move():
    # 3.5 deg: the far corner moves ~0.22 m (< 0.3), so only the rotation gate fires.
    verdict = calibration_drift_verdict(_record(), _body(_rotated_about_view_centre(3.5)))
    assert verdict["state"] == "stale"
    assert 3.0 < verdict["rotation_deg"] < 4.0
    assert verdict["max_move_m"] < 0.3


def test_small_differences_stay_ok_on_both_gates():
    moved = calibration_drift_verdict(_record(), _body(_translated(0.2)))
    yawed = calibration_drift_verdict(_record(), _body(_rotated_about_view_centre(1.5)))
    assert moved["state"] == "ok" and moved["max_move_m"] == pytest.approx(0.2, abs=0.005)
    assert yawed["state"] == "ok" and yawed["rotation_deg"] < 3.0


def test_a_rejected_or_foreign_proposal_is_not_evidence():
    record = _record()
    assert calibration_drift_verdict(record, _body(_translated(5.0), accepted=False)) is None
    assert calibration_drift_verdict(record, _body(_translated(5.0), width=1280)) is None
    assert calibration_drift_verdict(record, _body(_translated(5.0), height=720)) is None
    nan_fit = [[float("nan"), 0.0, 0.0], [0.0, -0.01, 3.6], [0.0, 0.0, 1.0]]
    assert calibration_drift_verdict(record, _body(nan_fit)) is None
    assert calibration_drift_verdict(record, {"accepted": False, "proposal": None}) is None
    assert calibration_drift_verdict(record, {}) is None


# -- watch lifecycle ----------------------------------------------------------


class _Fetcher:
    """Async fake: answers from a queue; records every requested source id."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def __call__(self, source_id):
        self.calls.append(source_id)
        return self.answers.pop(0) if self.answers else None


def _watch(fetcher, calibrations=None, clock=None, interval_s=60.0):
    return CalibrationDriftWatch(sources=[_source()],
                                 calibrations=calibrations or TrackingCalibrationStore(),
                                 fetch_proposal=fetcher,
                                 clock=clock or _Clock(), interval_s=interval_s)


def test_watch_records_a_verdict_and_keeps_it_through_busy_cycles():
    calibrations = TrackingCalibrationStore()
    calibrations.put(_record())
    fetcher = _Fetcher(_body(_translated(0.5)))
    watch = _watch(fetcher, calibrations)
    asyncio.run(watch.poll_once())
    verdict = watch.verdicts()["ceiling_north"]
    assert verdict["state"] == "stale" and verdict["max_move_m"] == pytest.approx(0.5, abs=0.005)
    assert verdict["calibration_revision"] == calibrations.get("ceiling_north").calibration_revision
    assert verdict["frame_seq"] == 77 and verdict["checked_at"] == NOW
    # A busy Vision (manual proposal run holds the worker) is a skip, not a change.
    asyncio.run(watch.poll_once())
    assert watch.verdicts()["ceiling_north"] == verdict


def test_a_new_approval_resets_the_verdict():
    calibrations = TrackingCalibrationStore()
    calibrations.put(_record(approved_at=1.0))
    fetcher = _Fetcher(_body(_translated(0.5)), None)
    watch = _watch(fetcher, calibrations)
    asyncio.run(watch.poll_once())
    assert watch.verdicts()["ceiling_north"]["state"] == "stale"
    calibrations.put(_record(approved_at=2.0))  # operator re-fits: old comparison is void
    asyncio.run(watch.poll_once())              # ... and Vision is busy this cycle
    assert "ceiling_north" not in watch.verdicts()


def test_a_revoked_calibration_clears_the_verdict():
    calibrations = TrackingCalibrationStore()
    calibrations.put(_record())
    fetcher = _Fetcher(_body(_translated(0.5)), None)
    watch = _watch(fetcher, calibrations)
    asyncio.run(watch.poll_once())
    assert watch.verdicts()["ceiling_north"]["state"] == "stale"
    calibrations.delete("ceiling_north", principal_id="operator-1", at=NOW)
    asyncio.run(watch.poll_once())
    assert watch.verdicts() == {}


def test_a_source_without_an_approved_calibration_is_never_fetched():
    fetcher = _Fetcher(_body(_translated(0.5)))
    watch = _watch(fetcher)  # no record in the store
    asyncio.run(watch.poll_once())
    assert fetcher.calls == []
    assert watch.verdicts() == {}


def test_watch_rejects_a_non_positive_interval():
    with pytest.raises(ValueError):
        _watch(_Fetcher(), interval_s=0.0)


# -- Vision reader ------------------------------------------------------------

SECRET = "drift-watch-test-secret-0123456789abcdef"


def _reader(handler, **kwargs):
    from core_common.protocol.vision_preview import VisionLeaseSigner
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reader = VisionMapProposalReader(base_url="https://vision:8095",
                                     signer=VisionLeaseSigner(SECRET), client=client, **kwargs)
    return reader, client


def test_reader_fetches_the_proposal_with_a_signed_lease():
    seen = {}

    def handler(request):
        seen.update(path=request.url.path, auth=request.headers.get("Authorization", ""))
        return httpx.Response(200, json=_body(_translated(0.5)))

    reader, client = _reader(handler)
    try:
        body = asyncio.run(reader("ceiling_north"))
    finally:
        asyncio.run(client.aclose())
    assert seen["path"] == "/api/vision/sources/ceiling_north/map-proposal"
    assert seen["auth"].startswith("Bearer ")
    assert body["accepted"] is True


@pytest.mark.parametrize("status", [429, 404, 401, 422, 500])
def test_reader_skips_busy_missing_or_failed_reads(status):
    def handler(request):
        return httpx.Response(status, json={})
    reader, client = _reader(handler)
    try:
        assert asyncio.run(reader("ceiling_north")) is None
    finally:
        asyncio.run(client.aclose())


def test_reader_skips_malformed_json_and_requires_an_origin():
    def handler(request):
        return httpx.Response(200, content=b"not-json\n", headers={"Content-Type": "application/json"})
    reader, client = _reader(handler)
    try:
        assert asyncio.run(reader("ceiling_north")) is None
    finally:
        asyncio.run(client.aclose())
    from core_common.protocol.vision_preview import VisionLeaseSigner
    with pytest.raises(ValueError):
        VisionMapProposalReader(base_url="http://vision.example:8095",
                                signer=VisionLeaseSigner(SECRET))
    with pytest.raises(ValueError):
        VisionMapProposalReader(base_url="https://vision:8095/frame",
                                signer=VisionLeaseSigner(SECRET))


# -- the verdict rides /api/fleet/tracking ------------------------------------


def _client(tmp_path, *, drift_provider=None):
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "map_id": "map_v2_fleet",
                                        "pose": {"x": 1.2, "y": 0.4, "yaw": 0.0}})
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest")], [robot])
    sightings = SightingService([_source()], known_robot_ids=console.robot_ids, clock=_Clock())
    tracking = TrackingService(sightings.sources, calibrations=TrackingCalibrationStore(),
                               clock=_Clock(), drift_provider=drift_provider)
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    users = {sha256(VIEWER_TOKEN.encode()).hexdigest(): {"principal_id": "viewer-1", "role": "viewer"}}
    app = create_app(console, sightings=sightings, tracking=tracking, task_service=task_service,
                     start_task_dispatcher=False, site_users=users)
    return TestClient(app)


STALE_VERDICT = {"state": "stale", "max_move_m": 0.55, "rotation_deg": 1.2,
                 "calibration_revision": "paint-test", "frame_seq": 900, "checked_at": NOW}


def test_tracking_readback_carries_the_server_drift_verdict(tmp_path):
    with _client(tmp_path, drift_provider=lambda: {"ceiling_north": STALE_VERDICT}) as client:
        sources = client.get("/api/fleet/tracking",
                             headers={"Authorization": f"Bearer {VIEWER_TOKEN}"}).json()["sources"]
    assert sources[0]["calibration_drift"] == STALE_VERDICT


def test_tracking_readback_has_a_null_drift_without_a_watch(tmp_path):
    with _client(tmp_path) as client:
        sources = client.get("/api/fleet/tracking",
                             headers={"Authorization": f"Bearer {VIEWER_TOKEN}"}).json()["sources"]
    assert sources[0]["calibration_drift"] is None


def test_the_app_refuses_a_drift_watch_without_tracking(tmp_path):
    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest")], [robot])
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    users = {sha256(VIEWER_TOKEN.encode()).hexdigest(): {"principal_id": "viewer-1", "role": "viewer"}}
    with pytest.raises(ValueError, match="calibration drift watch requires the tracking service"):
        create_app(console, task_service=task_service, site_users=users,
                   calibration_drift_watch=object())


def test_the_app_lifespan_runs_the_watch_and_closes_its_reader(tmp_path):
    import asyncio

    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest")], [robot])
    sightings = SightingService([_source()], known_robot_ids=console.robot_ids, clock=_Clock())
    tracking = TrackingService(sightings.sources, calibrations=TrackingCalibrationStore(),
                               clock=_Clock())
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    users = {sha256(VIEWER_TOKEN.encode()).hexdigest(): {"principal_id": "viewer-1", "role": "viewer"}}

    class _Watch:
        started = False
        closed = False

        async def run(self):
            _Watch.started = True
            await asyncio.sleep(3600)  # cancelled by the lifespan shutdown

        async def aclose(self):
            _Watch.closed = True

    watch = _Watch()
    app = create_app(console, sightings=sightings, tracking=tracking, task_service=task_service,
                     start_task_dispatcher=False, site_users=users,
                     calibration_drift_watch=watch)
    with TestClient(app):
        assert _Watch.started, "the lifespan never started the drift watch"
    assert _Watch.closed, "shutdown never closed the watch's reader"
