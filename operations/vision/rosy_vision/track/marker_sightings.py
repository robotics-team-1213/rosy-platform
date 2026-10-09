"""Identified robot markers through the approved record become sightings (D-587 1-6).

The tracking step already chose this frame's Calibration. When that is the approved D-457
record (not the corner-marker measurement, whose sightings ``project_frame`` sends), each
robot marker named in ``robot_markers`` is projected corner by corner, pulled toward the
camera nadir by the robot top height, gated on its corner geometry and turned into the
robot pose under it. Without a solvable camera (no lens FOV) there is no parallax step and
no sighting. Unassigned markers and anonymous blobs never become sightings.
"""

from __future__ import annotations

import math
from typing import Collection, Mapping, Sequence

import numpy as np

from core_common.protocol.sightings import SiteSightingPayload
from rosy_vision.project import CameraMap, Point, marker_geometry_ok, robot_pose_from_marker
from rosy_vision.track import geometry
from rosy_vision.track.model import ROBOT_TOP_HEIGHT_M, Calibration

APPROVED_RECORD = "approved_record"


def robot_sightings(camera: CameraMap, calibration: Calibration | None,
                    markers: Mapping[int, Sequence[Point]], *, captured_at: float, seq: int,
                    skip: Collection[str] = ()) -> tuple[SiteSightingPayload, ...]:
    """Sightings for the configured robot markers of one frame; () unless the approved record is in use."""
    if calibration is None or calibration.revision == camera.calibration_revision:
        return ()
    matrix = geometry.as_matrix(calibration.image_to_map)
    camera_pose = geometry.camera_from_homography(matrix, calibration.image_size, calibration.hfov_deg)
    if camera_pose is None:
        return ()
    min_x, min_y, max_x, max_y = calibration.track_bounds_m
    sightings = []
    for robot_id, marker_id in camera.robot_markers.items():
        quad = markers.get(marker_id)
        if robot_id in skip or quad is None:
            continue
        try:
            pixels = np.asarray(quad, dtype=float)
        except (TypeError, ValueError):
            continue
        if pixels.shape != (4, 2) or not np.all(np.isfinite(pixels)):
            continue
        mapped = geometry.apply(matrix, pixels)
        if not np.all(np.isfinite(mapped)):
            continue
        try:
            top = [geometry.parallax_correct(point, camera_pose, ROBOT_TOP_HEIGHT_M) for point in mapped]
        except ValueError:
            continue
        if not marker_geometry_ok([tuple(p) for p in pixels.tolist()], top):
            continue
        centre = (sum(p[0] for p in top) / 4, sum(p[1] for p in top) / 4)
        if not (min_x <= centre[0] <= max_x and min_y <= centre[1] <= max_y):
            continue
        edge_a, edge_b = camera.heading_edge
        tip = ((top[edge_a][0] + top[edge_b][0]) / 2, (top[edge_a][1] + top[edge_b][1]) / 2)
        marker_yaw = math.atan2(tip[1] - centre[1], tip[0] - centre[0])
        x, y, yaw = robot_pose_from_marker((centre[0], centre[1], marker_yaw),
                                           camera.marker_yaw_offset_deg.get(robot_id, 0.0))
        if not all(math.isfinite(v) for v in (x, y, yaw)):
            continue
        sightings.append(SiteSightingPayload(
            robot_id=robot_id, x=x, y=y, yaw=yaw, captured_at=captured_at, seq=seq,
            map_id=camera.map_id, calibration_revision=calibration.revision,
            processor_revision=camera.processor_revision, quality=None,
            corner_marker_ids=None, calibration_source=APPROVED_RECORD))
    return tuple(sightings)
