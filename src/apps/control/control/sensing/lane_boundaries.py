"""Subject: both lane boundaries, centre-line following with a fallback ladder.

Builds on lane_bev's bird's-eye view and its left/right boundary memories
(LaneEdgeFollower finds and remembers both lines); only the target choice
differs (spec 2026-09-22 lane-network junction spike §4.2):

  BOTH    both boundaries seen this frame: pursue the centre line, the
          locus equidistant from the two (it needs no lane-width assumption)
  ONE     one boundary seen: pursue its half-width iso-line (lane_bev rule)
  MEMORY  none seen, remembered ones still inside lane_bev's travel and
          clock limits: pursue them at MEMORY_CONFIDENCE
  STOP    nothing: no output, CORE stops
Tier 4 (a committed manoeuvre) belongs to the junction prototypes.

Junction signal (for the overlay and the prototypes, never a decision):
LEFT_OPENS / RIGHT_OPENS when both boundaries are remembered but only the
other side is seen, BRANCH when a fresh line of boundary length belongs to
neither side.
"""

import cv2
import numpy as np

from .lane import LaneObservation
from .lane_bev import (
    BEV_CELL_M, LOOKAHEAD_M, MEMORY_CONFIDENCE, MIN_BOUNDARY_LENGTH_M, LaneEdgeFollower,
)

TIERS = ("BOTH", "ONE", "MEMORY", "STOP")
#: Centre band: equal distance to both lines within this many cells.
CENTRE_BAND_CELLS = 2
#: The centre locus counts only between the lines, not far beyond them.
CENTRE_MAX_REACH = 1.5


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
        self.last["junction"] = self._junction(found, left_seen, right_seen)
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
        if not supported and not (left_seen or right_seen):
            if left_grid.any() and right_grid.any():
                target, supported = self._centre(view, left_grid, right_grid, half)
            for grid in (left_grid, right_grid):
                if supported:
                    break
                if grid.any():
                    target, supported = self._lookahead(view, grid, half)
            if supported:
                self.tier = "MEMORY"
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

    def _junction(self, found, left_seen, right_seen):
        remembered = bool(self._left) and bool(self._right)
        if remembered and left_seen and not right_seen:
            return "RIGHT_OPENS"
        if remembered and right_seen and not left_seen:
            return "LEFT_OPENS"
        stats, count = found["stats"], found["count"]
        for label in range(1, count):
            if label in (found["left"], found["right"]):
                continue
            if self._length(stats, label) >= MIN_BOUNDARY_LENGTH_M:
                return "BRANCH"
        return None
