"""D-587: identified ceiling robot markers through the approved record become sightings."""

import asyncio
import logging
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from rosy_vision.project import MARKER_MOUNT_XY_M, CameraMap
from rosy_vision.publish import SightingPublishError
from rosy_vision.track import geometry
from rosy_vision.track.calibration import from_record
from rosy_vision.track.marker_sightings import robot_sightings
from rosy_vision.track.model import ROBOT_TOP_HEIGHT_M, DetectorResult
from rosy_vision.track.worker import TrackWorker

GEOMETRY = Path(__file__).resolve().parents[3] / "middleware/apps/device/pinky/profile/config/geometry.yaml"
LENS = {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 67.8}
#: The approved record of the site camera on 2026-10-10 (camera ~1.94 m above the floor).
RECORD = {
    "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-7b220d432c2a",
    "map_to_image": [196.4529389, 57.37290635, 358.1593302, -28.42073799, -264.4803023, 248.0871427,
                     -0.1086106469, 0.06958453748, 0.6833957506],
    "image": {"width": 1280, "height": 720},
    "track_bounds_m": {"min_x": -1.405, "min_y": -0.63, "max_x": 1.405, "max_y": 0.63},
    "lens": LENS,
}
CAMERA = CameraMap(
    source_id="ceiling_north", map_id="map_v2_fleet", calibration_revision="map_v2_fleet",
    processor_revision="aruco-opencv-4.12", corner_marker_ids=None,
    corner_world_m=((-1.405, -0.63), (1.405, -0.63), (1.405, 0.63), (-1.405, 0.63)),
    robot_markers={"rosy_40": 40, "rosy_41": 41}, calibration_source="field_boundary",
)
SIDE_M = 0.030


def _calibration(lens=LENS):
    return from_record(RECORD, source_id="ceiling_north", map_id="map_v2_fleet",
                       frame_size=(1280, 720), lens=lens)


def _sticker(x, y, robot_yaw, *, sticker_turn=0.0, side=SIDE_M):
    """Image corners (ArUco order, top edge first) of a sticker on a robot at (x, y, yaw)."""
    calibration = _calibration()
    matrix = geometry.as_matrix(calibration.image_to_map)
    cx, cy, height = geometry.camera_from_homography(matrix, calibration.image_size, calibration.hfov_deg)
    mx, my = MARKER_MOUNT_XY_M
    centre = (x + mx * math.cos(robot_yaw) - my * math.sin(robot_yaw),
              y + mx * math.sin(robot_yaw) + my * math.cos(robot_yaw))
    yaw = robot_yaw + sticker_turn
    half = side / 2
    # Top edge = the sticker's "front": front-left, front-right, rear-right, rear-left.
    local = ((half, half), (half, -half), (-half, -half), (-half, half))
    corners = []
    for u, v in local:
        px = centre[0] + u * math.cos(yaw) - v * math.sin(yaw)
        py = centre[1] + u * math.sin(yaw) + v * math.cos(yaw)
        # A point at the robot top is seen where the floor point further from the nadir is.
        scale = height / (height - ROBOT_TOP_HEIGHT_M)
        corners.append((cx + (px - cx) * scale, cy + (py - cy) * scale))
    image = geometry.apply(np.linalg.inv(matrix), corners)
    return tuple((float(u), float(v)) for u, v in image)


def _sightings(markers, camera=CAMERA, calibration=None, **kwargs):
    return robot_sightings(camera, calibration or _calibration(), markers,
                           captured_at=1_790_000_000.25, seq=7, **kwargs)


def test_marker_mount_follows_the_urdf_nominal_lidar_top():
    nominal = yaml.safe_load(GEOMETRY.read_text(encoding="utf-8"))
    assert MARKER_MOUNT_XY_M == (nominal["lidar"]["x_m"], nominal["lidar"]["y_m"])
    assert ROBOT_TOP_HEIGHT_M == nominal["lidar"]["height_m"]


@pytest.mark.parametrize("x, y, yaw", [(0.05, -0.52, 0.0), (-1.0, -0.53, math.pi), (0.8, 0.4, 2.0)])
def test_robot_pose_is_recovered_through_the_approved_record_with_parallax(x, y, yaw):
    [sighting] = _sightings({40: _sticker(x, y, yaw)})
    assert (sighting.x, sighting.y) == pytest.approx((x, y), abs=1e-4)
    assert math.remainder(sighting.yaw - yaw, math.tau) == pytest.approx(0.0, abs=1e-3)
    assert (sighting.robot_id, sighting.calibration_source, sighting.calibration_revision,
            sighting.corner_marker_ids, sighting.map_id, sighting.seq, sighting.quality) == (
        "rosy_40", "approved_record", "paint-7b220d432c2a", None, "map_v2_fleet", 7, None)


