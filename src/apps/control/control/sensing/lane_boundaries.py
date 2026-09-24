"""Subject: both lane boundaries, centre-line following with a fallback ladder.

Builds on lane_bev's bird's-eye view and its left/right boundary memories
(LaneEdgeFollower finds and remembers both lines); only the target choice
differs (spec 2026-09-22 lane-network junction spike §4.2). The first tier
that yields a supported lookahead point wins:

  BOTH    both boundaries seen this frame: pursue the centre line, the
          locus equidistant from the two (it needs no lane-width assumption)
  ONE     a seen boundary: pursue its half-width iso-line (lane_bev rule),
          confidence capped at ONE_MAX_CONFIDENCE
  MEMORY  the fresh tiers found nothing supported (no line seen, or a seen
          one runs out ahead): pursue the remembered centre, else either
          remembered side, still inside lane_bev's travel and clock limits
          and within MEMORY_MAX_BEARING_RAD of the heading, at
          MEMORY_CONFIDENCE
  STOP    nothing: no output, CORE stops
Confidence is CORE's speed scale, so each lower tier also drives slower.
Tier 4 (a committed manoeuvre) belongs to the junction prototypes.

Junction signal (for the overlay and the prototypes, never a decision):
LEFT_OPENS / RIGHT_OPENS when one side is seen and the other's memory ENDS
ahead while the seen line runs on straight past that end (OPENS_REACH_M,
OPENS_MAX_ANGLE_RAD); at a convex corner the seen outer line itself turns,
so there is no OPENS. BRANCH when a fresh line of boundary length belongs
to neither side, starts ahead inside the lane corridor (BRANCH_MAX_LATERAL)
and leaves the boundary memory nearest it at BRANCH_MIN_ANGLE_RAD or more,
held over BRANCH_MIN_TRAVEL_M of travel.

Support is lane_bev's test plus an end-of-line check (END_AXIS_RADIUS_M),
so no tier pursues the iso-line loop round the end of a line.
"""

import math

import cv2
import numpy as np

from .lane import LANE_LINE_WIDTH_M, LaneObservation
from .lane_bev import (
    BEV_CELL_M, LOOKAHEAD_M, MEMORY_CONFIDENCE, MIN_BOUNDARY_LENGTH_M,
    SUPPORT_RADIUS_M, LaneEdgeFollower,
)

