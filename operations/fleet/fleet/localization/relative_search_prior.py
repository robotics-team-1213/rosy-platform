"""A camera search prior in a measured native grid. This module never selects or injects a pose."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Mapping

from core_common.protocol.evidence import STALE_VELOCITY_S

from fleet.localization import cues, trust

MAX_FRAME_AGE_S = .45
MAX_REFERENCE_READ_AGE_S = .45
MIN_BASELINE_M = .35
MAX_BASELINE_ERROR_M = .08
MAX_PEER_DISAGREEMENT_M = .08
MAX_PEER_HEADING_ERROR_RAD = math.radians(15)
MAX_SHORT_BASELINE_HEADING_DISAGREEMENT_RAD = math.radians(8)
MAX_CANDIDATE_HEADING_ERROR_RAD = math.radians(25)
MAX_CANDIDATE_DISTANCE_M = .25
MIN_CANDIDATE_SCAN_FIT = .85


def pose3(row: Mapping):
    if not isinstance(row, Mapping):
        return None
    vals = tuple(row.get(k) for k in ("x", "y", "yaw"))
    return vals if all(type(v) in (int, float) and math.isfinite(v) for v in vals) else None


def synchronous_markers(sightings, robot_id: str, map_id: str, wall_now: float):
    """Only one exposure of the active approved vision source, not bridged or anonymous tracks."""
    rows = {row.get("robot_id"): row for row in sightings if isinstance(row, Mapping)}
    target = rows.get(robot_id)
    if target is None:
        return None
    key_names = ("source_id", "seq", "captured_at", "map_id", "calibration_revision", "processor_revision")
    frame = tuple(target.get(key) for key in key_names)
    source, seq, captured_at, observed_map, revision, processor = frame
    if (not source or type(seq) is not int or type(captured_at) not in (int, float)
            or not 0 <= wall_now - captured_at <= MAX_FRAME_AGE_S
            or observed_map != map_id or not revision or not processor):
        return None
    markers = {
        rid: pose for rid, row in rows.items()
        if row.get("calibration_source") == "approved_record"
        and ((quality := row.get("quality")) is None or (type(quality) in (int, float) and quality >= .8))
        and tuple(row.get(key) for key in key_names) == frame
        and (pose := pose3(row)) is not None
    }
    return captured_at, markers, source, revision


def stationary(state, read_age_s: float):
    velocity = state.get("velocity") or {}
    return (isinstance(velocity, Mapping)
            and all(type(velocity.get(axis)) in (int, float) and abs(velocity[axis]) <= limit
                    for axis, limit in (("linear", .01), ("angular", .02)))
            and _channel_fresh(state, "velocity", read_age_s, STALE_VELOCITY_S))


def _channel_fresh(state, channel, read_age_s, max_age_s):
    channels = state.get("evidence")
    evidence = channels.get(channel) if isinstance(channels, Mapping) else None
    if not isinstance(evidence, Mapping) or evidence.get("evidence") != "fresh":
        return False
    try:
        age = (datetime.fromisoformat(state["timestamp"]) - datetime.fromisoformat(evidence["received_at"])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return False
    return age >= 0 and read_age_s >= 0 and age + read_age_s <= max_age_s


def fresh_native_stamp(state, stamp, max_age_s):
    """Validate native ROS scan or CORE receipt time in that robot's wall clock."""
    try:
        packet_at = datetime.fromisoformat(state["timestamp"])
        return packet_at.tzinfo is not None and 0 <= packet_at.timestamp() - stamp <= max_age_s
    except (KeyError, ValueError, TypeError):
        return False


def fresh_odom(state, read_age_s):
    row = state.get("odom_pose") or {}
    pose = pose3(row)
    if (pose is None or type(row.get("epoch")) is not int or row["epoch"] < 0 or read_age_s < 0
            or type(row.get("stamp")) not in (int, float)
            or not fresh_native_stamp(state, row["stamp"], MAX_REFERENCE_READ_AGE_S - read_age_s)):
        return None
    return pose, row["epoch"]


