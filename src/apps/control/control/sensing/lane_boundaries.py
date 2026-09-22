"""Subject: both lane boundaries, centre-line following with a fallback ladder.

Builds on lane_bev's bird's-eye view and its left/right boundary memories
(LaneEdgeFollower finds and remembers both lines); only the target choice
differs (spec 2026-09-22 lane-network junction spike §4.2). The first tier
that yields a supported lookahead point wins:

  BOTH    both boundaries seen this frame: pursue the centre line, the
          locus equidistant from the two (it needs no lane-width assumption)
  ONE     a seen boundary: pursue its half-width iso-line (lane_bev rule)
  MEMORY  the fresh tiers found nothing supported (no line seen, or a seen
          one runs out ahead): pursue the remembered centre, else either
          remembered side, still inside lane_bev's travel and clock limits
          and within MEMORY_MAX_BEARING_RAD of the heading, at
          MEMORY_CONFIDENCE
  STOP    nothing: no output, CORE stops
Tier 4 (a committed manoeuvre) belongs to the junction prototypes.

Junction signal (for the overlay and the prototypes, never a decision):
LEFT_OPENS / RIGHT_OPENS when both boundaries are remembered but only the
other side is seen; BRANCH when a fresh line of boundary length belongs to
neither side, starts ahead inside the lane corridor (BRANCH_MAX_LATERAL)
and leaves it at BRANCH_MIN_ANGLE_RAD or more to the lane direction.

Support is lane_bev's test plus an end-of-line check (END_AXIS_RADIUS_M),
so no tier pursues the iso-line loop round the end of a line.
"""

import math

import cv2
import numpy as np

from .lane import LANE_LINE_WIDTH_M, LaneObservation
from .lane_bev import (
    BEV_CELL_M, BEV_X_MAX_M, LOOKAHEAD_M, MEMORY_CONFIDENCE, MIN_BOUNDARY_LENGTH_M,
    SUPPORT_RADIUS_M, LaneEdgeFollower,
)

TIERS = ("BOTH", "ONE", "MEMORY", "STOP")
#: Centre band: equal distance to both lines within this many cells.
CENTRE_BAND_CELLS = 2
#: The centre locus counts only between the lines, not far beyond them.
CENTRE_MAX_REACH = 1.5
#: Pure pursuit on a path of radius R sees its LOOKAHEAD_M point at bearing
#: asin(L / 2R). The steepest real lane centre on the 260919 track is the
#: 90 deg corner arc, R = h = 0.0925 m: 54.2 deg (the ring, R = 0.2514 m:
#: 17.4 deg). The iso-line round the END of a remembered line has
#: R = h - line/2 = 0.080 m: 69.6 deg. 60 deg keeps the corner with a
#: 5.8 deg margin and refuses to drive round a dead end on memory.
MEMORY_MAX_BEARING_RAD = math.radians(60.0)
#: A branch's near end lies ahead within this many half-widths of the
#: robot's line: the lane corridor extended by the line pair's tolerance.
BRANCH_MAX_LATERAL = 1.5
#: A branch crosses the lane direction at this angle or more. The track's
#: spokes meet the ring and corridors at >= 40 deg; a parallel line (the
#: adjacent lane, the wall ring footprint) reads ~0 deg.
BRANCH_MIN_ANGLE_RAD = math.radians(25.0)
#: The branch direction is its principal axis within this of its near end,
#: where it leaves the lane: the wall ring's footprint runs parallel beside
#: the west lane and then turns along the south wall, so its whole-body
#: axis is diagonal.
BRANCH_AXIS_RADIUS_M = 0.06
#: lane_bev's support test takes the local axis over SUPPORT_RADIUS_M
#: (20 mm), less than the 25 mm line width: at a line's round end cap that
#: axis turns across the line and a point straight past the end reads as
#: supported (the loop round a dead end, 128 deg of turn on memory). Here
#: the nearest point must also be interior along the axis over two line
#: widths.
END_AXIS_RADIUS_M = 2.0 * LANE_LINE_WIDTH_M


def _axis(points):
    """Unit principal axis of (n, 2) points."""
    centred = points - points.mean(axis=0)
    return np.linalg.eigh(centred.T @ centred)[1][:, -1]


