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
no output: the boundary memory cannot be carried without odometry.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .bev_cache import cached_birds_eye
from .lane import (
    LANE_LINE_WIDTH_M,
    LaneCornerTracker,
    LaneObservation,
    _BRIGHT,
    _WASHED_FRACTION,
)
from .lane_bev_helpers import (
    BEV_CELL_M,
    BEV_MAX_RANGE_M,
    BEV_MIN_RANGE_M,
    BEV_X_MAX_M,
    BEV_X_MIN_M,
    BEV_Y_HALF_M,
    CORE_CRUISE_M_S,
    CORE_CURVE_SLOWDOWN,
    CORE_MIN_CONFIDENCE,
    CORE_STEERING_GAIN,
    LOOKAHEAD_M,
    LOOKAHEAD_MAX_BEARING_RAD,
    LOOKAHEAD_MAX_M,
    LOOKAHEAD_STEP_M,
    MATCH_MIN_CELLS,
    MATCH_RADIUS_CELLS,
    MEMORY_CONFIDENCE,
    MEMORY_MAX_AGE_S,
    MEMORY_RADIUS_M,
    MEMORY_TRAVEL_M,
    MIN_BOUNDARY_LENGTH_M,
    ODOM_MAX_SKEW_S,
    ODOM_MAX_STEP_M,
    PAINT_CONNECTIVITY,
    PATH_BAND_HALF_M,
    PATH_MAX_OFFSET_M,
    RESEED_MAX_GAP_M,
    RIGHT_MATE_MAX_LATERAL_FRACTION,
    SUPPORT_MAX_ANGLE_RAD,
    SUPPORT_RADIUS_M,
    BirdsEye,
    _LineMemory,
    _TIGHTEST_PATH_RADIUS_M,
    _memory_max_age_s,
    _to_odom,
    _to_robot,
    error_for_curvature,
    pose_if_fresh,
)
from .lane_boundary_identity import stationary_boundary_replaced


