"""Subject: lane following — floor line to lateral error plus loss tracking.

Two camera modes share one LaneObservation contract, both classical CV with
no model and no YOLO (SRS NAV-007):

  single line   one bright line on a dark floor; threshold plus column centroid
                (`detect_lane_error`)
  two-line lane a lane bounded by two white lines; per-row line runs projected
                to metres on a calibrated ground plane, steering to the midpoint
                (`detect_lane_centre`). No ground plane, no lane mode.
  between       the same two-line lane in image space, no ground plane: steer
                to the midpoint of the inner edges (`LaneBetweenKeeper`)

The tracker turns the observation stream into TRACKING/LOST: loss beyond the
grace period demands stop, never a blind search drive. ROS-free, same contract
onboard and in fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np

from .lane_helpers import (
    GROUND_LABELS,
    IRLineCalibration,
    LANE_LOST_GRACE_S,
    LANE_MAX_LINEAR_M_S,
    LaneBetweenKeeper,
    LaneObservation,
    LaneTracker,
    _BRIGHT,
    _WASHED_FRACTION,
    _row_runs,
    detect_ir_line,
    detect_lane_between,
    detect_lane_error,
    line_observation_payload,
    steer_correction,
)


def _spans_lane(ground, row: int, width_px: int, half: float) -> bool:
    """True when the frame at this row reaches both boundaries of a centred
    lane, so a missing line there is evidence and not just out of view."""
    frame_left = ground.lateral(0, row)
    frame_right = ground.lateral(width_px - 1, row)
    return (frame_left is not None and frame_right is not None
            and frame_left <= -half and frame_right >= half)


def _bright_runs(bright_row: np.ndarray, ground, row: int):
    """(near, far, middle) lateral metres of each horizontal bright run."""
    lit = np.concatenate(([0], (bright_row > 0).astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(lit))
    runs = []
    for start, stop in zip(edges[0::2], edges[1::2]):
        # Pixel centres sit on integer columns; the run spans half a pixel
        # beyond its first and last lit column.
        near = ground.lateral(start - 0.5, row)
        far = ground.lateral(stop - 0.5, row)
        middle = ground.lateral((start + stop - 1) / 2.0, row)
        if near is not None and far is not None and middle is not None:
            runs.append((near, far, middle))
    return runs


def detect_lane_centre(bgr: np.ndarray, ground, *,
                       bright_threshold: int = _BRIGHT,
                       lane_half_width_m: float,
                       roi_top_fraction: float,
                       roi_bottom_fraction: float,
                       washed_fraction: float = _WASHED_FRACTION,
                       max_line_width_m: float = 0.06,
                       row_step: int = 2) -> LaneObservation | None:
    """Steer to the midpoint between the two boundary lines of a lane.

    `ground is None` returns None: an uncalibrated camera never drives in
    lane mode.
    """
    if (isinstance(bright_threshold, bool) or not isinstance(bright_threshold, int)
            or not 1 <= bright_threshold <= 254):
        raise ValueError("bright_threshold must be an integer from 1 through 254")
    if (isinstance(lane_half_width_m, bool)
            or not isinstance(lane_half_width_m, (int, float))
            or not math.isfinite(lane_half_width_m) or not lane_half_width_m > 0.0):
        raise ValueError("lane_half_width_m must be a positive finite number")
    if (isinstance(roi_top_fraction, bool)
            or not isinstance(roi_top_fraction, (int, float))
            or not math.isfinite(roi_top_fraction) or not 0.0 <= roi_top_fraction < 1.0):
        raise ValueError("roi_top_fraction must be in [0, 1)")
    if (isinstance(roi_bottom_fraction, bool)
            or not isinstance(roi_bottom_fraction, (int, float))
            or not math.isfinite(roi_bottom_fraction)
            or not roi_top_fraction < roi_bottom_fraction <= 1.0):
        raise ValueError("roi_bottom_fraction must be in (roi_top_fraction, 1]")
    if (isinstance(washed_fraction, bool)
            or not isinstance(washed_fraction, (int, float))
            or not math.isfinite(washed_fraction) or not 0.0 < washed_fraction <= 1.0):
        raise ValueError("washed_fraction must be in (0, 1]")
    if (isinstance(max_line_width_m, bool)
            or not isinstance(max_line_width_m, (int, float))
            or not math.isfinite(max_line_width_m) or not max_line_width_m > 0.0):
        raise ValueError("max_line_width_m must be a positive finite number")
    if isinstance(row_step, bool) or not isinstance(row_step, int) or row_step < 1:
        raise ValueError("row_step must be a positive integer")
    if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
        raise ValueError("camera frame must be a non-empty grayscale or BGR array")
    if ground is None:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    top = int(gray.shape[0] * roi_top_fraction)
    bottom = int(gray.shape[0] * roi_bottom_fraction)
    band = gray[top:bottom, :]
    if band.size == 0:
        return None
    _, bright = cv2.threshold(band, bright_threshold, 255, cv2.THRESH_BINARY)
    if (bright > 0).sum() > washed_fraction * band.size:
        return None

    half = float(lane_half_width_m)
    observable = 0
    centres = []
    for offset in range(0, band.shape[0], row_step):
        row = top + offset
        if ground.distance(row) is None:
            continue
        if not _spans_lane(ground, row, gray.shape[1], half):
            continue
        observable += 1
        runs = [middle for near, far, middle in _bright_runs(bright[offset], ground, row)
                if far - near <= max_line_width_m]
        best = None
        for i, a in enumerate(runs):
            for b in runs[i + 1:]:
                separation = b - a
                if not 1.2 * half <= separation <= 2.8 * half:
                    continue
                midpoint = (a + b) / 2.0
                score = (abs(separation - 2.0 * half), abs(midpoint))
                if best is None or score < best[0]:
                    best = (score, midpoint)
        if best is not None:
            centres.append(best[1])
        elif len(runs) == 1:
            centres.append(runs[0] + half if runs[0] < 0.0 else runs[0] - half)
    if observable == 0 or not centres:
        return None
    error = max(-1.0, min(1.0, float(np.median(centres)) / half))
    return LaneObservation(error=error, confidence=len(centres) / observable)


# --- Corner turning (260919 track, Gazebo run 164757) ----------------------

#: Painted line width on the 260919 track.
LANE_LINE_WIDTH_M = 0.025
#: A run this wide is a line crossing the view, not a boundary seen along.
CORNER_TRANSVERSE_MIN_WIDTH_M = 3.0 * LANE_LINE_WIDTH_M
#: The open side must be seen empty over this much forward floor, nearer than
#: the transverse line, so a gap in the paint is not taken for a corner.
CORNER_OPEN_MIN_EXTENT_M = 0.05
#: Corner evidence beyond this camera range is too coarse (one row is cm).
CORNER_MAX_RANGE_M = 0.35
#: Consecutive frames that must agree before a turn is committed.
CORNER_CONFIRM_FRAMES = 2
#: Frame-to-frame agreement on the transverse distance after odometry travel.
CORNER_CONSISTENCY_M = 0.03
#: Confidence emitted while approaching with no line to centre on.
APPROACH_CONFIDENCE = 0.6
#: Speed CORE gives APPROACH_CONFIDENCE at zero error; sets the time bound.
APPROACH_NOMINAL_SPEED_M_S = 0.03
#: Approach may take this multiple of its nominal duration.
APPROACH_TIMEOUT_FACTOR = 2.0
#: Lateral odometry drift from the committed line, as a fraction of the
#: half-width, that aborts the approach.
APPROACH_MAX_DRIFT_FRACTION = 0.5
#: Past this yaw the new lane may end the turn.
TURN_REACQUIRE_MIN_RAD = math.radians(75.0)
#: Past this yaw without the new lane the turn has failed.
TURN_MAX_RAD = math.radians(105.0)
#: A 90 deg turn at CORE's 0.7 rad/s takes ~2.2 s.
TURN_TIMEOUT_S = 6.0
#: The reacquired lane must be this close to centre to end the turn.
TURN_REACQUIRE_MAX_ERROR = 0.5
#: A corner confirmed while commits were held stays armed until the robot
#: has turned this far or driven a half-width past its pivot...
ARMED_MAX_YAW_RAD = math.radians(30.0)
#: ...or for this long, whatever odometry says.
ARMED_MAX_AGE_S = APPROACH_TIMEOUT_FACTOR * CORNER_MAX_RANGE_M / APPROACH_NOMINAL_SPEED_M_S


@dataclass(frozen=True)
class LaneCorner:
    """`side` is the open side, where the new lane goes: 'LEFT' or 'RIGHT'.
    `distance_m` is camera-frame forward range to the transverse line centre."""

    side: str
    distance_m: float


def detect_lane_corner(bgr: np.ndarray, ground, *,
                       bright_threshold: int = _BRIGHT,
                       lane_half_width_m: float,
                       max_line_width_m: float = 0.06,
                       max_range_m: float = CORNER_MAX_RANGE_M) -> LaneCorner | None:
    """One frame's evidence of a 90 deg corner, or None."""
    if (isinstance(bright_threshold, bool) or not isinstance(bright_threshold, int)
            or not 1 <= bright_threshold <= 254):
        raise ValueError("bright_threshold must be an integer from 1 through 254")
    for name, value in (("lane_half_width_m", lane_half_width_m),
                        ("max_line_width_m", max_line_width_m),
                        ("max_range_m", max_range_m)):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not value > 0.0):
            raise ValueError(f"{name} must be a positive finite number")
    if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
        raise ValueError("camera frame must be a non-empty grayscale or BGR array")
    if ground is None:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    _, bright = cv2.threshold(gray, bright_threshold, 255, cv2.THRESH_BINARY)
    half = float(lane_half_width_m)
    nearer = []  # (distance, left line seen, right line seen), nearest first
    for row in range(gray.shape[0] - 1, -1, -1):
        distance = ground.distance(row)
        if distance is None:
            continue
        if distance > max_range_m:
            break
        if not _spans_lane(ground, row, gray.shape[1], half):
            continue
        runs = _bright_runs(bright[row], ground, row)
        if any(far - near > CORNER_TRANSVERSE_MIN_WIDTH_M for near, far, _ in runs):
            return _open_side(nearer, distance)
        lines = [middle for near, far, middle in runs if far - near <= max_line_width_m]
        nearer.append((distance, any(m < 0.0 for m in lines),
                       any(m >= 0.0 for m in lines)))
    return None


