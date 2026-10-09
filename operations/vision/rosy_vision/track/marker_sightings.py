"""Identified robot markers through the approved record become sightings (D-587 1-6).

The tracking step hands over this frame's Calibration only when it is the approved D-457
record (the corner-marker measurement's sightings come from ``project_frame``). Each robot
marker named in ``robot_markers`` whose robot has a configured ``marker_yaw_offset_deg`` is
projected corner by corner, pulled toward the camera nadir by the marker height, gated on
its corner geometry and turned into the robot pose under it. A robot without a configured
offset sends nothing: an unmeasured sticker can be 90 or 180 deg off, consistently, which no
jump gate catches (D-587 4). Without a solvable camera (no lens FOV) there is no parallax
step and no sighting. Unassigned markers and anonymous blobs never become sightings.
"""

from __future__ import annotations

import math
from typing import Collection, Mapping, Sequence

import numpy as np

from core_common.protocol.sightings import SiteSightingPayload
from rosy_vision.project import (MARKER_HEIGHT_M, CameraMap, Point, marker_geometry_ok,
                                 robot_pose_from_marker)
from rosy_vision.track import geometry
from rosy_vision.track.model import Calibration

APPROVED_RECORD = "approved_record"


def marker_pose(calibration: Calibration, quad, heading_edge: tuple[int, int],
                camera_pose: tuple[float, float, float]) -> tuple[float, float, float] | None:
    """The sticker's map pose (centre x, y, heading-edge yaw) at MARKER_HEIGHT_M, or None
    when the quad fails the D-587 6 geometry gate or lies outside the track bounds."""
    try:
        pixels = np.asarray(quad, dtype=float)
    except (TypeError, ValueError):
        return None
    if pixels.shape != (4, 2) or not np.all(np.isfinite(pixels)):
        return None
    mapped = geometry.apply(geometry.as_matrix(calibration.image_to_map), pixels)
    if not np.all(np.isfinite(mapped)):
        return None
    try:
        top = [geometry.parallax_correct(point, camera_pose, MARKER_HEIGHT_M) for point in mapped]
    except ValueError:
        return None
    if not marker_geometry_ok([tuple(p) for p in pixels.tolist()], top):
        return None
    centre = (sum(p[0] for p in top) / 4, sum(p[1] for p in top) / 4)
    min_x, min_y, max_x, max_y = calibration.track_bounds_m
    if not (min_x <= centre[0] <= max_x and min_y <= centre[1] <= max_y):
        return None
    edge_a, edge_b = heading_edge
    tip = ((top[edge_a][0] + top[edge_b][0]) / 2, (top[edge_a][1] + top[edge_b][1]) / 2)
    yaw = math.atan2(tip[1] - centre[1], tip[0] - centre[0])
    return (centre[0], centre[1], yaw) if all(math.isfinite(v) for v in (*centre, yaw)) else None


def solved_camera(calibration: Calibration) -> tuple[float, float, float] | None:
    """Camera nadir and height from the calibration and lens FOV; None means no parallax step."""
    return geometry.camera_from_homography(geometry.as_matrix(calibration.image_to_map),
                                           calibration.image_size, calibration.hfov_deg)


def robot_sightings(camera: CameraMap, approved: Calibration | None,
                    markers: Mapping[int, Sequence[Point]], *, captured_at: float, seq: int,
                    skip: Collection[str] = ()) -> tuple[SiteSightingPayload, ...]:
    """Sightings for the configured robot markers of one frame. ``approved`` is the approved
    record's Calibration when this frame used it, else None (then nothing is sent)."""
    if approved is None:
        return ()
    camera_pose = solved_camera(approved)
    if camera_pose is None:
        return ()
    sightings = []
    for robot_id, marker_id in camera.robot_markers.items():
        quad = markers.get(marker_id)
        offset = camera.marker_yaw_offset_deg.get(robot_id)
        if robot_id in skip or quad is None or offset is None:
            continue
        pose = marker_pose(approved, quad, camera.heading_edge, camera_pose)
        if pose is None:
            continue
        x, y, yaw = robot_pose_from_marker(pose, offset)
        sightings.append(SiteSightingPayload(
            robot_id=robot_id, x=x, y=y, yaw=yaw, captured_at=captured_at, seq=seq,
            map_id=camera.map_id, calibration_revision=approved.revision,
            processor_revision=camera.processor_revision, quality=None,
            corner_marker_ids=None, calibration_source=APPROVED_RECORD))
    return tuple(sightings)
