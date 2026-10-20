"""Fixed surveyed map camera to station candidates; Fleet owns installation acceptance."""
import asyncio
import math
import time
from typing import Annotated, Literal

from pydantic import Field, model_validator
import numpy as np
from core_common.protocol.station_charging import (
    Contract, Identifier, Nonnegative, Number, Pose2D, Positive, Revision, StationPoseRecord,
)
from .station_marker import marker_pose, validate_marker_calibration
from .detect import detect_markers
from .project import MIN_MARKER_SIDE_PX, MAX_MARKER_SIDE_RATIO


def _convex_quad(points):
    try:
        points = np.asarray(points, dtype=float)
    except (TypeError, ValueError):
        return False
    if points.shape != (4, 2) or not np.isfinite(points).all():
        return False
    edges = np.roll(points, -1, axis=0)-points
    following = np.roll(edges, -1, axis=0)
    cross = edges[:, 0]*following[:, 1]-edges[:, 1]*following[:, 0]
    sides = np.linalg.norm(edges, axis=1)
    return (bool(np.all(cross > 0) or np.all(cross < 0))
            and min(sides) >= MIN_MARKER_SIDE_PX
            and np.all(np.abs(cross) >= MIN_MARKER_SIDE_PX*sides)
            and max(sides)/min(sides) <= MAX_MARKER_SIDE_RATIO)


class StationImageAnchor(Contract):
    """Surveyed rectified image corners; independent of station-marker plane H."""
    marker_id: Annotated[int, Field(strict=True, ge=0)]
    corners: tuple[tuple[Nonnegative, Nonnegative], tuple[Nonnegative, Nonnegative],
                   tuple[Nonnegative, Nonnegative], tuple[Nonnegative, Nonnegative]]

    @model_validator(mode='after')
    def measurable_quad(self):
        if not _convex_quad(self.corners):
            raise ValueError('STATION_MAP_ANCHOR_GEOMETRY_INVALID')
        return self


class StationMapCalibration(Contract):
    station_id: Identifier
    map_id: Identifier
    map_revision: Identifier
    source_id: Identifier
    source_epoch: Identifier
    revision: Identifier
    pose_revision_hint: Revision
    marker_id: Annotated[int, Field(strict=True, ge=0)]
    marker_side_m: Positive
    marker_mount: Pose2D
    image_to_map: tuple[Number, ...]
    plane: Literal['station_marker']
    lens_rectified: bool
    approved: bool
    fixed_map_anchor: bool
    image_anchors: tuple[StationImageAnchor, StationImageAnchor, StationImageAnchor, StationImageAnchor]
    max_anchor_error_px: Positive
    uncertainty_m: Nonnegative
    uncertainty_rad: Nonnegative
    approach_offset_m: Positive

    @model_validator(mode='after')
    def measured_fixed_map_plane(self):
        validate_marker_calibration(self, self.image_to_map, plane='station_marker')
        if self.fixed_map_anchor is not True:
            raise ValueError('STATION_FIXED_MAP_ANCHOR_REQUIRED')
        ids = [anchor.marker_id for anchor in self.image_anchors]
        centres = [np.asarray(anchor.corners).mean(axis=0) for anchor in self.image_anchors]
        if len(set(ids+[self.marker_id])) != 5 or not _convex_quad(centres):
            raise ValueError('STATION_MAP_ANCHOR_COVERAGE_INVALID')
        for anchor in self.image_anchors:
            pixels = np.asarray(anchor.corners)
            if self.max_anchor_error_px >= .1*min(np.linalg.norm(pixels-np.roll(pixels, 1, axis=0), axis=1)):
                raise ValueError('STATION_MAP_ANCHOR_TOLERANCE_TOO_LARGE')
        return self

    def anchors_match(self, detected):
        for anchor in self.image_anchors:
            observed = detected.get(anchor.marker_id)
            if not _convex_quad(observed) or np.max(np.linalg.norm(
                    np.asarray(observed)-np.asarray(anchor.corners), axis=1)) > self.max_anchor_error_px:
                return False
        quad = detected.get(self.marker_id)
        if not _convex_quad(quad):
            return False
        hull = np.asarray([np.asarray(anchor.corners).mean(axis=0) for anchor in self.image_anchors])
        edges = np.roll(hull, -1, axis=0)-hull
        delta = np.asarray(quad)[:, None, :]-hull
        cross = edges[None, :, 0]*delta[:, :, 1]-edges[None, :, 1]*delta[:, :, 0]
        return bool(np.all(cross > 0) or np.all(cross < 0))


