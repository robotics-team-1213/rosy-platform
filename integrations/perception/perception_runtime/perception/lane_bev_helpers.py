"""Bird's-eye floor grid projection, odometry cell lattice memory, and curvature steering law."""

from __future__ import annotations

import math

import cv2
import numpy as np

#: Grid cell. A lane line is ten cells wide, and the 6 mm gap between the
#: lap's crosswalk bars and the boundary is at least two, so the gap
#: survives cell rounding at every heading.
BEV_CELL_M = 0.0025
#: Grid extent, base_link frame. Behind and beside the robot only memory
#: lives: the camera cannot see a boundary a half-width to the side until
#: ~0.17 m ahead of base_link.
BEV_X_MIN_M = -0.20
BEV_X_MAX_M = 0.50
BEV_Y_HALF_M = 0.35
#: Camera range below which the robot's own body fills the image (Gazebo:
#: rows >= 139, i.e. nearer than 0.082 m, render the body at grey ~218).
BEV_MIN_RANGE_M = 0.09
#: Camera range beyond which one image row spans > 1 cm of floor.
BEV_MAX_RANGE_M = 0.40

#: Pure-pursuit lookahead from base_link. Comparable to the tightest path
#: radius on the lap (a half-width round convex corners) so corners are not
#: cut by more than a few cm.
LOOKAHEAD_M = 0.15
#: If the path point at LOOKAHEAD_M is unsupported, the lookahead grows in
#: LOOKAHEAD_STEP_M steps up to this (on a fresh seed the boundary is only
#: seen from ~0.17 m ahead; pure pursuit holds for any radius).
LOOKAHEAD_MAX_M = 0.25
LOOKAHEAD_STEP_M = 0.01
#: A path point further off the heading than this is behind, not ahead.
LOOKAHEAD_MAX_BEARING_RAD = math.radians(100.0)
# ponytail: Host 65-deg gap calibration; tune from reviewed camera frames before activation.
RIGHT_MATE_MAX_LATERAL_FRACTION = 0.65
#: The robot must be within this of the path it pursues.
PATH_MAX_OFFSET_M = 0.14
#: Half-thickness of the iso-line band, so it stays 8-connected.
PATH_BAND_HALF_M = BEV_CELL_M
#: A path point is supported by the boundary when its nearest boundary point
#: is interior -- paint extends SUPPORT_RADIUS_M / 2 along the local axis
#: (principal axis over SUPPORT_RADIUS_M) on both sides of it -- and the
#: offset is within SUPPORT_MAX_ANGLE_RAD of the local normal.
SUPPORT_MAX_ANGLE_RAD = math.radians(45.0)
SUPPORT_RADIUS_M = 0.02

#: Memory overlap: a component matches the carried boundary when this many
#: of its cells lie within MATCH_RADIUS_CELLS (5 mm) of it.
MATCH_RADIUS_CELLS = 2
MATCH_MIN_CELLS = 20
#: With memory but no overlap (the camera picks a line up again beyond the
#: remembered piece, e.g. the new lane's inner line after a 90 deg turn), a
#: lane-width pair may reseed if its left line continues the memory within
#: this gap.
RESEED_MAX_GAP_M = 0.15
#: Seed and right-boundary candidates must be longer than the lap's crosswalk
#: bars (0.121 m, between the lines); the boundary in view is >= 0.2 m.
MIN_BOUNDARY_LENGTH_M = 0.15
#: Paint components are 4-connected, so a one-cell diagonal gap (the
#: crosswalk bars stop 6 mm short of the boundary) cannot leak.
PAINT_CONNECTIVITY = 4
#: A boundary cell not re-observed within this much travel is dropped.
MEMORY_TRAVEL_M = 0.40
#: Memory ages by max(translation, half-width x rotation) per frame.
MEMORY_RADIUS_M = 0.50
#: Confidence while pursuing remembered paint only; CORE drives ~0.03 m/s.
MEMORY_CONFIDENCE = 0.6

#: Odometry whose stamp is further than this from the image's is no pose.
ODOM_MAX_SKEW_S = 0.30
# ponytail: Conservative 0.5 s camera gap at 0.08 m/s plus margin; calibrate on robot odom.
ODOM_MAX_STEP_M = 0.06

# CORE line_follow law (core_features/line_follow/manager.py, tick()),
# mirrored so a curvature can be expressed as the error CORE turns into it;
# test_lane_edge pins these to CORE's LineFollowConfig defaults.
CORE_CRUISE_M_S = 0.08
CORE_STEERING_GAIN = 0.8
CORE_CURVE_SLOWDOWN = 0.65
CORE_MIN_CONFIDENCE = 0.35