TIERS = ("BOTH", "ONE", "MEMORY", "STOP")
#: Centre band: equal distance to both lines within this many cells.
CENTRE_BAND_CELLS = 2
#: The centre locus counts only between the lines, not far beyond them.
CENTRE_MAX_REACH = 1.5
#: Defence in depth for memory pursuit (the dead-end loop is stopped by the
#: end-of-line support check, END_AXIS_RADIUS_M, not by this). Pure pursuit
#: to a point at bearing b and range L demands curvature 2 sin(b) / L, so
#: at LOOKAHEAD_M this bounds a MEMORY target to paths no tighter than
#: R = 0.15 / (2 sin 60 deg) = 0.087 m: the tightest real lane centre on
#: the 260919 track is the 90 deg corner arc, R = h = 0.0925 m (bearing
#: 54.2 deg; the ring, R = 0.2514 m: 17.4 deg). A remembered line across
#: the path is refused (test_memory_bearing_bound_refuses_a_line_across_the_path).
MEMORY_MAX_BEARING_RAD = math.radians(60.0)
#: ONE offsets a single line by the assumed half-width, so a lane narrower
#: or wider than assumed puts it off-centre (17.5 mm for a 150 mm lane)
#: where BOTH is not. Capping its confidence caps CORE's speed scale at
#: (0.8 - 0.35) / 0.65 = 0.69 of BOTH, above MEMORY's (0.6: 0.38).
ONE_MAX_CONFIDENCE = 0.8
#: A branch's near end lies ahead within this many half-widths of the
#: robot's line: the lane corridor extended by the line pair's tolerance.
BRANCH_MAX_LATERAL = 1.5
#: A branch crosses the lane direction at this angle or more. The track's
#: spokes meet the ring and corridors at >= 40 deg; a parallel line (the
#: adjacent lane, the wall ring footprint) reads ~0 deg.
BRANCH_MIN_ANGLE_RAD = math.radians(25.0)
#: The branch direction is its principal axis within this of its near end,
#: where it leaves the lane (the wall footprint in stl_world runs parallel
#: beside the west lane, then turns along the south wall: its whole-body
#: axis is diagonal); the lane direction is the boundary memory within
#: this of the memory point nearest that end. Measured from the robot
#: instead, a sliver beside a chevron's diagonal leg read 25-64 deg.
BRANCH_AXIS_RADIUS_M = 0.06
#: BRANCH must hold over this much travel. Lap and east-curve replays
#: showed single-frame raw branches, and a 3-frame one (0.032 m) where the
#: wall footprint crossed the view at its 0.43 m edge; the 45 deg mouth
#: holds for 9 frames (0.128 m). One frame at cruise is 0.016 m.
BRANCH_MIN_TRAVEL_M = 0.05
#: OPENS: past the unseen side's end, the seen line is looked at over this
#: reach along the lane. At a 90 deg corner the outer line turns ~2h +
#: line/2 = 0.2 m past the inner line's end.
OPENS_REACH_M = 0.25
#: ... and must run within this of the lane direction there to be a mouth.
OPENS_MAX_ANGLE_RAD = math.radians(15.0)
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
        self._frame = 0
        self._branch_frame = None
        self._branch_from = 0.0

    @property
    def state(self) -> str:
        return self.tier

    def update(self, now_s, pose, bgr, ground, **kwargs) -> LaneObservation | None:
        self.tier = "STOP"
        self.last = {}
        self._frame += 1
        return super().update(now_s, pose, bgr, ground, **kwargs)

    def _pursue(self, view, found, half):
        left_seen, right_seen = found["left"] is not None, found["right"] is not None
        left_grid, right_grid = found["left_grid"], found["right_grid"]
        self.last["junction"] = self._junction(view, found, left_seen, right_seen, half)
        target, supported, source = None, False, None
        if left_seen and right_seen:
            target, supported = self._centre(view, left_grid, right_grid, half)
            if supported:
                self.tier = "BOTH"
                source = "CENTRE"
        if not supported:
            for seen, grid, name in ((left_seen, left_grid, "LEFT"),
                                     (right_seen, right_grid, "RIGHT")):
                if seen and grid.any():
                    target, supported = self._lookahead(view, grid, half)
                    if supported:
                        self.tier = "ONE"
                        source = name
                        break
        if not supported:
            # Only what the fresh tiers did not already try: the centre
            # unless both were seen, a side unless it was seen.
            tries = []
            if left_grid.any() and right_grid.any() and not (left_seen and right_seen):
                tries.append(("CENTRE", lambda: self._centre(view, left_grid, right_grid, half)))
            tries += [(name, lambda grid=grid: self._lookahead(view, grid, half))
                      for seen, grid, name in ((left_seen, left_grid, "LEFT"),
                                               (right_seen, right_grid, "RIGHT"))
                      if not seen and grid.any()]
            for name, find in tries:
                target, supported = find()
                if supported and (abs(math.atan2(target[1], target[0]))
                                  <= MEMORY_MAX_BEARING_RAD):
                    self.tier = "MEMORY"
                    source = name
                    break
                supported = False
        self.last.update(target=target, supported=supported, tier=self.tier, source=source)
        if target is None or not supported:
            self.tier = "STOP"
            self.last["tier"] = "STOP"
            self.last["source"] = None
            return None
        if self.tier == "MEMORY":
            confidence = MEMORY_CONFIDENCE
        else:
            confidence = max(min(1.0, found["fresh_length"] / LOOKAHEAD_M), MEMORY_CONFIDENCE)
            if self.tier == "ONE":
                confidence = min(confidence, ONE_MAX_CONFIDENCE)
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
    def _lane_axis(view, found, point):
        """Lane direction at `point`: the boundary memory within
        BRANCH_AXIS_RADIUS_M of the memory point nearest it, else the
        heading."""
        best = None
        for grid in (found["left_grid"], found["right_grid"]):
            cells = grid > 0
            if cells.sum() < 3:
                continue
            points = np.stack([view.x[cells], view.y[cells]], axis=1)
            gaps = np.hypot(*(points - point).T)
            nearest = int(np.argmin(gaps))
            if best is None or gaps[nearest] < best[0]:
                best = (gaps[nearest], points, points[nearest])
        if best is not None:
            _, points, anchor = best
            local = points[np.hypot(*(points - anchor).T) <= BRANCH_AXIS_RADIUS_M]
            if len(local) >= 3:
                return _axis(local)
        return np.array([1.0, 0.0])

    @staticmethod
    def _opens(view, seen_grid, unseen_grid, half) -> bool:
        """The unseen side's memory ends ahead in the corridor and the seen
        line runs on straight past that end."""
        unseen = np.stack([view.x[unseen_grid > 0], view.y[unseen_grid > 0]], axis=1)
        seen = np.stack([view.x[seen_grid > 0], view.y[seen_grid > 0]], axis=1)
        if len(unseen) < 3 or len(seen) < 3:
            return False
        direction = _axis(unseen)
        if direction[0] < 0.0:
            direction = -direction
        along = unseen @ direction
        end = unseen[int(np.argmax(along))]
        if not (end[0] > 0.0 and abs(end[1]) <= BRANCH_MAX_LATERAL * half):
            return False
        reach = seen @ direction - along.max()
        past = seen[(reach >= 0.0) & (reach <= OPENS_REACH_M)]
        if len(past) < 3 or np.ptp(past @ direction) < BRANCH_AXIS_RADIUS_M:
            return False
        cosine = min(1.0, abs(float(np.dot(_axis(past), direction))))
        return math.acos(cosine) <= OPENS_MAX_ANGLE_RAD

    def _junction(self, view, found, left_seen, right_seen, half):
        signal = self._raw_junction(view, found, left_seen, right_seen, half)
        if signal != "BRANCH":
            return signal
        if self._branch_frame != self._frame - 1:
            self._branch_from = self._odometer
        self._branch_frame = self._frame
        return signal if self._odometer - self._branch_from >= BRANCH_MIN_TRAVEL_M else None

    def _raw_junction(self, view, found, left_seen, right_seen, half):
        if left_seen != right_seen and self._left and self._right:
            seen, unseen = ((found["left_grid"], found["right_grid"]) if left_seen
                            else (found["right_grid"], found["left_grid"]))
            if self._opens(view, seen, unseen, half):
                return "RIGHT_OPENS" if left_seen else "LEFT_OPENS"
        labels, stats, count = found["labels"], found["stats"], found["count"]
        for label in range(1, count):
            if (label in (found["left"], found["right"])
                    or self._length(stats, label) < MIN_BOUNDARY_LENGTH_M):
                continue
            cells = labels == label
            points = np.stack([view.x[cells], view.y[cells]], axis=1)
            near_end = points[np.argmin(np.hypot(*points.T))]
            x, y = near_end
            if not (x > 0.0 and abs(y) <= BRANCH_MAX_LATERAL * half):
                continue
            leaving = points[np.hypot(*(points - near_end).T) <= BRANCH_AXIS_RADIUS_M]
            lane_axis = self._lane_axis(view, found, near_end)
            cosine = min(1.0, abs(float(np.dot(_axis(leaving), lane_axis))))
            if math.acos(cosine) >= BRANCH_MIN_ANGLE_RAD:
                self.last["branch_mask"] = cells
                return "BRANCH"
        return None
