"""Hybrid route_ab: prototype B's pose steering prototype A's camera-first logic.

User decision 2026-09-23 (docs/validation/lane-junction-spike/2026-09-23/
comparison.md). A lost two Gazebo scenarios and collapses under odometry
drift because it places the route with dead-reckoned odometry; B is robust
to drift but its route pursuit swings on the steep NE spoke exit. Per frame:

  pose       PaintLocalizer (B) over the checked-in paint map, started at the
             known start pose, fed the odometry pose (increments only)
  steering   RouteCameraFollower (A) with `map_frame=True`, fed the
             estimate as its pose: the route-gated seed, the select and the
             bounded MANOEUVRE all place the route with the corrected pose;
             the camera tracker still owns lane keeping
  fail-closed B's conditions first: no estimate, spread over MAX_SPREAD_M or
             match under MIN_MATCH is no output (state LOCALISE_STOP,
             `last["reason"]` NO_ESTIMATE / SPREAD / MATCH) and A is not
             updated that frame; then A's own STOP / MANOEUVRE_ABORT
  cross-check B's camera/route disagreement (route_map.disagreement) on A's
             tracker, placed by the estimate: DISAGREE_MIN_FRAMES of the
             last DISAGREE_WINDOW compared frames over MAX_DISAGREE_M is no
             output (LOCALISE_STOP, reason DISAGREE)
  confidence min(A's output confidence, B's confidence_for(match, spread)),
             so a weak localisation also slows CORE. The error is
             re-encoded at the lower confidence so the commanded curvature
             is A's (`_with_confidence`)

The cross-check is kept because A's route gate alone does not catch a
biased estimate: offline, with the estimate shifted +-30 / +-50 mm, 4 of 48
runs drove to the end on the right branch 44-57 mm off the centreline
without stopping; with the check all 48 stop, none unstopped
(test_a_biased_estimate_is_not_driven_off_the_lane).
"""

from __future__ import annotations

import math

from .lane import LaneObservation
from .lane_bev import (
    CORE_CRUISE_M_S,
    CORE_CURVE_SLOWDOWN,
    CORE_MIN_CONFIDENCE,
    CORE_STEERING_GAIN,
    error_for_curvature,
)
from .paint_localizer import PaintLocalizer, PaintMap
from .route_camera import RouteCameraFollower
from .route_map import (
    DISAGREE_MIN_FRAMES,
    DISAGREE_WINDOW,
    MAX_DISAGREE_M,
    MAX_SPREAD_M,
    MIN_MATCH,
    _bundle_map,
    centreline_pieces,
    confidence_for,
    disagreement,
)


def _with_confidence(observation: LaneObservation, confidence: float) -> LaneObservation:
    """`observation` at a confidence no higher than `confidence`, its error
    re-encoded so CORE commands the same path curvature (inverse of
    lane_bev.error_for_curvature: |k| = g|e| / (V (1 - c|e|)))."""
    if confidence >= observation.confidence:
        return observation
    scale = (observation.confidence - CORE_MIN_CONFIDENCE) / (1.0 - CORE_MIN_CONFIDENCE)
    speed = CORE_CRUISE_M_S * max(0.0, min(1.0, scale))
    magnitude = abs(observation.error)
    if speed <= 0.0 or magnitude == 0.0:
        return LaneObservation(error=observation.error, confidence=confidence)
    curvature = -math.copysign(
        CORE_STEERING_GAIN * magnitude
        / (speed * max(1e-9, 1.0 - CORE_CURVE_SLOWDOWN * magnitude)),
        observation.error)
    return LaneObservation(error=error_for_curvature(curvature, confidence),
                           confidence=confidence)


class RouteHybridFollower:
    """See the module docstring. `update` has LaneBoundaryTracker's
    signature and returns a LaneObservation or None. `state` (also `tier`)
    is A's (BOTH / ONE / MEMORY / MANOEUVRE / STOP / MANOEUVRE_ABORT) or
    LOCALISE_STOP."""

    def __init__(self, graph, keys, *, start_pose, camera_x_offset_m: float,
                 paint_map: PaintMap | None = None, seed: int | None = None,
                 particles: int = 300) -> None:
        self._follower = RouteCameraFollower(graph, keys, start_pose=start_pose,
                                             camera_x_offset_m=camera_x_offset_m,
                                             map_frame=True)
        self._localizer = PaintLocalizer(
            _bundle_map() if paint_map is None else paint_map,
            camera_x_offset_m=camera_x_offset_m, particles=particles,
            seed=seed).initialise(start_pose)
        self._pieces = centreline_pieces(graph)
        self._compared = []     # over-threshold flags, last DISAGREE_WINDOW compared frames
        self.state = "STOP"
        self.last = {}

    @property
    def tier(self) -> str:
        return self.state

    @property
    def map_pose(self):
        """The last accepted estimate (start_pose before any)."""
        return self._follower.map_pose

    @property
    def view(self):
        return self._follower.view

    def update(self, now_s, pose, bgr, ground, **lane_kwargs) -> LaneObservation | None:
        estimate = self._localizer.update(now_s, pose, bgr, ground, **lane_kwargs)
        self.last = {"estimate": estimate,
                     "spread_m": None if estimate is None else estimate.spread_m,
                     "match": None if estimate is None else estimate.match,
                     "reason": None, "camera_confidence": None,
                     "tracker": self._follower.last.get("tracker", {})}
        if estimate is None:
            return self._stop("NO_ESTIMATE")
        if estimate.spread_m > MAX_SPREAD_M:
            return self._stop("SPREAD")
        if estimate.match < MIN_MATCH:
            return self._stop("MATCH")
        observation = self._follower.update(now_s, estimate.pose, bgr, ground, **lane_kwargs)
        self.state = self._follower.state
        self.last.update(self._follower.last)
        disagree = disagreement(self._follower._tracker, estimate.pose, self._pieces)
        if disagree is not None:
            self._compared = (self._compared + [disagree > MAX_DISAGREE_M])[-DISAGREE_WINDOW:]
        self.last["disagree_m"] = disagree
        if sum(self._compared) >= DISAGREE_MIN_FRAMES:
            return self._stop("DISAGREE")
        if observation is None:
            self.last["reason"] = self.state
            return None
        self.last["camera_confidence"] = observation.confidence
        return _with_confidence(observation,
                                confidence_for(estimate.match, estimate.spread_m))

    def _stop(self, reason: str) -> None:
        # A latched abort stays latched; otherwise the localiser owns the stop.
        self.state = ("MANOEUVRE_ABORT" if self._follower.state == "MANOEUVRE_ABORT"
                      else "LOCALISE_STOP")
        self.last["reason"] = reason
