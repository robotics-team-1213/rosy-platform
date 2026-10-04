"""Project ArUco marker observations into a configured site map (D-257)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from core_common.protocol.sightings import SiteSightingPayload
from games.field.homography import Point, fit

MarkerQuad = tuple[Point, Point, Point, Point]


@dataclass(frozen=True)
class CameraMap:
    """Reviewed camera-to-map calibration and marker assignment for one source."""

    source_id: str
    map_id: str
    calibration_revision: str
    processor_revision: str
    corner_marker_ids: tuple[int, int, int, int]
    corner_world_m: tuple[Point, Point, Point, Point]
    robot_markers: Mapping[str, int]
    heading_edge: tuple[int, int] = (0, 1)

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.map_id.strip():
            raise ValueError("source and map identifiers are required")
        if not self.calibration_revision.strip() or not self.processor_revision.strip():
            raise ValueError("calibration and processor revisions are required")
        if len(set(self.corner_marker_ids)) != 4 or any(type(v) is not int or v < 0
                                                       for v in self.corner_marker_ids):
            raise ValueError("four distinct non-negative corner marker ids are required")
        if len(set(self.robot_markers.values())) != len(self.robot_markers):
            raise ValueError("each robot must have a unique marker id")
        if set(self.corner_marker_ids).intersection(self.robot_markers.values()):
            raise ValueError("robot marker ids cannot overlap calibration corners")
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


def project_frame(
    camera: CameraMap,
    *,
    source_id: str,
    seq: int,
    captured_at: float,
    markers: Mapping[int, Sequence[Point]],
) -> tuple[SiteSightingPayload, ...]:
    """Return display-only poses when every calibration corner is in this frame."""

    if source_id != camera.source_id:
        return ()
    if any(marker_id not in markers for marker_id in camera.corner_marker_ids):
        return ()
    try:
        corner_centers = tuple(_center(markers[marker_id]) for marker_id in camera.corner_marker_ids)
        homography = fit(corner_centers, camera.corner_world_m)
    except (TypeError, ValueError, ZeroDivisionError):
        return ()

    sightings = []
    for robot_id, marker_id in camera.robot_markers.items():
        quad = markers.get(marker_id)
        if quad is None:
            continue
        try:
            center = _center(quad)
            edge_a, edge_b = camera.heading_edge
            heading_tip = (
                (quad[edge_a][0] + quad[edge_b][0]) / 2,
                (quad[edge_a][1] + quad[edge_b][1]) / 2,
            )
            x, y = homography.apply(*center)
            yaw = homography.yaw(center, heading_tip)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            continue
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
        ))
    return tuple(sightings)


def _center(quad: Sequence[Point]) -> Point:
    if len(quad) != 4:
        raise ValueError("an ArUco marker must have four corners")
    if any(len(point) != 2 or any(not math.isfinite(value) for value in point) for point in quad):
        raise ValueError("marker corners must be finite")
    return (
        sum(point[0] for point in quad) / 4,
        sum(point[1] for point in quad) / 4,
    )
