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
             the camera tracker still owns lane keeping, its boundary memory
             carried by odometry (smooth frame to frame; the estimate steps
             on resampling: see test_the_camera_tracker_keeps_its_boundary_
             memory_on_odometry for the measurement)
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

  ring entry within JUNCTION_ARM_M either side of a node where the route
             leaves a road for the roundabout (`ring_entries`), A still
             decides WHETHER to drive (its gate, manoeuvre bounds, STOP) but
             the route decides WHERE: its output is replaced by B's pure
             pursuit, the route point ENTRY_LOOKAHEAD_M ahead of the
             estimate, at A's confidence (`last["steer"]` "route"; elsewhere
             "camera", or "manoeuvre" for A's own route pursuit). See below.

Why the ring entry is route-steered (diagnosis 2026-09-23, offline 00 and
11, the two Gazebo failures): through the entry A's camera target lies ON
the route centreline (median 2-3 mm off it; the ONE iso-line of the island
or of the outer arc is the ring centreline), so neither the pose nor A's
45 mm agreement gate is the cause. The widening is pure-pursuit geometry:
the robot reaches the 106-115 deg corner still heading into the island,
and a pursuit arc to a point on the ring LOOKAHEAD ahead dips inside the
ring deeper the longer the lookahead. A pursues at the camera's 0.15 m, B
at 0.12 m: the route pursued at 0.15 m (camera-free) already reads
28.4 / 27.3 mm, at 0.12 m 21.6 / 21.2 mm; A's camera adds the rest
(37.5 / 37.3 mm), in 00 mostly three frames just before the node where
the spoke's left line bends into the island paint and its iso-line (17-40
mm off the route, inside the 45 mm gate) steers left before a right turn.
Tightening the gate alone was measured and is not enough: 30 mm -> 30.3 /
36.3 mm, 20 mm -> 32.7 / 36.0 mm. Ring exits (01, 04, 07, 10) and ring to
ring stay camera-steered: route pursuit there measured 10.7 mm on 01
against the camera's 3.8 (B's Gazebo failure is that exit).

The cross-check is kept because A's route gate alone does not catch a
biased estimate: offline, with the estimate shifted +-30 / +-50 mm, 6 of 48
runs drove to the end on the right branch 43-63 mm off the centreline
without stopping; with the check 47 stop and 1 passes, none unstopped
(test_a_biased_estimate_is_not_driven_off_the_lane).
"""

from __future__ import annotations

import math

import numpy as np

from .lane import LaneObservation
from .lane_bev import (
    CORE_CRUISE_M_S,
    CORE_CURVE_SLOWDOWN,
    CORE_MIN_CONFIDENCE,
    CORE_STEERING_GAIN,
    error_for_curvature,
)
from .paint_localizer import PaintLocalizer, PaintMap
from .route_camera import JUNCTION_ARM_M, TRACK_HALF_WIDTH_M, RouteCameraFollower
from .route_map import (
    DISAGREE_MIN_FRAMES,
    DISAGREE_WINDOW,
    LOOKAHEAD_M,
    MAX_DISAGREE_M,
    MAX_SPREAD_M,
    MIN_MATCH,
    _bundle_map,
    centreline_pieces,
    confidence_for,
    disagreement,
)

#: Ring-entry pursuit lookahead: B's (route_map.LOOKAHEAD_M, its offline
#: sweep 0.10 -> 17 mm, 0.12 -> 21 mm, 0.15 -> 31 mm), measured on the
#: hybrid's entries 00 / 11: 37.5 / 37.3 mm (camera) -> 22.1 / 21.3 mm.
ENTRY_LOOKAHEAD_M = LOOKAHEAD_M
#: A segment is on the roundabout when every centreline point lies within
#: this of the lane_graph `roundabout` circle: half a lane, the ring lane
#: itself (lane_graph's ring points sit within 1 mm of the radius; a road
#: leaves the circle by more than a lane width away from its node).
RING_TOLERANCE_M = TRACK_HALF_WIDTH_M


def ring_entries(graph, keys) -> list:
    """Per route node (between keys[i] and keys[i + 1]): True where the
    route leaves a road for a roundabout segment. A graph without a
    `roundabout` has none."""
    ring = graph.get("roundabout")
    if not ring:
        return [False] * (len(keys) - 1)
    centre, radius = np.asarray(ring["centre"], float), float(ring["radius"])

    def on_ring(key):
        points = np.asarray(graph["segments"][key.split(":")[0]]["points"], float)
        return bool(np.all(np.abs(np.hypot(*(points - centre).T) - radius)
                           <= RING_TOLERANCE_M))

    flags = [on_ring(key) for key in keys]
    return [not a and b for a, b in zip(flags, flags[1:])]


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
        self._entries = ring_entries(graph, keys)
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
        observation = self._follower.update(now_s, estimate.pose, bgr, ground,
                                            odom_pose=pose, **lane_kwargs)
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
        observation = self._steer(observation, estimate.pose)
        return _with_confidence(observation,
                                confidence_for(estimate.match, estimate.spread_m))

    def _in_ring_entry(self) -> bool:
        """Within JUNCTION_ARM_M before or after a road-to-ring node."""
        fix = self._follower.last.get("fix")
        if fix is None:
            return False
        i = fix.segment_index
        return ((i < len(self._entries) and self._entries[i]
                 and fix.distance_to_node_m <= JUNCTION_ARM_M)
                or (i > 0 and self._entries[i - 1] and fix.s_m <= JUNCTION_ARM_M))

    def _steer(self, observation: LaneObservation, pose) -> LaneObservation:
        """A's output, or in a ring entry B's route pursuit at A's
        confidence (see the module docstring). Where the pursuit target is
        the route's end, within half the lookahead or behind the robot
        (route_map's END), A's output is kept."""
        self.last["steer"] = "manoeuvre" if self.state == "MANOEUVRE" else "camera"
        if not self._in_ring_entry():
            return observation
        x, y, yaw = pose
        route = self._follower.route
        tx, ty = route.point_ahead((x, y), ENTRY_LOOKAHEAD_M)
        c, s = math.cos(yaw), math.sin(yaw)
        ahead, left = c * (tx - x) + s * (ty - y), -s * (tx - x) + c * (ty - y)
        range2 = ahead * ahead + left * left
        fix = self._follower.last["fix"]
        at_end = (fix.segment_index == len(route.segments) - 1
                  and fix.distance_to_node_m <= ENTRY_LOOKAHEAD_M)
        if range2 <= 1e-9 or (at_end and (ahead <= 0.0
                                          or range2 < (ENTRY_LOOKAHEAD_M / 2.0) ** 2)):
            return observation
        self.last["steer"] = "route"
        self.last["route_target"] = (ahead, left)
        return LaneObservation(
            error=error_for_curvature(2.0 * left / range2, observation.confidence),
            confidence=observation.confidence)

    def _stop(self, reason: str) -> None:
        # A latched abort stays latched; otherwise the localiser owns the stop.
        self.state = ("MANOEUVRE_ABORT" if self._follower.state == "MANOEUVRE_ABORT"
                      else "LOCALISE_STOP")
        self.last["reason"] = reason
