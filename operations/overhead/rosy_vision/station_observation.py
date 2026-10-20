"""Rectified station-camera markers to relative poses; map localization needs an independent anchor.

The homography is measured at the robot marker plane, not the floor. Its validity
is station-local and does not establish the station's map position after a move.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from core_common.protocol.station_charging import MapPoseEvidence, Pose2D, StationObservation, StationPoseRecord
from .station_marker import marker_pose, validate_marker_calibration


def _wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def _compose(base, local):
    c, s = math.cos(base.yaw), math.sin(base.yaw)
    return Pose2D(x=base.x + c * local.x - s * local.y,
                  y=base.y + s * local.x + c * local.y, yaw=_wrap(base.yaw + local.yaw))


@dataclass(frozen=True)
class StationCameraCalibration:
    station_id: str
    source_id: str
    source_epoch: str
    revision: str
    marker_id: int
    marker_side_m: float
    marker_mount: Pose2D
    image_to_station: tuple[float, ...]
    plane: str
    lens_rectified: bool
    approved: bool
    uncertainty_m: float
    uncertainty_rad: float

    def __post_init__(self):
        validate_marker_calibration(self, self.image_to_station, plane='robot_marker')


def observe_jpeg(jpeg: bytes, *, calibration: StationCameraCalibration,
                 template: StationObservation) -> StationObservation:
    if ((template.station_id, template.source_id, template.source_epoch, template.calibration_revision)
            != (calibration.station_id, calibration.source_id, calibration.source_epoch, calibration.revision)):
        raise ValueError('STATION_CALIBRATION_SCOPE_MISMATCH')
    lost = template.model_copy(update={'visible': False, 'pose': None})
    pose = marker_pose(jpeg, marker_id=calibration.marker_id, marker_side_m=calibration.marker_side_m,
                       marker_mount=calibration.marker_mount, matrix=calibration.image_to_station)
    if pose is None:
        return lost
    x, y, heading = pose.x, pose.y, pose.yaw
    c, s = math.cos(heading), math.sin(heading)
    # The station frame's origin is the target seating pose; invert station←robot.
    relative = Pose2D(x=float(-c * x - s * y), y=float(s * x - c * y), yaw=_wrap(-heading))
    return template.model_copy(update={
        'visible': True, 'pose': relative, 'uncertainty_m': calibration.uncertainty_m,
        'uncertainty_rad': calibration.uncertainty_rad})


def station_map_pose(robot_map: MapPoseEvidence, relative: StationObservation, *,
                     approach_offset_m: float) -> StationPoseRecord:
    if not relative.visible or relative.pose is None or robot_map.source_id == relative.source_id:
        raise ValueError('INDEPENDENT_MAP_ANCHOR_REQUIRED')
    if any(getattr(robot_map, key) != getattr(relative, key) for key in (
            'robot_id', 'boot_id', 'odom_epoch', 'map_id', 'map_revision', 'captured_at')):
        raise ValueError('MAP_ANCHOR_NOT_PAIRED')
    if (isinstance(approach_offset_m, bool) or not math.isfinite(approach_offset_m)
            or approach_offset_m <= 0):
        raise ValueError('APPROACH_OFFSET_REQUIRED')
    pose = _compose(robot_map.pose, relative.pose)
    return StationPoseRecord(
        station_id=relative.station_id, map_id=relative.map_id, map_revision=relative.map_revision,
        pose_revision=relative.pose_revision, pose=pose,
        approach_pose=_compose(pose, Pose2D(x=-approach_offset_m, y=0.0, yaw=0.0)), approach_verified=False,
        source_id=relative.source_id, source_epoch=relative.source_epoch,
        calibration_revision=relative.calibration_revision, captured_at=relative.captured_at,
        valid_until=min(robot_map.valid_until, relative.valid_until),
        uncertainty_m=(robot_map.uncertainty_m + relative.uncertainty_m
                       + math.hypot(relative.pose.x, relative.pose.y) * robot_map.uncertainty_rad),
        uncertainty_rad=robot_map.uncertainty_rad + relative.uncertainty_rad, status='CANDIDATE')