def error_for_curvature(curvature: float, confidence: float) -> float:
    """CORE error whose command follows `curvature` (1/m, left +).

    CORE: w = -g e, v = V max(0.2, 1 - c|e|), V = cruise x confidence scale.
    Following a curve needs w = v k, so g|e| = V|k| (1 - c|e|), giving
    |e| = V|k| / (g + c V|k|); 1 - c|e| >= 0.2 holds for |e| <= 1. The sign
    is opposite to k (left curvature is a negative, steer-left error).
    """
    scale = (confidence - CORE_MIN_CONFIDENCE) / (1.0 - CORE_MIN_CONFIDENCE)
    speed = CORE_CRUISE_M_S * max(0.0, min(1.0, scale))
    demand = speed * abs(curvature)
    magnitude = demand / (CORE_STEERING_GAIN + CORE_CURVE_SLOWDOWN * demand)
    return max(-1.0, min(1.0, -math.copysign(magnitude, curvature)))


#: The tightest path the lap asks for: a half-width round a convex corner.
_TIGHTEST_PATH_RADIUS_M = 0.0925


def _memory_max_age_s() -> float:
    """MEMORY_TRAVEL_M at the slowest speed CORE commands on memory alone
    (MEMORY_CONFIDENCE on the tightest path): 0.40 m / 0.0242 m/s = 16.5 s."""
    confidence = MEMORY_CONFIDENCE
    error = error_for_curvature(1.0 / _TIGHTEST_PATH_RADIUS_M, confidence)
    scale = (confidence - CORE_MIN_CONFIDENCE) / (1.0 - CORE_MIN_CONFIDENCE)
    slowest = CORE_CRUISE_M_S * scale * max(
        0.2, 1.0 - CORE_CURVE_SLOWDOWN * abs(error)
    )
    return MEMORY_TRAVEL_M / slowest


#: With no fresh paint of this lane (left or right) for this long, memory is
#: forgotten and there is no output. See `_memory_max_age_s`.
MEMORY_MAX_AGE_S = _memory_max_age_s()


def pose_if_fresh(pose, pose_stamp_s, image_stamp_s):
    """`pose` if its stamp is within ODOM_MAX_SKEW_S of the image's, else None
    (dead odometry, or a pose from another moment)."""
    if pose is None or pose_stamp_s is None or image_stamp_s is None:
        return None
    skew = float(image_stamp_s) - float(pose_stamp_s)
    if not math.isfinite(skew) or abs(skew) > ODOM_MAX_SKEW_S:
        return None
    return pose


class BirdsEye:
    """Robot-frame BEV_CELL_M floor grid sampled from one camera's pixels."""

    def __init__(
        self, ground, width_px: int, height_px: int, camera_x_offset_m: float
    ) -> None:
        self.rows = int(round((BEV_X_MAX_M - BEV_X_MIN_M) / BEV_CELL_M))
        self.cols = int(round(2.0 * BEV_Y_HALF_M / BEV_CELL_M))
        i, j = np.mgrid[0 : self.rows, 0 : self.cols]
        self.x = BEV_X_MIN_M + (i + 0.5) * BEV_CELL_M
        self.y = BEV_Y_HALF_M - (j + 0.5) * BEV_CELL_M
        forward = self.x - camera_x_offset_m
        right = -self.y
        with np.errstate(invalid="ignore", divide="ignore"):
            ray = np.arctan2(ground.height_m, forward) - ground.pitch_rad
            row = ground.principal_y + ground.focal_px * np.tan(ray)
            denominator = (
                ground.focal_px * math.sin(ground.pitch_rad)
                + (row - ground.principal_y) * math.cos(ground.pitch_rad)
            )
            column = (
                ground.principal_x + right * denominator / ground.height_m
            )
        pixel_row = np.rint(row)
        pixel_col = np.rint(column)
        self.observable = (
            (forward >= BEV_MIN_RANGE_M)
            & (forward <= BEV_MAX_RANGE_M)
            & (forward <= ground.max_range_m)
            & np.isfinite(pixel_row)
            & np.isfinite(pixel_col)
            & (pixel_row >= 0)
            & (pixel_row < height_px)
            & (pixel_col >= 0)
            & (pixel_col < width_px)
        )
        self._pixel_row = np.where(self.observable, pixel_row, 0).astype(
            np.intp
        )
        self._pixel_col = np.where(self.observable, pixel_col, 0).astype(
            np.intp
        )
        #: Range and |bearing| of every cell from base_link (fixed per view).
        self.radius = np.hypot(self.x, self.y)
        self.bearing = np.abs(np.arctan2(self.y, self.x))

    def sample(self, bright: np.ndarray) -> np.ndarray:
        return (
            bright[self._pixel_row, self._pixel_col] & self.observable
        ).astype(np.uint8)

    def seen(self, xy: np.ndarray) -> np.ndarray:
        """bool per floor point (N x 2, base_link): on an observable cell of this grid."""
        i = np.floor((xy[:, 0] - BEV_X_MIN_M) / BEV_CELL_M).astype(np.intp)
        j = np.floor((BEV_Y_HALF_M - xy[:, 1]) / BEV_CELL_M).astype(np.intp)
        inside = (i >= 0) & (i < self.rows) & (j >= 0) & (j < self.cols)
        return inside & self.observable[
            np.where(inside, i, 0), np.where(inside, j, 0)
        ]

    def cell(self, x: float, y: float) -> tuple[int, int]:
        return (
            int(math.floor((x - BEV_X_MIN_M) / BEV_CELL_M)),
            int(math.floor((BEV_Y_HALF_M - y) / BEV_CELL_M)),
        )


