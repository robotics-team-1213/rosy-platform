"""Subject: left-edge lane following in a bird's-eye view of the floor.

Row-wise line pairing assumes the lines run roughly along travel; at the
260919 track's 65 deg chevrons and the roundabout arc a boundary crosses the
image and a row sees one wide run. This module stops reading rows and reads
the floor instead:

  bird's-eye view   every observable cell of a 2.5 mm robot-frame grid samples
                    the thresholded camera pixel that images it, through the
                    calibrated GroundPlane (inverse mapping, so the far field
                    has no holes between rows)
  boundaries        the connected paint component on the robot's left that
                    best overlaps the previous boundary, carried forward by
                    odometry, seeded only by a lane-width line pair; the
                    same lane's right boundary likewise, as a stand-in
  path              the locus a half-width from that boundary on the robot's
                    side (a distance-field iso-line: parallel on straights,
                    an arc of radius half-width round convex corners)
  pursuit           pure pursuit to the path point LOOKAHEAD_M away, mapped
                    through CORE's line_follow law to the error it expects

Frame: base_link, x ahead, y LEFT positive (REP 103). Output keeps the lane
contract: error > 0 means steer right. No ground plane or no odometry means
no output: the boundary memory cannot be carried without odometry. Odometry
older than ODOM_MAX_SKEW_S against the image counts as none, and memory not
refreshed by fresh paint for MEMORY_MAX_AGE_S is forgotten, so frozen
odometry cannot drive on remembered paint for ever.

On the 260919 lap the inner block's outline is one closed line on the
robot's left, so holding it at a half-width drives the whole lap with no
junction decision (the roundabout is taken on its outer arc).
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .lane import (
    LANE_LINE_WIDTH_M,
    LaneCornerTracker,
    LaneObservation,
    _BRIGHT,
    _WASHED_FRACTION,
)

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
#: The robot must be within this of the path it pursues.
PATH_MAX_OFFSET_M = 0.14
#: Half-thickness of the iso-line band, so it stays 8-connected.
PATH_BAND_HALF_M = BEV_CELL_M
#: A path point is supported by the boundary when its nearest boundary point
#: is interior -- paint extends SUPPORT_RADIUS_M / 2 along the local axis
#: (principal axis over SUPPORT_RADIUS_M) on both sides of it -- and the
#: offset is within SUPPORT_MAX_ANGLE_RAD of the local normal. Otherwise the
#: point lies on the cap round the END of known paint (past a bend the
#: boundary has left the 66 deg field of view): an artefact, not a road, and
#: never pursued. A convex corner with both legs known stays supported: its
#: local axis joins the legs and the offset is its bisector.
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
#: A boundary cell not re-observed within this much travel is dropped. It
#: bounds how far the robot drives on remembered paint (e.g. the blind
#: quarter-turn round a 90 deg corner, ~0.31 m after last sight).
MEMORY_TRAVEL_M = 0.40
#: Memory ages by max(translation, half-width x rotation) per frame: on a
#: corner arc the two are the same motion, and spinning in place still ages
#: stale paint.
MEMORY_RADIUS_M = 0.50
#: Confidence while pursuing remembered paint only; CORE drives ~0.03 m/s.
MEMORY_CONFIDENCE = 0.6

#: Odometry whose stamp is further than this from the image's is no pose.
#: Equal to CORE line_follow stale_after_s: evidence older than that already
#: stops CORE, and a pose that old cannot place the paint in the image.
ODOM_MAX_SKEW_S = 0.30

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
    (MEMORY_CONFIDENCE on the tightest path): 0.40 m / 0.0242 m/s = 16.5 s.
    Travel ages memory only while odometry moves; this ages it by the clock,
    so memory outlives no drive it could honestly have been used for."""
    confidence = MEMORY_CONFIDENCE
    error = error_for_curvature(1.0 / _TIGHTEST_PATH_RADIUS_M, confidence)
    scale = (confidence - CORE_MIN_CONFIDENCE) / (1.0 - CORE_MIN_CONFIDENCE)
    slowest = CORE_CRUISE_M_S * scale * max(0.2, 1.0 - CORE_CURVE_SLOWDOWN * abs(error))
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

    def __init__(self, ground, width_px: int, height_px: int,
                 camera_x_offset_m: float) -> None:
        self.rows = int(round((BEV_X_MAX_M - BEV_X_MIN_M) / BEV_CELL_M))
        self.cols = int(round(2.0 * BEV_Y_HALF_M / BEV_CELL_M))
        i, j = np.mgrid[0:self.rows, 0:self.cols]
        self.x = BEV_X_MIN_M + (i + 0.5) * BEV_CELL_M
        self.y = BEV_Y_HALF_M - (j + 0.5) * BEV_CELL_M
        forward = self.x - camera_x_offset_m
        right = -self.y
        with np.errstate(invalid="ignore", divide="ignore"):
            ray = np.arctan2(ground.height_m, forward) - ground.pitch_rad
            row = ground.principal_y + ground.focal_px * np.tan(ray)
            denominator = (ground.focal_px * math.sin(ground.pitch_rad)
                           + (row - ground.principal_y) * math.cos(ground.pitch_rad))
            column = ground.principal_x + right * denominator / ground.height_m
        pixel_row = np.rint(row)
        pixel_col = np.rint(column)
        self.observable = ((forward >= BEV_MIN_RANGE_M) & (forward <= BEV_MAX_RANGE_M)
                           & (forward <= ground.max_range_m)
                           & np.isfinite(pixel_row) & np.isfinite(pixel_col)
                           & (pixel_row >= 0) & (pixel_row < height_px)
                           & (pixel_col >= 0) & (pixel_col < width_px))
        self._pixel_row = np.where(self.observable, pixel_row, 0).astype(np.intp)
        self._pixel_col = np.where(self.observable, pixel_col, 0).astype(np.intp)

    def sample(self, bright: np.ndarray) -> np.ndarray:
        return (bright[self._pixel_row, self._pixel_col] & self.observable).astype(np.uint8)

    def cell(self, x: float, y: float) -> tuple[int, int]:
        return (int(math.floor((x - BEV_X_MIN_M) / BEV_CELL_M)),
                int(math.floor((BEV_Y_HALF_M - y) / BEV_CELL_M)))


