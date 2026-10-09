"""Project ArUco marker observations into a configured site map (D-257)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from core_common.protocol.place_markers import PlaceMarkerPayload, PlaceMarkerPose
from core_common.protocol.sightings import SiteSightingPayload
from games.field.homography import Homography, Point, fit

MarkerQuad = tuple[Point, Point, Point, Point]

#: D-587 4: nominal sticker centre on the robot (base_footprint x, y in m) is the top of the
#: LiDAR, the robot top D-457 3 uses (geometry.yaml lidar x_m / y_m; drift-tested in
#: test_marker_sightings.py). Per-robot yaw offsets come from the site config.
MARKER_MOUNT_XY_M = (-0.017, 0.0)
#: D-562: the black square of the 40 mm robot sticker (one white cell border).
MARKER_SIDE_M = 0.030
#: D-587 6: corner geometry a robot marker must have to become a sighting.
MIN_MARKER_SIDE_PX = 6.0
MARKER_SIDE_BAND = (0.6, 1.4)
MAX_MARKER_SIDE_RATIO = 1.33


@dataclass(frozen=True)
class CameraMap:
    """Reviewed camera-to-map calibration and marker assignment for one source."""

    source_id: str
    map_id: str
    calibration_revision: str
    processor_revision: str
    corner_marker_ids: tuple[int, int, int, int] | None
    corner_world_m: tuple[Point, Point, Point, Point]
    robot_markers: Mapping[str, int]
    heading_edge: tuple[int, int] = (0, 1)
    #: D-484: where this frame's image-to-map homography is measured from.
    #: "corner_markers" (default) needs four ArUco corners per frame;
    #: "field_boundary" gets it from the accepted field quad + orientation.
    calibration_source: str = "corner_markers"
    #: D-564: floor place marker ids (height 0, so no parallax), teach input only.
    place_markers: tuple[int, ...] = ()
    #: D-587 4: robot id -> sticker top edge direction from the robot front (deg, CCW +).
    marker_yaw_offset_deg: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.map_id.strip():
            raise ValueError("source and map identifiers are required")
        if not self.calibration_revision.strip() or not self.processor_revision.strip():
            raise ValueError("calibration and processor revisions are required")
        if self.calibration_source not in ("corner_markers", "field_boundary"):
            raise ValueError("calibration source must be corner_markers or field_boundary")
        if self.calibration_source == "field_boundary" and self.corner_marker_ids is not None:
            raise ValueError("a field_boundary source has no corner marker ids")
        if self.calibration_source == "corner_markers":
            if self.corner_marker_ids is None:
                raise ValueError("four corner marker ids are required for corner_markers")
            if (len(set(self.corner_marker_ids)) != 4
                    or any(type(v) is not int or v < 0 for v in self.corner_marker_ids)):
                raise ValueError("four distinct non-negative corner marker ids are required")
            if set(self.corner_marker_ids).intersection(self.robot_markers.values()):
                raise ValueError("robot marker ids cannot overlap calibration corners")
        if len(set(self.robot_markers.values())) != len(self.robot_markers):
            raise ValueError("each robot must have a unique marker id")
        if len(self.corner_world_m) != 4 or len(set(self.corner_world_m)) != 4:
            raise ValueError("four distinct map coordinates are required")
        if any(len(point) != 2 or any(not math.isfinite(value) for value in point)
               for point in self.corner_world_m):
            raise ValueError("map coordinates must be finite x/y pairs")
        if (len(self.heading_edge) != 2 or self.heading_edge[0] == self.heading_edge[1]
                or any(index not in range(4) for index in self.heading_edge)):
            raise ValueError("heading edge must identify two distinct marker corners")
        if any(not isinstance(robot_id, str) or not robot_id.strip()
               for robot_id in self.robot_markers):
            raise ValueError("robot identifiers are required")
        if any(type(marker_id) is not int or marker_id < 0
               for marker_id in self.robot_markers.values()):
            raise ValueError("robot marker ids must be non-negative integers")
        # D-580 may swap robot_markers for Fleet's roster, so offsets are not tied to them here.
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in self.marker_yaw_offset_deg.values()):
            raise ValueError("marker yaw offsets must be finite degrees")


def marker_homography(camera: CameraMap, markers: Mapping[int, Sequence[Point]]):
    """Image-to-map homography from the four corner markers, or None unless all four are in view."""

    if camera.corner_marker_ids is None or any(
            marker_id not in markers for marker_id in camera.corner_marker_ids):
        return None
    try:
        corner_centers = tuple(_center(markers[marker_id]) for marker_id in camera.corner_marker_ids)
        return fit(corner_centers, camera.corner_world_m)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def project_frame(
    camera: CameraMap,
    *,
    source_id: str,
    seq: int,
    captured_at: float,
    markers: Mapping[int, Sequence[Point]],
    homography: Homography | None = None,
) -> tuple[SiteSightingPayload, ...]:
    """Return display-only poses for every configured robot marker in this frame.

    ``corner_markers`` sources re-measure the homography from the frame's four
    corner markers. ``field_boundary`` sources (D-484) use the calibrator's
    accepted quad homography passed as ``homography``; None means this frame has
    no measured calibration and no sightings.
    """

    if source_id != camera.source_id:
        return ()
    measured = _measured(camera, markers, homography)
    if measured is None:
        return ()

    sightings = []
    for robot_id, marker_id in camera.robot_markers.items():
        pose = _pose(camera, measured, markers.get(marker_id))
        if pose is None:
            continue
        x, y, yaw = robot_pose_from_marker(pose, camera.marker_yaw_offset_deg.get(robot_id, 0.0))
        sightings.append(SiteSightingPayload(
            robot_id=robot_id,
            x=x,
            y=y,
            yaw=yaw,
            captured_at=captured_at,
            seq=seq,
            map_id=camera.map_id,
            calibration_revision=camera.calibration_revision,
            processor_revision=camera.processor_revision,
            quality=None,
            corner_marker_ids=camera.corner_marker_ids,
            calibration_source=camera.calibration_source,
        ))
    return tuple(sightings)


def project_place_markers(
    camera: CameraMap,
    *,
    seq: int,
    captured_at: float,
    markers: Mapping[int, Sequence[Point]],
    homography: Homography | None = None,
) -> PlaceMarkerPayload | None:
    """D-564: configured floor place markers in this frame, or None when none is measurable."""

    measured = _measured(camera, markers, homography) if camera.place_markers else None
    if measured is None:
        return None
    poses = []
    for marker_id in camera.place_markers:
        pose = _pose(camera, measured, markers.get(marker_id))
        if pose is not None:
            poses.append(PlaceMarkerPose(marker_id=marker_id, x=pose[0], y=pose[1], yaw=pose[2]))
    if not poses:
        return None
    return PlaceMarkerPayload(map_id=camera.map_id, calibration_revision=camera.calibration_revision,
                              captured_at=captured_at, seq=seq, markers=tuple(poses))


def robot_pose_from_marker(marker: tuple[float, float, float], yaw_offset_deg: float
                           ) -> tuple[float, float, float]:
    """D-587 4: the robot pose under a marker pose: yaw minus the offset, then the mount removed."""
    x, y, marker_yaw = marker
    yaw = math.atan2(math.sin(marker_yaw - math.radians(yaw_offset_deg)),
                     math.cos(marker_yaw - math.radians(yaw_offset_deg)))
    mx, my = MARKER_MOUNT_XY_M
    return (x - (mx * math.cos(yaw) - my * math.sin(yaw)),
            y - (mx * math.sin(yaw) + my * math.cos(yaw)), yaw)


def marker_geometry_ok(pixels: Sequence[Point], mapped: Sequence[Point]) -> bool:
    """D-587 6: a convex quad, shortest image side >= MIN_MARKER_SIDE_PX, map sides near the
    sticker size and opposite side pairs of similar length. ``mapped`` is the quad on the map
    plane at the marker height."""
    if len(pixels) != 4 or len(mapped) != 4:
        return False
    try:
        crosses = []
        for i in range(4):
            ax, ay = pixels[i]
            bx, by = pixels[(i + 1) % 4]
            cx, cy = pixels[(i + 2) % 4]
            crosses.append((bx - ax) * (cy - by) - (by - ay) * (cx - bx))
        pixel_sides = [math.dist(pixels[i], pixels[(i + 1) % 4]) for i in range(4)]
        sides = [math.dist(mapped[i], mapped[(i + 1) % 4]) for i in range(4)]
    except (TypeError, ValueError):
        return False
    if not all(math.isfinite(v) for v in (*crosses, *pixel_sides, *sides)):
        return False
    if not (all(c > 0 for c in crosses) or all(c < 0 for c in crosses)):
        return False
    if min(pixel_sides) < MIN_MARKER_SIDE_PX or min(sides) <= 0.0:
        return False
    low, high = MARKER_SIDE_BAND
    if not low * MARKER_SIDE_M <= sum(sides) / 4 <= high * MARKER_SIDE_M:
        return False
    ratio = (sides[0] + sides[2]) / (sides[1] + sides[3])
    return 1 / MAX_MARKER_SIDE_RATIO <= ratio <= MAX_MARKER_SIDE_RATIO


def _measured(camera: CameraMap, markers, homography):
    if camera.calibration_source == "field_boundary":
        return homography
    return marker_homography(camera, markers)


def _pose(camera: CameraMap, measured: Homography, quad) -> tuple[float, float, float] | None:
    """Marker centre and ``heading_edge`` tip through the homography; None when unusable."""
    if quad is None:
        return None
    try:
        center = _center(quad)
        edge_a, edge_b = camera.heading_edge
        heading_tip = (
            (quad[edge_a][0] + quad[edge_b][0]) / 2,
            (quad[edge_a][1] + quad[edge_b][1]) / 2,
        )
        x, y = measured.apply(*center)
        yaw = measured.yaw(center, heading_tip)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if not all(math.isfinite(value) for value in (x, y, yaw)):
        return None
    return x, y, yaw


def _center(quad: Sequence[Point]) -> Point:
    if len(quad) != 4:
        raise ValueError("an ArUco marker must have four corners")
    if any(len(point) != 2 or any(not math.isfinite(value) for value in point) for point in quad):
        raise ValueError("marker corners must be finite")
    return (
        sum(point[0] for point in quad) / 4,
        sum(point[1] for point in quad) / 4,
    )