def _to_robot(points_odom: np.ndarray, pose) -> np.ndarray:
    x, y, yaw = pose
    dx, dy = points_odom[:, 0] - x, points_odom[:, 1] - y
    c, s = math.cos(yaw), math.sin(yaw)
    return np.stack([dx * c + dy * s, -dx * s + dy * c], axis=1)


def _to_odom(points_robot: np.ndarray, pose) -> np.ndarray:
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    return np.stack(
        [
            x + points_robot[:, 0] * c - points_robot[:, 1] * s,
            y + points_robot[:, 0] * s + points_robot[:, 1] * c,
        ],
        axis=1,
    )


class _LineMemory:
    """One boundary line's paint cells in the odometry frame: integer cell
    keys (BEV_CELL_M lattice) and the odometer reading each was last seen
    at, one row per distinct key."""

    def __init__(self) -> None:
        self._keys = np.empty((0, 2), np.int64)
        self._seen = np.empty(0)

    def __bool__(self) -> bool:
        return len(self._seen) > 0

    def clear(self) -> None:
        self._keys = np.empty((0, 2), np.int64)
        self._seen = np.empty(0)

    def remember(
        self, points_robot: np.ndarray, pose, odometer: float
    ) -> None:
        keys = np.rint(_to_odom(points_robot, pose) / BEV_CELL_M).astype(
            np.int64
        )
        if len(keys) == 0:
            return
        keys = np.vstack([self._keys, keys])
        seen = np.concatenate(
            [self._seen, np.full(len(keys) - len(self._seen), odometer)]
        )
        code = (keys[:, 0] << 32) + keys[:, 1]
        _, first = np.unique(code[::-1], return_index=True)
        last = len(code) - 1 - first
        self._keys, self._seen = keys[last], seen[last]

    def prune(self, pose, odometer: float) -> None:
        if not len(self._seen):
            return
        radius_cells = MEMORY_RADIUS_M / BEV_CELL_M
        px, py = pose[0] / BEV_CELL_M, pose[1] / BEV_CELL_M
        keep = (odometer - self._seen <= MEMORY_TRAVEL_M) & (
            np.hypot(self._keys[:, 0] - px, self._keys[:, 1] - py)
            <= radius_cells
        )
        self._keys, self._seen = self._keys[keep], self._seen[keep]

    def grid(self, view: BirdsEye, pose) -> np.ndarray:
        grid = np.zeros((view.rows, view.cols), np.uint8)
        if not len(self._seen):
            return grid
        points = _to_robot(self._keys * BEV_CELL_M, pose)
        i = np.floor((points[:, 0] - BEV_X_MIN_M) / BEV_CELL_M).astype(int)
        j = np.floor((BEV_Y_HALF_M - points[:, 1]) / BEV_CELL_M).astype(int)
        inside = (i >= 0) & (i < view.rows) & (j >= 0) & (j < view.cols)
        grid[i[inside], j[inside]] = 1
        return cv2.morphologyEx(
            grid, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)
        )

    def __len__(self) -> int:
        return len(self._seen)