def _to_robot(points_odom: np.ndarray, pose) -> np.ndarray:
    x, y, yaw = pose
    dx, dy = points_odom[:, 0] - x, points_odom[:, 1] - y
    c, s = math.cos(yaw), math.sin(yaw)
    return np.stack([dx * c + dy * s, -dx * s + dy * c], axis=1)


def _to_odom(points_robot: np.ndarray, pose) -> np.ndarray:
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    return np.stack([x + points_robot[:, 0] * c - points_robot[:, 1] * s,
                     y + points_robot[:, 0] * s + points_robot[:, 1] * c], axis=1)


class _LineMemory:
    """One boundary line's paint cells in the odometry frame."""

    def __init__(self) -> None:
        self._cells = {}

    def __bool__(self) -> bool:
        return bool(self._cells)

    def clear(self) -> None:
        self._cells.clear()

    def remember(self, points_robot: np.ndarray, pose, odometer: float) -> None:
        for key in map(tuple, np.rint(_to_odom(points_robot, pose) / BEV_CELL_M).astype(int)):
            self._cells[key] = odometer

    def prune(self, pose, odometer: float) -> None:
        radius_cells = MEMORY_RADIUS_M / BEV_CELL_M
        px, py = pose[0] / BEV_CELL_M, pose[1] / BEV_CELL_M
        self._cells = {
            key: seen for key, seen in self._cells.items()
            if odometer - seen <= MEMORY_TRAVEL_M
            and math.hypot(key[0] - px, key[1] - py) <= radius_cells}

    def grid(self, view: BirdsEye, pose) -> np.ndarray:
        grid = np.zeros((view.rows, view.cols), np.uint8)
        if not self._cells:
            return grid
        points = _to_robot(np.array(list(self._cells.keys()), float) * BEV_CELL_M, pose)
        i = np.floor((points[:, 0] - BEV_X_MIN_M) / BEV_CELL_M).astype(int)
        j = np.floor((BEV_Y_HALF_M - points[:, 1]) / BEV_CELL_M).astype(int)
        inside = (i >= 0) & (i < view.rows) & (j >= 0) & (j < view.cols)
        grid[i[inside], j[inside]] = 1
        # Rotated lattice points can leave one-cell holes; close them.
        return cv2.morphologyEx(grid, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    def __len__(self) -> int:
        return len(self._cells)


class LaneEdgeFollower:
    """Hold the lane's LEFT boundary a half-width off, across bends and arcs.

    Per frame, with odometry pose (x, y, yaw) of base_link:
      1. bird's-eye view of the thresholded frame; paint components
         (PAINT_CONNECTIVITY). A frame whose observable floor is more than
         `washed_fraction` lit is None.
      2. the left boundary is the component overlapping the carried memory
         most (>= MATCH_MIN_CELLS). With no memory it is seeded only by a
         pair: a left and a right component, each >= MIN_BOUNDARY_LENGTH_M
         long, whose near ends lie a half-width (+/- half of that) either
         side, separated by 1.2..2.8 half-widths like `detect_lane_centre`.
         Crosswalk bars are shorter, pair worse than the true lines and are
         never connected to the boundary memory. When memory exists but
         nothing overlaps it, a pair reseeds only if its left line lies
         within RESEED_MAX_GAP_M of the memory.
      3. the lane's RIGHT boundary gets its own memory: the component
         overlapping it, else the pair's right line, else a fresh component
         >= MIN_BOUNDARY_LENGTH_M, right of the robot where nearest, whose
         paint comes within ~2 half-widths (+/- half) of the left memory
         and no closer.
      4. memories: boundary cells in the odometry frame, dropped after
         MEMORY_TRAVEL_M of travel unseen or beyond MEMORY_RADIUS_M. Only
         the component joined to the fresh line (else the largest) is used:
         a boundary is one continuous line.
      5. path: iso-line of the distance to the left boundary at half-width
         minus half a line width, the band piece nearest the robot (within
         PATH_MAX_OFFSET_M); only a supported lookahead point (see
         SUPPORT_MAX_ANGLE_RAD) is pursued. Failing that, the same from the
         right boundary: on the lap's convex left turns the left line leaves
         the 66 deg field of view while the right one crosses it.
      6. pursuit: k = 2 y / r^2 to the lookahead point, error from
         `error_for_curvature`. Confidence is the longer fresh boundary of
         this lane over LOOKAHEAD_M, floored at MEMORY_CONFIDENCE while
         remembered paint still carries a supported lookahead point; with
         none there is no output.
    With `corner_handoff`, a LaneCornerTracker watches for 90 deg corners
    and commits a turn only when step 5 finds no lookahead point; while it
    manoeuvres its output is used.
    """

    def __init__(self, *, camera_x_offset_m: float = 0.0,
                 corner_handoff: bool = False) -> None:
        if (isinstance(camera_x_offset_m, bool)
                or not isinstance(camera_x_offset_m, (int, float))
                or not math.isfinite(camera_x_offset_m)):
            raise ValueError("camera_x_offset_m must be a finite number")
        self._camera_x = float(camera_x_offset_m)
        self._corner = (LaneCornerTracker(camera_x_offset_m=self._camera_x)
                        if corner_handoff else None)
        self._view = None
        self._view_key = None
        self._left = _LineMemory()
        self._right = _LineMemory()
        self._odometer = 0.0
        self._last_pose = None
        self._fresh_at = None
        self.last = {}

    @property
    def state(self) -> str:
        if self._corner is not None and self._corner.state != "FOLLOW":
            return "CORNER_" + self._corner.state
        return "EDGE"

    def _forget(self) -> None:
        self._left.clear()
        self._right.clear()
        self._last_pose = None
        self._fresh_at = None

    def _birds_eye(self, ground, shape) -> BirdsEye:
        key = (ground.height_m, ground.pitch_rad, ground.focal_px, ground.principal_x,
               ground.principal_y, ground.max_range_m, shape[0], shape[1], self._camera_x)
        if key != self._view_key:
            self._view = BirdsEye(ground, shape[1], shape[0], self._camera_x)
            self._view_key = key
        return self._view

    def update(self, now_s: float, pose, bgr: np.ndarray, ground, *,
               lane_half_width_m: float,
               roi_top_fraction: float = 0.25,
               roi_bottom_fraction: float = 0.75,
               bright_threshold: int = _BRIGHT,
               washed_fraction: float = _WASHED_FRACTION) -> LaneObservation | None:
        if (isinstance(bright_threshold, bool) or not isinstance(bright_threshold, int)
                or not 1 <= bright_threshold <= 254):
            raise ValueError("bright_threshold must be an integer from 1 through 254")
        if (isinstance(lane_half_width_m, bool)
                or not isinstance(lane_half_width_m, (int, float))
                or not math.isfinite(lane_half_width_m) or not lane_half_width_m > 0.0):
            raise ValueError("lane_half_width_m must be a positive finite number")
        if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
            raise ValueError("camera frame must be a non-empty grayscale or BGR array")
        if pose is not None:
            pose = tuple(float(v) for v in pose)
            if len(pose) != 3 or not all(math.isfinite(v) for v in pose):
                pose = None
        if ground is None or pose is None:
            self._forget()
            if self._corner is not None:
                self._corner.update(now_s, None, bgr, ground,
                                    lane_half_width_m=lane_half_width_m,
                                    roi_top_fraction=roi_top_fraction,
                                    roi_bottom_fraction=roi_bottom_fraction,
                                    bright_threshold=bright_threshold,
                                    washed_fraction=washed_fraction)
            return None

        edge = self._follow(float(now_s), pose, bgr, ground, float(lane_half_width_m),
                            bright_threshold, float(washed_fraction))
        if self._corner is None:
            return edge
        manoeuvring = self._corner.state != "FOLLOW"
        corner = self._corner.update(
            now_s, pose, bgr, ground, lane_half_width_m=lane_half_width_m,
            roi_top_fraction=roi_top_fraction, roi_bottom_fraction=roi_bottom_fraction,
            bright_threshold=bright_threshold, washed_fraction=washed_fraction,
            commit_allowed=edge is None)
        # A committed manoeuvre owns the output until it ends, including the
        # frame it aborts on (None).
        if manoeuvring or self._corner.state != "FOLLOW":
            return corner
        return edge

    def _follow(self, now_s, pose, bgr, ground, half, bright_threshold, washed_fraction):
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        view = self._birds_eye(ground, gray.shape)
        paint = view.sample(gray > bright_threshold)
        self.last = {"paint": paint}
        observable = int(view.observable.sum())
        if observable == 0 or paint.sum() > washed_fraction * observable:
            return None

        if self._last_pose is not None:
            dx, dy = pose[0] - self._last_pose[0], pose[1] - self._last_pose[1]
            dyaw = math.atan2(math.sin(pose[2] - self._last_pose[2]),
                              math.cos(pose[2] - self._last_pose[2]))
            self._odometer += max(math.hypot(dx, dy), half * abs(dyaw))
        self._last_pose = pose

        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            paint, connectivity=PAINT_CONNECTIVITY)
        left_grid = self._left.grid(view, pose)
        left = self._match(labels, count, left_grid)
        seeded_right = None
        if left is None:
            left, seeded_right = self._seed(view, labels, stats, count, half)
            if left is not None and self._left and not self._continues(
                    labels == left, left_grid):
                left, seeded_right = None, None
        right = self._match(labels, count, self._right.grid(view, pose), exclude=left)
        if right is None:
            right = seeded_right
        if right is None and self._left:
            right = self._right_boundary(view, labels, stats, count, left, left_grid, half)

        fresh_length = 0.0
        for label, memory in ((left, self._left), (right, self._right)):
            if label is None:
                continue
            cells = labels == label
            fresh_length = max(fresh_length,
                               float(cells.sum()) * BEV_CELL_M ** 2 / LANE_LINE_WIDTH_M)
            memory.remember(np.stack([view.x[cells], view.y[cells]], axis=1), pose,
                            self._odometer)
        for memory in (self._left, self._right):
            memory.prune(pose, self._odometer)
        if left is not None or right is not None:
            self._fresh_at = now_s
        elif (self._fresh_at is None or now_s < self._fresh_at
              or now_s - self._fresh_at > MEMORY_MAX_AGE_S):
            self._forget()
            return None
        left_grid = self._one_line(self._left.grid(view, pose),
                                   None if left is None else labels == left)
        right_grid = self._one_line(self._right.grid(view, pose),
                                    None if right is None else labels == right)
        self.last.update(left_label=left, right_label=right, memory=left_grid,
                         right_memory=right_grid, fresh_length=fresh_length)

        # The left boundary leads; the right one of the same lane stands in
        # where the left has left the field of view (convex left turns).
        target, supported, source = None, False, None
        for name, grid in (("LEFT", left_grid), ("RIGHT", right_grid)):
            if not grid.any():
                continue
            target, supported = self._lookahead(view, grid, half)
            if supported:
                source = name
                break
        self.last.update(target=target, source=source, supported=supported)
        if target is None or not supported:
            return None
        confidence = min(1.0, fresh_length / LOOKAHEAD_M)
        confidence = max(confidence, MEMORY_CONFIDENCE)
        x, y = target
        curvature = 2.0 * y / (x * x + y * y)
        return LaneObservation(error=error_for_curvature(curvature, confidence),
                               confidence=confidence)

    @staticmethod
    def _one_line(memory_grid, fresh_cells):
        """The boundary is one continuous line: keep the memory component
        joined to what is seen now (else the largest). Pruning at ragged
        edges leaves fragments whose own iso-line circles would otherwise
        pass nearer the robot than the real path."""
        count, labels, stats, _ = cv2.connectedComponentsWithStats(memory_grid, connectivity=8)
        if count <= 2:
            return memory_grid
        if fresh_cells is not None and fresh_cells.any():
            keep = int(np.argmax(np.bincount(labels[fresh_cells], minlength=count)[1:])) + 1
        else:
            keep = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
        return (labels == keep).astype(np.uint8)

    @staticmethod
    def _match(labels, count, memory_grid, exclude=None):
        if count <= 1 or not memory_grid.any():
            return None
        size = 2 * MATCH_RADIUS_CELLS + 1
        near = cv2.dilate(memory_grid, np.ones((size, size), np.uint8)) > 0
        overlap = np.bincount(labels[near], minlength=count)
        overlap[0] = 0
        if exclude is not None:
            overlap[exclude] = 0
        best = int(np.argmax(overlap))
        return best if overlap[best] >= MATCH_MIN_CELLS else None

    @staticmethod
    def _continues(cells, memory_grid) -> bool:
        gap = cv2.distanceTransform((memory_grid == 0).astype(np.uint8),
                                    cv2.DIST_L2, cv2.DIST_MASK_PRECISE)[cells].min()
        return gap * BEV_CELL_M <= RESEED_MAX_GAP_M

    @staticmethod
    def _length(stats, label) -> float:
        return math.hypot(stats[label, cv2.CC_STAT_WIDTH],
                          stats[label, cv2.CC_STAT_HEIGHT]) * BEV_CELL_M

    def _seed(self, view, labels, stats, count, half):
        near_lateral = {}
        for label in range(1, count):
            if self._length(stats, label) < MIN_BOUNDARY_LENGTH_M:
                continue
            cells = labels == label
            xs = view.x[cells]
            near = xs <= xs.min() + 0.05
            near_lateral[label] = float(np.mean(view.y[cells][near]))
        lefts = [(lab, y) for lab, y in near_lateral.items() if 0.5 * half <= y <= 1.5 * half]
        rights = [(lab, y) for lab, y in near_lateral.items() if -1.5 * half <= y <= -0.5 * half]
        best = None
        for left, yl in lefts:
            for right, yr in rights:
                separation = yl - yr
                if not 1.2 * half <= separation <= 2.8 * half:
                    continue
                score = abs(separation - 2.0 * half)
                if best is None or score < best[0]:
                    best = (score, left, right)
        return (None, None) if best is None else best[1:]

    def _right_boundary(self, view, labels, stats, count, left, memory_grid, half):
        distance = cv2.distanceTransform((memory_grid == 0).astype(np.uint8),
                                         cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * BEV_CELL_M
        # Paint-edge to paint-edge distance for line centres ~2 half-widths apart.
        low, high = 1.5 * half - LANE_LINE_WIDTH_M, 2.5 * half - LANE_LINE_WIDTH_M
        best = None
        for label in range(1, count):
            if label == left or self._length(stats, label) < MIN_BOUNDARY_LENGTH_M:
                continue
            cells = labels == label
            # Right of the robot where it is nearest (a bent right line
            # crosses the view, so its mean may lie left).
            nearest = np.argmin(np.hypot(view.x[cells], view.y[cells]))
            if view.y[cells][nearest] >= 0.0:
                continue
            # Parallel lines: the closest approach is their spacing, even
            # where one bends and the rest of it runs away from the memory.
            gap = float(distance[cells].min())
            score = abs(gap + LANE_LINE_WIDTH_M - 2.0 * half)
            if low <= gap <= high and (best is None or score < best[0]):
                best = (score, label)
        return None if best is None else best[1]

    def _lookahead(self, view, boundary_grid, half):
        """(nearest supported path point at LOOKAHEAD_M..LOOKAHEAD_MAX_M,
        True), else (the LOOKAHEAD_M point or None, False).

        The iso-line runs on both sides of a boundary; the piece nearest the
        robot is the side it drives on.
        """
        distance = cv2.distanceTransform((boundary_grid == 0).astype(np.uint8),
                                         cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * BEV_CELL_M
        offset = half - LANE_LINE_WIDTH_M / 2.0
        band = (np.abs(distance - offset) <= PATH_BAND_HALF_M).astype(np.uint8)
        count, labels = cv2.connectedComponents(band, connectivity=8)
        if count <= 1:
            return None, False
        radius = np.hypot(view.x, view.y)
        in_band = labels > 0
        nearest = np.argmin(np.where(in_band, radius, np.inf))
        if radius.flat[nearest] > PATH_MAX_OFFSET_M:
            return None, False
        path = labels == labels.flat[nearest]
        self.last["path"] = path
        bearing = np.abs(np.arctan2(view.y, view.x))
        first = None
        steps = int(round((LOOKAHEAD_MAX_M - LOOKAHEAD_M) / LOOKAHEAD_STEP_M))
        for step in range(steps + 1):
            ring = path & (np.abs(radius - (LOOKAHEAD_M + step * LOOKAHEAD_STEP_M))
                           <= BEV_CELL_M)
            if not ring.any():
                continue
            candidates = np.where(ring, bearing, np.inf)
            best = np.argmin(candidates)
            if candidates.flat[best] > LOOKAHEAD_MAX_BEARING_RAD:
                continue
            # Average the ring cells within 1 cm of the best one.
            close = ring & (np.hypot(view.x - view.x.flat[best],
                                     view.y - view.y.flat[best]) <= 0.01)
            target = (float(view.x[close].mean()), float(view.y[close].mean()))
            if self._supported(view, boundary_grid, np.array(target)):
                return target, True
            if first is None:
                first = target
        return first, False

    @staticmethod
    def _supported(view, boundary_grid, target) -> bool:
        cells = boundary_grid > 0
        points = np.stack([view.x[cells], view.y[cells]], axis=1)
        nearest = points[np.argmin(np.hypot(*(points - target).T))]
        local = points[np.hypot(*(points - nearest).T) <= SUPPORT_RADIUS_M]
        offset = target - nearest
        if len(local) < 3 or not np.any(offset):
            return False
        centred = local - local.mean(axis=0)
        _, vectors = np.linalg.eigh(centred.T @ centred)
        tangent = vectors[:, -1]
        spread = (local - nearest) @ tangent
        interior = spread.min() <= -SUPPORT_RADIUS_M / 2 and spread.max() >= SUPPORT_RADIUS_M / 2
        along = abs(float(np.dot(offset, tangent))) / float(np.linalg.norm(offset))
        return bool(interior and along <= math.sin(SUPPORT_MAX_ANGLE_RAD))