def _open_side(nearer, transverse_near_edge: float) -> LaneCorner | None:
    side = None
    reached = None
    for distance, left, right in reversed(nearer):
        if left == right:
            break
        open_side = "RIGHT" if left else "LEFT"
        if side is not None and open_side != side:
            break
        side, reached = open_side, distance
    if side is None or transverse_near_edge - reached < CORNER_OPEN_MIN_EXTENT_M:
        return None
    return LaneCorner(side=side,
                      distance_m=transverse_near_edge + LANE_LINE_WIDTH_M / 2.0)


def _travel(origin, pose) -> tuple[float, float]:
    """Displacement from `origin` along and across its heading (+ left)."""
    dx, dy = pose[0] - origin[0], pose[1] - origin[1]
    cos_yaw, sin_yaw = math.cos(origin[2]), math.sin(origin[2])
    return dx * cos_yaw + dy * sin_yaw, -dx * sin_yaw + dy * cos_yaw


class LaneCornerTracker:
    """Lane-centre following that can take a 90 deg corner."""

    def __init__(self, *, camera_x_offset_m: float = 0.0) -> None:
        if (isinstance(camera_x_offset_m, bool)
                or not isinstance(camera_x_offset_m, (int, float))
                or not math.isfinite(camera_x_offset_m)):
            raise ValueError("camera_x_offset_m must be a finite number")
        self._camera_x = float(camera_x_offset_m)
        self._reset()

    def _reset(self) -> None:
        self.state = "FOLLOW"
        self.side = None
        self._candidate = None
        self._origin = None
        self._started = None
        self._remaining = None
        self._timeout = None
        self._armed = None

    def _abort(self) -> None:
        self._reset()
        return None

    def _confirmed(self, corner, pose) -> bool:
        if corner is None:
            self._candidate = None
            return False
        count = 1
        if self._candidate is not None and self._candidate[0] == corner.side:
            _, distance, seen_at, seen = self._candidate
            along, _ = _travel(seen_at, pose)
            if abs(corner.distance_m + along - distance) <= CORNER_CONSISTENCY_M:
                count = seen + 1
        self._candidate = (corner.side, corner.distance_m, pose, count)
        return count >= CORNER_CONFIRM_FRAMES

    def update(self, now_s: float, pose, bgr: np.ndarray, ground, *,
               lane_half_width_m: float,
               roi_top_fraction: float,
               roi_bottom_fraction: float,
               bright_threshold: int = _BRIGHT,
               washed_fraction: float = _WASHED_FRACTION,
               commit_allowed: bool = True) -> LaneObservation | None:
        lane = detect_lane_centre(
            bgr, ground, bright_threshold=bright_threshold,
            lane_half_width_m=lane_half_width_m, roi_top_fraction=roi_top_fraction,
            roi_bottom_fraction=roi_bottom_fraction, washed_fraction=washed_fraction)
        half = float(lane_half_width_m)
        if pose is not None:
            pose = tuple(float(v) for v in pose)
            if len(pose) != 3 or not all(math.isfinite(v) for v in pose):
                pose = None
        now_s = float(now_s)

        if self.state == "FOLLOW":
            if pose is None or ground is None:
                self._candidate = None
                return lane
            corner = detect_lane_corner(bgr, ground, bright_threshold=bright_threshold,
                                        lane_half_width_m=half)
            if self._confirmed(corner, pose):
                self._armed = (corner.side, corner.distance_m, pose, now_s)
            elif self._armed is not None:
                side, distance, seen_at, armed_at = self._armed
                along, _ = _travel(seen_at, pose)
                turned = math.atan2(math.sin(pose[2] - seen_at[2]),
                                    math.cos(pose[2] - seen_at[2]))
                if (abs(turned) > ARMED_MAX_YAW_RAD
                        or along > distance + self._camera_x - half + half
                        or not 0.0 <= now_s - armed_at <= ARMED_MAX_AGE_S):
                    self._armed = None
            if not commit_allowed or self._armed is None:
                return lane
            side, distance, seen_at, _armed_at = self._armed
            self._armed = None
            self.state, self.side = "APPROACH", side
            self._origin, self._started = seen_at, now_s
            self._remaining = distance + self._camera_x - half
            already, _ = _travel(seen_at, pose)
            self._timeout = (APPROACH_TIMEOUT_FACTOR * max(0.0, self._remaining - already)
                             / APPROACH_NOMINAL_SPEED_M_S)

        if pose is None:
            return self._abort()

        if self.state == "APPROACH":
            along, across = _travel(self._origin, pose)
            if abs(across) > APPROACH_MAX_DRIFT_FRACTION * half:
                return self._abort()
            if along < self._remaining:
                if now_s - self._started > self._timeout:
                    return self._abort()
                if lane is None:
                    return LaneObservation(error=0.0, confidence=APPROACH_CONFIDENCE)
                return LaneObservation(error=lane.error,
                                       confidence=max(lane.confidence, APPROACH_CONFIDENCE))
            self.state = "TURN"
            self._origin, self._started = pose, now_s

        sign = 1.0 if self.side == "LEFT" else -1.0
        delta = pose[2] - self._origin[2]
        turned = sign * math.atan2(math.sin(delta), math.cos(delta))
        if now_s - self._started > TURN_TIMEOUT_S or turned > TURN_MAX_RAD:
            return self._abort()
        if (turned >= TURN_REACQUIRE_MIN_RAD and lane is not None
                and abs(lane.error) < TURN_REACQUIRE_MAX_ERROR):
            self._reset()
            return lane
        return LaneObservation(error=-sign, confidence=1.0)