class LaneBoundaryTracker(LaneEdgeFollower):
    """Centre-line follower over both boundaries; see the module docstring."""

    def __init__(self, *, camera_x_offset_m: float = 0.0) -> None:
        super().__init__(camera_x_offset_m=camera_x_offset_m, corner_handoff=False)
        self.tier = "STOP"

    @property
    def state(self) -> str:
        return self.tier

    def update(self, now_s, pose, bgr, ground, **kwargs) -> LaneObservation | None:
        self.tier = "STOP"
        self.last = {}
        return super().update(now_s, pose, bgr, ground, **kwargs)

    def _pursue(self, view, found, half):
        left_seen, right_seen = found["left"] is not None, found["right"] is not None
        left_grid, right_grid = found["left_grid"], found["right_grid"]
        self.last["junction"] = self._junction(view, found, left_seen, right_seen, half)
        target, supported = None, False
        if left_seen and right_seen:
            target, supported = self._centre(view, left_grid, right_grid, half)
            if supported:
                self.tier = "BOTH"
        if not supported:
            for seen, grid in ((left_seen, left_grid), (right_seen, right_grid)):
                if seen and grid.any():
                    target, supported = self._lookahead(view, grid, half)
                    if supported:
                        self.tier = "ONE"
                        break
        if not supported:
            # Only what the fresh tiers did not already try: the centre
            # unless both were seen, a side unless it was seen.
            tries = []
            if left_grid.any() and right_grid.any() and not (left_seen and right_seen):
                tries.append(lambda: self._centre(view, left_grid, right_grid, half))
            tries += [lambda grid=grid: self._lookahead(view, grid, half)
                      for seen, grid in ((left_seen, left_grid), (right_seen, right_grid))
                      if not seen and grid.any()]
            for find in tries:
                target, supported = find()
                if supported and (abs(math.atan2(target[1], target[0]))
                                  <= MEMORY_MAX_BEARING_RAD):
                    self.tier = "MEMORY"
                    break
                supported = False
        self.last.update(target=target, supported=supported, tier=self.tier)
        if target is None or not supported:
            self.tier = "STOP"
            self.last["tier"] = "STOP"
            return None
        if self.tier == "MEMORY":
            confidence = MEMORY_CONFIDENCE
        else:
            confidence = max(min(1.0, found["fresh_length"] / LOOKAHEAD_M), MEMORY_CONFIDENCE)
        return self._observation(target, confidence)

    def _centre(self, view, left_grid, right_grid, half):
        dl = cv2.distanceTransform((left_grid == 0).astype(np.uint8),
                                   cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * BEV_CELL_M
        dr = cv2.distanceTransform((right_grid == 0).astype(np.uint8),
                                   cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * BEV_CELL_M
        reach = CENTRE_MAX_REACH * half
        band = ((np.abs(dl - dr) <= CENTRE_BAND_CELLS * BEV_CELL_M)
                & (dl <= reach) & (dr <= reach)).astype(np.uint8)
        self.last["centre_band"] = band

        def supported(target):
            return (self._supported(view, left_grid, target)
                    and self._supported(view, right_grid, target))

        return self._band_lookahead(view, band, supported)

    @staticmethod
    def _supported(view, boundary_grid, target) -> bool:
        if not LaneEdgeFollower._supported(view, boundary_grid, target):
            return False
        cells = boundary_grid > 0
        points = np.stack([view.x[cells], view.y[cells]], axis=1)
        nearest = points[np.argmin(np.hypot(*(points - target).T))]
        local = points[np.hypot(*(points - nearest).T) <= END_AXIS_RADIUS_M]
        spread = (local - nearest) @ _axis(local)
        return bool(spread.min() <= -SUPPORT_RADIUS_M / 2
                    and spread.max() >= SUPPORT_RADIUS_M / 2)

    @staticmethod
    def _lane_axis(view, found):
        """Lane direction: the boundary memory within LOOKAHEAD_M of the
        robot (left, else right), else the heading."""
        near = np.hypot(view.x, view.y) <= LOOKAHEAD_M
        for grid in (found["left_grid"], found["right_grid"]):
            cells = (grid > 0) & near
            if cells.sum() >= 3:
                return _axis(np.stack([view.x[cells], view.y[cells]], axis=1))
        return np.array([1.0, 0.0])

    def _junction(self, view, found, left_seen, right_seen, half):
        remembered = bool(self._left) and bool(self._right)
        if remembered and left_seen and not right_seen:
            return "RIGHT_OPENS"
        if remembered and right_seen and not left_seen:
            return "LEFT_OPENS"
        labels, stats, count = found["labels"], found["stats"], found["count"]
        lane_axis = None
        for label in range(1, count):
            if (label in (found["left"], found["right"])
                    or self._length(stats, label) < MIN_BOUNDARY_LENGTH_M):
                continue
            cells = labels == label
            points = np.stack([view.x[cells], view.y[cells]], axis=1)
            near_end = points[np.argmin(np.hypot(*points.T))]
            x, y = near_end
            if not (0.0 < x <= BEV_X_MAX_M and abs(y) <= BRANCH_MAX_LATERAL * half):
                continue
            if lane_axis is None:
                lane_axis = self._lane_axis(view, found)
            leaving = points[np.hypot(*(points - near_end).T) <= BRANCH_AXIS_RADIUS_M]
            cosine = min(1.0, abs(float(np.dot(_axis(leaving), lane_axis))))
            if math.acos(cosine) >= BRANCH_MIN_ANGLE_RAD:
                return "BRANCH"
        return None