def create_station_map_worker(*, calibration, ingest, rectify, publisher, clock, max_age_s,
                              monotonic=time.monotonic):
    from .worker import VisionWorker
    processor = StationMapFrameProcessor(calibration=calibration, rectify=rectify, publisher=publisher,
        clock=clock, max_age_s=max_age_s, monotonic=monotonic)
    return VisionWorker(source_id=processor.source_id, ingest=ingest, camera=None,
        publisher=publisher, clock=clock, max_age_s=max_age_s, station=processor)


class StationMapFrameProcessor:
    def __init__(self, *, calibration, rectify, publisher, clock, max_age_s, monotonic):
        if (not isinstance(calibration, StationMapCalibration) or not callable(rectify)
                or not callable(clock) or not callable(monotonic)
                or type(max_age_s) not in (int, float) or not math.isfinite(max_age_s) or max_age_s <= 0):
            raise ValueError('STATION_FIXED_MAP_PROFILE_REQUIRED')
        self.calibration = StationMapCalibration.model_validate(calibration.model_dump())
        self.rectify, self.publisher = rectify, publisher
        self.clock, self.max_age_s, self.monotonic = clock, max_age_s, monotonic
        self._lock = asyncio.Lock()
        self._seq = self._captured = None

    @property
    def source_id(self):
        return self.calibration.source_id

    def _measure(self, jpeg, captured, expiry):
        cal = self.calibration
        rectified = self.rectify(jpeg)
        detected = detect_markers(rectified)
        if not cal.anchors_match(detected):
            return None
        pose = marker_pose(rectified, marker_id=cal.marker_id, marker_side_m=cal.marker_side_m,
            marker_mount=cal.marker_mount, matrix=cal.image_to_map, detected=detected)
        if pose is None:
            return None
        c, s = math.cos(pose.yaw), math.sin(pose.yaw)
        return StationPoseRecord(station_id=cal.station_id, map_id=cal.map_id, map_revision=cal.map_revision,
            pose_revision=cal.pose_revision_hint, pose=pose,
            approach_pose=Pose2D(x=pose.x-c*cal.approach_offset_m, y=pose.y-s*cal.approach_offset_m, yaw=pose.yaw),
            approach_verified=False, source_id=cal.source_id, source_epoch=cal.source_epoch,
            calibration_revision=cal.revision, captured_at=captured, valid_until=expiry,
            uncertainty_m=cal.uncertainty_m+math.hypot(cal.marker_mount.x, cal.marker_mount.y)*cal.uncertainty_rad,
            uncertainty_rad=cal.uncertainty_rad, status='CANDIDATE')

    async def process(self, frame, *, source_id):
        if source_id != self.source_id:
            raise ValueError('STATION_FRAME_SOURCE_MISMATCH')
        async with self._lock:
            captured, received, seq, jpeg = frame.captured_at, frame.received_at, frame.header.seq, frame.jpeg
            mono, utc = self.monotonic(), self.clock()
            values = (captured, received, utc, mono)
            if (any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
                    or type(seq) is not int or seq < 0 or self._seq is not None and seq <= self._seq
                    or self._captured is not None and captured <= self._captured):
                return False
            self._seq = seq  # Unknown publication and invalid frames are never resubmitted.
            expiry = captured+self.max_age_s
            if not 0 <= captured <= received <= utc < expiry:
                return False
            self._captured = captured
            deadline = mono+expiry-utc
            try:
                candidate = await asyncio.wait_for(asyncio.to_thread(self._measure, jpeg, captured, expiry),
                    timeout=expiry-utc)
                if candidate is None:
                    return False
                current_mono, now = self.monotonic(), self.clock()
                if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (now, current_mono))
                        or now < utc or not mono <= current_mono < deadline):
                    return False
                StationPoseRecord.model_validate(candidate.model_dump(), context={'now': now})
                result = await asyncio.wait_for(self.publisher.publish_station_pose(candidate),
                    timeout=min(expiry-now, deadline-current_mono))
                return isinstance(result, dict) and result.get('accepted') is True
            except (ValueError, TypeError, TimeoutError):
                return False