class LaneEdgeFollower:
    """Hold the lane's LEFT boundary a half-width off, across bends and arcs."""

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
        self._pose_fault = False
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

    _birds_eye = cached_birds_eye

    def _allow_unseen_memory(self) -> bool:
        # Route followers may override only with an active, aligned map gate.
        return False

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
        if self._pose_fault:
            self.last = {"reason": "odom_discontinuity"}
            return None
        if pose is not None and self._last_pose is not None:
            dx, dy = pose[0] - self._last_pose[0], pose[1] - self._last_pose[1]
            dyaw = math.remainder(pose[2] - self._last_pose[2], 2.0 * math.pi)
            if max(math.hypot(dx, dy), float(lane_half_width_m) * abs(dyaw)) > ODOM_MAX_STEP_M:
                self._forget()
                self._pose_fault = True
                self.last = {"reason": "odom_discontinuity"}
                return None
        if ground is None or pose is None:
            self._forget()
            self.last = {}
            if ground is not None:
                self._follow(float(now_s), None, bgr, ground, float(lane_half_width_m),
                             bright_threshold, float(washed_fraction))
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
        if self.last.get("reason") == "boundary_identity_unconfirmed":
            return None  # a corner handoff cannot turn on the rejected stripe
        if self._corner is None:
            return edge
        manoeuvring = self._corner.state != "FOLLOW"
        corner = self._corner.update(
            now_s, pose, bgr, ground, lane_half_width_m=lane_half_width_m,
            roi_top_fraction=roi_top_fraction, roi_bottom_fraction=roi_bottom_fraction,
            bright_threshold=bright_threshold, washed_fraction=washed_fraction,
            commit_allowed=edge is None)
        if manoeuvring or self._corner.state != "FOLLOW":
            return corner
        return edge

    def _follow(self, now_s, pose, bgr, ground, half, bright_threshold, washed_fraction):
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        view = self._birds_eye(ground, gray.shape)
        paint = view.sample(gray > bright_threshold)
        self.last = {"paint": paint}
        observable = int(view.observable.sum())
        if observable == 0:
            return None
        if paint.sum() > washed_fraction * observable:
            self.last["reason"] = "washed"
            return None
        if pose is None:
            self.last = {}
            return None

        stationary = False
        if self._last_pose is not None:
            dx, dy = pose[0] - self._last_pose[0], pose[1] - self._last_pose[1]
            dyaw = math.atan2(math.sin(pose[2] - self._last_pose[2]),
                              math.cos(pose[2] - self._last_pose[2]))
            stationary = math.hypot(dx, dy) <= 0.002 and abs(dyaw) <= math.radians(1)
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
        right_grid = self._right.grid(view, pose)
        right = self._match(labels, count, right_grid, exclude=left)
        if right is None:
            right = seeded_right
        if right is None and self._left:
            right = self._right_boundary(view, labels, stats, count, left, left_grid, half)

        if stationary and ((left is not None and self._left and stationary_boundary_replaced(
                labels == left, left_grid > 0, view.y)) or
                (right is not None and self._right and stationary_boundary_replaced(
                    labels == right, right_grid > 0, view.y))):
            self._forget()
            if self._corner is not None:
                self._corner._abort()
            self.last = {"reason": "boundary_identity_unconfirmed"}
            return None

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
        elif not self._allow_unseen_memory():
            return None  # neither lane boundary is observed: no drive evidence
        left_grid = self._one_line(self._left.grid(view, pose),
                                   None if left is None else labels == left)
        right_grid = self._one_line(self._right.grid(view, pose),
                                    None if right is None else labels == right)
        self.last.update(left_label=left, right_label=right, memory=left_grid,
                         right_memory=right_grid, fresh_length=fresh_length)
        return self._pursue(view, {
            "left": left, "right": right, "labels": labels, "stats": stats, "count": count,
            "left_grid": left_grid, "right_grid": right_grid, "fresh_length": fresh_length,
        }, half)

    def _pursue(self, view, found, half):
        """Target selection. edge_left: the left boundary leads; the right one
        of the same lane stands in where the left has left the field of view
        (convex left turns)."""
        target, supported, source = None, False, None
        candidates = (("LEFT", found["left_grid"]), ("RIGHT", found["right_grid"]))
        if (found.get("left") is None and found.get("right") is not None
                and found["left_grid"].any() and found["right_grid"].any()):
            left_target, left_supported = self._lookahead(view, found["left_grid"], half)
            right_target, right_supported = self._lookahead(view, found["right_grid"], half)
            if (left_supported and right_supported
                    and abs(right_target[1]) <= half * RIGHT_MATE_MAX_LATERAL_FRACTION
                    and abs(left_target[1] - right_target[1]) > LANE_LINE_WIDTH_M):
                # A forward observed mate beats the old line's turning end cap.
                candidates = candidates[1:]
        for name, grid in candidates:
            if not grid.any():
                continue
            if name == "RIGHT":
                near = (view.x >= BEV_MIN_RANGE_M) & (view.x <= LOOKAHEAD_MAX_M)
                left_y = view.y[(found["left_grid"] > 0) & near]
                right_y = view.y[(grid > 0) & near]
                if len(left_y) and len(right_y) and not (
                        1.2 * half <= np.median(left_y) - np.median(right_y) <= 2.8 * half):
                    continue  # a branch or wall line is not this lane's missing boundary
            target, supported = self._lookahead(view, grid, half)
            if supported:
                source = name
                break
        self.last.update(target=target, source=source, supported=supported)
        if target is None or not supported:
            return None
        confidence = min(1.0, found["fresh_length"] / LOOKAHEAD_M)
        confidence = max(confidence, MEMORY_CONFIDENCE)
        return self._observation(target, confidence)

    @staticmethod
    def _observation(target, confidence):
        x, y = target
        curvature = 2.0 * y / (x * x + y * y)
        return LaneObservation(error=error_for_curvature(curvature, confidence),
                               confidence=confidence)

    @staticmethod
    def _one_line(memory_grid, fresh_cells):
        """The boundary is one continuous line: keep the memory component
        joined to what is seen now (else the largest)."""
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
        low, high = 1.5 * half - LANE_LINE_WIDTH_M, 2.5 * half - LANE_LINE_WIDTH_M
        best = None
        for label in range(1, count):
            if label == left or self._length(stats, label) < MIN_BOUNDARY_LENGTH_M:
                continue
            cells = labels == label
            nearest = np.argmin(np.hypot(view.x[cells], view.y[cells]))
            if view.y[cells][nearest] >= 0.0:
                continue
            gap = float(distance[cells].min())
            score = abs(gap + LANE_LINE_WIDTH_M - 2.0 * half)
            if low <= gap <= high and (best is None or score < best[0]):
                best = (score, label)
        return None if best is None else best[1]

    def _lookahead(self, view, boundary_grid, half):
        """(nearest supported path point at LOOKAHEAD_M..LOOKAHEAD_MAX_M,
        True), else (the LOOKAHEAD_M point or None, False)."""
        distance = cv2.distanceTransform((boundary_grid == 0).astype(np.uint8),
                                         cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * BEV_CELL_M
        offset = half - LANE_LINE_WIDTH_M / 2.0
        band = (np.abs(distance - offset) <= PATH_BAND_HALF_M).astype(np.uint8)
        return self._band_lookahead(
            view, band, lambda target: self._supported(view, boundary_grid, target))

    def _band_lookahead(self, view, band, supported):
        """Pursuit point on the band piece nearest the robot."""
        count, labels = cv2.connectedComponents(band, connectivity=8)
        if count <= 1:
            return None, False
        radius = view.radius
        in_band = labels > 0
        nearest = np.argmin(np.where(in_band, radius, np.inf))
        if radius.flat[nearest] > PATH_MAX_OFFSET_M:
            return None, False
        path = labels == labels.flat[nearest]
        self.last["path"] = path
        cells = np.flatnonzero(path)
        px, py = view.x.flat[cells], view.y.flat[cells]
        pr, pb = radius.flat[cells], view.bearing.flat[cells]
        first = None
        steps = int(round((LOOKAHEAD_MAX_M - LOOKAHEAD_M) / LOOKAHEAD_STEP_M))
        for step in range(steps + 1):
            ring = np.abs(pr - (LOOKAHEAD_M + step * LOOKAHEAD_STEP_M)) <= BEV_CELL_M
            if not ring.any():
                continue
            candidates = np.where(ring, pb, np.inf)
            best = np.argmin(candidates)
            if candidates[best] > LOOKAHEAD_MAX_BEARING_RAD:
                continue
            close = ring & (np.hypot(px - px[best], py - py[best]) <= 0.01)
            target = (float(px[close].mean()), float(py[close].mean()))
            if supported(np.array(target)):
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