def test_a_turned_sticker_needs_its_yaw_offset():
    markers = {41: _sticker(0.3, 0.1, 0.5, sticker_turn=math.pi)}
    [raw] = _sightings(markers)
    assert math.remainder(raw.yaw - (0.5 + math.pi), math.tau) == pytest.approx(0.0, abs=1e-3)
    corrected = CameraMap(**{**CAMERA.__dict__, "marker_yaw_offset_deg": {"rosy_41": 180.0}})
    [sighting] = _sightings(markers, camera=corrected)
    assert math.remainder(sighting.yaw - 0.5, math.tau) == pytest.approx(0.0, abs=1e-3)
    assert (sighting.x, sighting.y) == pytest.approx((0.3, 0.1), abs=1e-4)


def test_only_assigned_markers_outside_the_skip_list_become_sightings():
    markers = {40: _sticker(0.0, 0.0, 0.0), 41: _sticker(0.5, 0.0, 0.0), 42: _sticker(-0.5, 0.0, 0.0)}
    assert sorted(s.robot_id for s in _sightings(markers)) == ["rosy_40", "rosy_41"]
    assert [s.robot_id for s in _sightings(markers, skip={"rosy_40"})] == ["rosy_41"]


def test_no_sighting_without_the_approved_record_or_a_solvable_camera():
    markers = {40: _sticker(0.0, 0.0, 0.0)}
    measured = _calibration().__class__(**{**_calibration().__dict__, "revision": "map_v2_fleet"})
    assert _sightings(markers, calibration=measured) == ()   # project_frame's measured path
    assert robot_sightings(CAMERA, None, markers, captured_at=1.0, seq=1) == ()
    assert _sightings(markers, calibration=_calibration(lens=None)) == ()  # no lens: no parallax


@pytest.mark.parametrize("bad", [
    lambda q: (q[0], q[2], q[1], q[3]),                       # crossed corners
    lambda q: tuple((q[0][0] + 4 * i, q[0][1]) for i in range(4)),  # four points on a line
])
def test_bad_corner_geometry_is_not_sent(bad):
    assert _sightings({40: bad(_sticker(0.0, 0.0, 0.3))}) == ()


def test_a_marker_far_from_the_sticker_size_or_outside_the_track_is_not_sent():
    assert len(_sightings({40: _sticker(0.0, 0.0, 0.0, side=0.036)})) == 1
    assert _sightings({40: _sticker(0.0, 0.0, 0.0, side=0.06)}) == ()     # 2x the sticker
    assert _sightings({40: _sticker(0.0, 0.0, 0.0, side=0.012)}) == ()    # also < 6 px
    assert _sightings({40: _sticker(1.6, 0.0, 0.0)}) == ()                 # beyond track bounds


class _Publisher:
    def __init__(self, error=None):
        self.sent = []
        self.error = error

    async def publish(self, sighting):
        self.sent.append(sighting)
        if self.error is not None:
            raise self.error
        return {}


class _Client:
    def __init__(self):
        self.published = []

    async def publish(self, payload):
        self.published.append(payload)
        return {"accepted": True}

    async def fetch_config(self):
        return {"source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration": RECORD,
                "relearn_seq": 0}


class _Ingest:
    def source_lens(self, source_id):
        return LENS

    def report_calibration(self, *args):
        pass


class _Detector:
    processor_revision = "background-blob/1"

    def detect(self, frame, calibration):
        return DetectorResult((), "OK")

    def reset(self):
        pass


def _run(publisher, sighted=frozenset()):
    client = _Client()
    worker = TrackWorker(camera=CAMERA, ingest=_Ingest(), client=client, detector=_Detector(),
                         decode=lambda jpeg: np.zeros((720, 1280, 3), np.uint8), sightings=publisher)
    try:
        asyncio.run(worker.refresh_config())
        frame = SimpleNamespace(header=SimpleNamespace(seq=12022), jpeg=b"jpeg",
                                captured_at=1_790_000_000.25, received_at=1_790_000_000.3)
        payload = asyncio.run(worker.process(frame, {40: _sticker(0.05, -0.52, 0.0)}, sighted))
    finally:
        worker.close()
    return payload, client


def test_track_worker_sends_the_sighting_after_the_detections():
    publisher = _Publisher()
    payload, client = _run(publisher)
    assert client.published == [payload] and [d.marker_id for d in payload.detections] == [40]
    [sighting] = publisher.sent
    assert (sighting.robot_id, sighting.seq, sighting.captured_at) == ("rosy_40", 12022, 1_790_000_000.25)


def test_track_worker_skips_robots_already_sighted_and_only_logs_a_rejection(caplog):
    publisher = _Publisher()
    _run(publisher, sighted=frozenset({"rosy_40"}))
    assert publisher.sent == []
    failing = _Publisher(SightingPublishError(409, "CALIBRATION_MISMATCH", "no"))
    with caplog.at_level(logging.WARNING, logger="rosy_vision.track"):
        payload, _ = _run(failing)
    assert payload is not None and len(failing.sent) == 1
    assert "marker sighting not accepted" in caplog.text and "CALIBRATION_MISMATCH" in caplog.text
