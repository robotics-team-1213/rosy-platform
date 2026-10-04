"""Which calibration a frame uses for tracking (D-457 2).

Corner markers are a measurement and win when all four are in this frame; the approved
lane-paint fit from Fleet is an estimate and is used otherwise. A record for another
source or map, another lens (the lens was changed: the record is void), or another frame
aspect ratio is not used — the frame is then CALIBRATION_REQUIRED.

The Fleet record holds ``map_to_image`` for frames of ``image`` size; its inverse is the
``image_to_map`` a Calibration carries, rescaled by pixel centres to the frame's own
resolution (the same rule background_blob uses for its work image).
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

from rosy_vision.project import CameraMap, Point, marker_homography
from rosy_vision.track import geometry
from rosy_vision.track.model import Calibration

#: Same rule as the console map-fit view (map-fit.js SCALE_TOLERANCE): never stretch a fit.
ASPECT_TOLERANCE = 0.01
#: The console reads the lens back from X-Source-Lens, printed with 6 significant digits.
LENS_REL_TOL = 1e-4


def same_lens(a, b) -> bool:
    """Same lens kind, focal length and FOV (both None also counts: no lens reported)."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return (a["kind"] == b["kind"]
                and math.isclose(float(a["focal_mm"]), float(b["focal_mm"]), rel_tol=LENS_REL_TOL)
                and math.isclose(float(a["hfov_deg"]), float(b["hfov_deg"]), rel_tol=LENS_REL_TOL))
    except (KeyError, TypeError, ValueError):
        return False


def _hfov(lens) -> float | None:
    return None if lens is None else float(lens["hfov_deg"])


def from_record(record, *, source_id: str, map_id: str, frame_size: Sequence[int],
                lens) -> Calibration | None:
    """An approved Fleet record as a Calibration for frames of ``frame_size``, or None."""
    if (not isinstance(record, Mapping) or record.get("source_id") != source_id
            or record.get("map_id") != map_id or not same_lens(record.get("lens"), lens)):
        return None
    try:
        map_to_image = geometry.as_matrix(record["map_to_image"])
        width, height = int(record["image"]["width"]), int(record["image"]["height"])
        bounds = record["track_bounds_m"]
        track = (float(bounds["min_x"]), float(bounds["min_y"]),
                 float(bounds["max_x"]), float(bounds["max_y"]))
        revision = str(record["calibration_revision"])
        image_to_map = np.linalg.inv(map_to_image)
    except (KeyError, TypeError, ValueError, np.linalg.LinAlgError):
        return None
    if width <= 0 or height <= 0 or min(frame_size) <= 0:
        return None
    sx, sy = frame_size[0] / width, frame_size[1] / height
    if abs(sx / sy - 1.0) > ASPECT_TOLERANCE:
        return None
    image_to_map = geometry.normalized(image_to_map @ geometry.centre_scale(1.0 / sx, 1.0 / sy))
    try:
        return Calibration(source_id=source_id, map_id=map_id, revision=revision,
                           image_to_map=tuple(float(v) for v in image_to_map.reshape(-1)),
                           image_size=(int(frame_size[0]), int(frame_size[1])), track_bounds_m=track,
                           hfov_deg=_hfov(lens))
    except (KeyError, TypeError, ValueError):
        return None


def from_markers(camera: CameraMap, markers: Mapping[int, Sequence[Point]], *,
                 frame_size: Sequence[int], lens) -> Calibration | None:
    """The four corner markers of this frame as a Calibration, or None unless all are in view."""
    homography = marker_homography(camera, markers)
    if homography is None:
        return None
    xs = [point[0] for point in camera.corner_world_m]
    ys = [point[1] for point in camera.corner_world_m]
    try:
        return Calibration(source_id=camera.source_id, map_id=camera.map_id,
                           revision=camera.calibration_revision,
                           image_to_map=tuple(float(v) for v in homography.h),
                           image_size=(int(frame_size[0]), int(frame_size[1])),
                           track_bounds_m=(min(xs), min(ys), max(xs), max(ys)),
                           hfov_deg=_hfov(lens))
    except (KeyError, TypeError, ValueError):
        return None


def choose(camera: CameraMap, markers: Mapping[int, Sequence[Point]], record, *,
           frame_size: Sequence[int], lens) -> Calibration | None:
    """Corner markers (a measurement) win; else the approved paint fit (an estimate)."""
    marker = from_markers(camera, markers, frame_size=frame_size, lens=lens)
    if marker is not None:
        return marker
    if record is None:
        return None
    return from_record(record, source_id=camera.source_id, map_id=camera.map_id,
                       frame_size=frame_size, lens=lens)