def fresh_reference(state, read_age_s: float):
    """CORE packet-local clock for pose/velocity evidence, Fleet monotonic for receipt age."""
    if (not isinstance(state, Mapping) or trust.classify(state) != trust.TRUSTED
            or state.get("pose_frame") != "map" or not stationary(state, read_age_s)
            or not _channel_fresh(state, "pose", read_age_s, MAX_REFERENCE_READ_AGE_S)):
        return None
    return pose3(state.get("pose") or {})


def relative_center(target, references):
    """Check both independent peer projections in native metres before averaging their search centres."""
    if len(references) != 2:
        return None
    (cam_a, native_a), (cam_b, native_b) = references
    cam_len, native_len = math.dist(cam_a[:2], cam_b[:2]), math.dist(native_a[:2], native_b[:2])
    if min(cam_len, native_len) < MIN_BASELINE_M or abs(cam_len - native_len) > MAX_BASELINE_ERROR_M:
        return None
    baseline_yaw = cues.wrap(math.atan2(native_b[1] - native_a[1], native_b[0] - native_a[0])
                             - math.atan2(cam_b[1] - cam_a[1], cam_b[0] - cam_a[0]))
    predictions = []
    for camera, native in references:
        yaw = cues.wrap(native[2] - camera[2])
        if abs(cues.wrap(yaw - baseline_yaw)) > MAX_PEER_HEADING_ERROR_RAD:
            return None
        predictions.append(cues.to_map((native[0], native[1], yaw), (target[0] - camera[0], target[1] - camera[1])))
    if math.dist(*predictions) > MAX_PEER_DISAGREEMENT_M:
        return None
    x, y = ((a + b) / 2 for a, b in zip(*predictions))
    return x, y, cues.wrap(target[2] + baseline_yaw)


def short_baseline_center(target, references, report):
    """Use the two calibrated marker headings independently when a baseline cannot give yaw."""
    if len(references) != 2:
        return None
    (cam_a, native_a), (cam_b, native_b) = references
    cam_len, native_len = math.dist(cam_a[:2], cam_b[:2]), math.dist(native_a[:2], native_b[:2])
    if (not 0 < min(cam_len, native_len) <= max(cam_len, native_len) < MIN_BASELINE_M
            or abs(cam_len - native_len) > MAX_BASELINE_ERROR_M):
        return None
    rotations = [cues.wrap(native[2] - camera[2]) for camera, native in references]
    if abs(cues.wrap(rotations[0] - rotations[1])) > MAX_SHORT_BASELINE_HEADING_DISAGREEMENT_RAD:
        return None
    predictions = [cues.to_map((native[0], native[1], rotation),
                               (target[0] - camera[0], target[1] - camera[1]))
                   for (camera, native), rotation in zip(references, rotations)]
    if math.dist(*predictions) > MAX_PEER_DISAGREEMENT_M:
        return None
    center = tuple((a + b) / 2 for a, b in zip(*predictions))
    nearby = [c for c in report.candidates if c.scan_fit >= MIN_CANDIDATE_SCAN_FIT
              and math.dist(center, (c.x, c.y)) <= MAX_CANDIDATE_DISTANCE_M]
    if not nearby:
        return None
    leader = max(nearby, key=lambda c: c.scan_fit)
    if any(abs(cues.wrap(leader.yaw - c.yaw)) > MAX_PEER_HEADING_ERROR_RAD
           or math.dist((leader.x, leader.y), (c.x, c.y)) > MAX_PEER_DISAGREEMENT_M for c in nearby):
        return None
    if any(abs(cues.wrap(leader.yaw - target[2] - r)) > MAX_CANDIDATE_HEADING_ERROR_RAD for r in rotations):
        return None
    return (*center, leader.yaw)


def supports_heading(center, report):
    """A configured target marker heading needs independent native scan corroboration."""
    return any(c.scan_fit >= MIN_CANDIDATE_SCAN_FIT
               and math.dist(center[:2], (c.x, c.y)) <= MAX_CANDIDATE_DISTANCE_M
               and abs(cues.wrap(center[2] - c.yaw)) <= MAX_CANDIDATE_HEADING_ERROR_RAD
               for c in report.candidates)
