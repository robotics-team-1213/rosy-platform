"""Prototype A: camera lane keeping with route-driven junction manoeuvres.

Spec 2026-09-22 lane-network junction spike §5, plan 2026-09-23 Task 3.
Lane keeping is LaneBoundaryTracker's (BOTH / ONE / MEMORY / STOP ladder).
The route (a LaneRoute over lane_graph segments) and the odometry pose do
three bounded things only:

  seed      before the first camera lock, or near a node, a boundary may be
            seeded from the route's predicted boundaries (the centreline
            offset a half-width either side) when no lane-width pair is in
            view: the one-line seed the baseline asked for (bends, ring arcs)
  select    near a node, a camera target (centre, or one side's iso-line)
            counts as supported only if it lies on the route's lane
            (AGREE_MAX_LATERAL_M). The ladder then falls through to the side
            that continues along the route: at a mouth that picks the branch,
            on the ring it keeps the island on the left (CCW)
  manoeuvre near a node, with a lock already held and no route-consistent
            camera target, pure pursuit on the route centreline at
            MEMORY_CONFIDENCE (tier 4, MANOEUVRE). It ends when the camera
            has a route-consistent BOTH/ONE target again and the heading is
            within REACQUIRE_HEADING_RAD of the route; past
            MANOEUVRE_MAX_TRAVEL_M, MANOEUVRE_TIMEOUT_S or
            MANOEUVRE_MAX_HEADING_RAD it aborts and stays stopped
            (MANOEUVRE_ABORT, fail-closed)

"Near a node" is within JUNCTION_ARM_M of either end of the current route
segment. Outside that, after the first lock, the tracker runs unmodified.
Direction on the ring comes from the route: LaneRoute refuses a one-way
segment walked backwards, so a clockwise ring route cannot be built.

The pose is odometry (the offline loop and Gazebo pass ground truth).
Position along the route is its projection; drift is not modelled here.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .lane import LaneObservation
from .lane_bev import (
    BEV_CELL_M,
    BEV_MAX_RANGE_M,
    BEV_X_MIN_M,
    BEV_Y_HALF_M,
    CORE_CRUISE_M_S,
    CORE_CURVE_SLOWDOWN,
    CORE_MIN_CONFIDENCE,
    LOOKAHEAD_M,
    LOOKAHEAD_MAX_M,
    MEMORY_CONFIDENCE,
    MEMORY_TRAVEL_M,
    MIN_BOUNDARY_LENGTH_M,
    _to_robot,
    error_for_curvature,
)
from .lane_boundaries import LaneBoundaryTracker
from .lane_route import DirectedSegment, LaneRoute

#: 260919 track lane half-width (lane_graph; lane_sim.H, lane_bev's
#: tightest path radius). Only the heading and travel bounds below use it;
#: boundary prediction uses the lane_half_width_m the caller passes.
TRACK_HALF_WIDTH_M = 0.0925
#: Route help (seed, select, manoeuvre) is armed within this of a node on
#: either side. Before the node: junction paint can enter the bird's-eye
#: view from BEV_MAX_RANGE_M (0.40 m) ahead. After it: the approach lane's
#: boundary memory, which still pulls the tracker, lives MEMORY_TRAVEL_M
#: (0.40 m). The larger of the two.
JUNCTION_ARM_M = max(BEV_MAX_RANGE_M, MEMORY_TRAVEL_M)
#: A paint component is a predicted boundary when SEED_MIN_FRACTION of its
#: cells lie within SEED_TOLERANCE_M of the prediction. lane_graph pins
#: every centreline point 60-100 mm from the nearest paint, so a boundary's
#: line centre sits within 92.5 +- 32.5 mm of the centreline; add half a
#: line width (12.5 mm) for the cells either side of it: 45 mm.
SEED_TOLERANCE_M = 0.045
#: Most of the component runs along the prediction; a line that only
#: crosses it (a spoke boundary meeting the ring) contributes a few cells.
SEED_MIN_FRACTION = 0.5
#: A camera target agrees with the route within this of its centreline:
#: the same 32.5 mm graph-to-paint slack plus 12.5 mm for the tracker's
#: centre band / iso-line quantisation; a quarter of the 185 mm lane, so
#: the other branch's lane centre fails it once the two have diverged.
AGREE_MAX_LATERAL_M = 0.045
#: Manoeuvre hands back to the camera when the heading is within this of
#: the route: a pursuit target inside the lane (|lateral| <= half-width) at
#: LOOKAHEAD_M bears at most atan(0.0925 / 0.15) = 31.7 deg.
REACQUIRE_HEADING_RAD = math.atan2(TRACK_HALF_WIDTH_M, LOOKAHEAD_M)
#: A manoeuvre bridges a mouth: the boundary gap across a spoke or ring
#: entry is one lane width (2 x 0.0925 m). Driving further on the route
#: alone means the camera never found the new lane. Offline the longest
#: manoeuvre was 0.095 m (scenario 05, west:f -> ring_w:f).
MANOEUVRE_MAX_TRAVEL_M = 2.0 * TRACK_HALF_WIDTH_M
#: Moving more than 90 deg off the route tangent is travelling against it
#: (junction_score's wrong_way test uses the same 90 deg).
MANOEUVRE_MAX_HEADING_RAD = math.pi / 2.0
_LOCK_TIERS = ("BOTH", "ONE")


def _manoeuvre_timeout_s() -> float:
    """MANOEUVRE_MAX_TRAVEL_M at the slowest speed CORE commands at
    MEMORY_CONFIDENCE on the tightest path (radius TRACK_HALF_WIDTH_M), as
    lane_bev's MEMORY_MAX_AGE_S: 0.185 m / 0.0242 m/s = 7.6 s. A manoeuvre
    that has not covered its travel by then is not moving as commanded."""
    error = error_for_curvature(1.0 / TRACK_HALF_WIDTH_M, MEMORY_CONFIDENCE)
    scale = (MEMORY_CONFIDENCE - CORE_MIN_CONFIDENCE) / (1.0 - CORE_MIN_CONFIDENCE)
    slowest = CORE_CRUISE_M_S * scale * max(0.2, 1.0 - CORE_CURVE_SLOWDOWN * abs(error))
    return MANOEUVRE_MAX_TRAVEL_M / slowest


MANOEUVRE_TIMEOUT_S = _manoeuvre_timeout_s()


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def _to_world(point_robot, pose) -> np.ndarray:
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([x + point_robot[0] * c - point_robot[1] * s,
                     y + point_robot[0] * s + point_robot[1] * c])


class _RouteGatedTracker(LaneBoundaryTracker):
    """LaneBoundaryTracker whose seed and target support consult `gate`
    (the follower) while it is set; with `gate` None it is unmodified."""

    def __init__(self, *, camera_x_offset_m: float = 0.0) -> None:
        super().__init__(camera_x_offset_m=camera_x_offset_m)
        self.gate = None

    def _seed(self, view, labels, stats, count, half):
        left, right = super()._seed(view, labels, stats, count, half)
        if left is not None or self.gate is None:
            return left, right
        picks = []
        for line in self.gate.predicted_boundaries(half):
            grid = np.zeros((view.rows, view.cols), np.uint8)
            rows = (line[:, 0] - BEV_X_MIN_M) / BEV_CELL_M
            cols = (BEV_Y_HALF_M - line[:, 1]) / BEV_CELL_M
            cv2.polylines(grid, [np.rint(np.stack([cols, rows], axis=1) * 16).astype(np.int32)],
                          False, 1, 1, shift=4)
            distance = cv2.distanceTransform((grid == 0).astype(np.uint8), cv2.DIST_L2,
                                             cv2.DIST_MASK_PRECISE) * BEV_CELL_M
            best = None
            for label in range(1, count):
                if label in picks or self._length(stats, label) < MIN_BOUNDARY_LENGTH_M:
                    continue
                near = distance[labels == label] <= SEED_TOLERANCE_M
                if near.mean() >= SEED_MIN_FRACTION and (best is None or near.sum() > best[0]):
                    best = (int(near.sum()), label)
            picks.append(None if best is None else best[1])
        self.last["route_seed"] = tuple(picks)
        return picks[0], picks[1]

    def _centre(self, view, left_grid, right_grid, half):
        target, supported = super()._centre(view, left_grid, right_grid, half)
        return target, supported and (self.gate is None or self.gate.agrees(target))

    def _lookahead(self, view, boundary_grid, half):
        target, supported = super()._lookahead(view, boundary_grid, half)
        return target, supported and (self.gate is None or self.gate.agrees(target))


class RouteCameraFollower:
    """Prototype A follower; see the module docstring. `update` has
    LaneBoundaryTracker's signature and returns a LaneObservation or None.
    `state` (also `tier`) is BOTH / ONE / MEMORY (camera), MANOEUVRE
    (route), STOP, or MANOEUVRE_ABORT (latched)."""

    def __init__(self, graph, keys, *, start_pose, camera_x_offset_m: float = 0.0) -> None:
        self.route = LaneRoute(graph, keys)
        segs = [DirectedSegment.from_graph(graph, key) for key in keys]
        self._points = np.vstack([segs[0].points] + [seg.points[1:] for seg in segs[1:]])
        self._arc = np.concatenate(
            [[0.0], np.cumsum(np.linalg.norm(np.diff(self._points, axis=0), axis=1))])
        self._seg_start = np.concatenate([[0.0], np.cumsum([seg.length_m for seg in segs])])
        start_pose = tuple(float(v) for v in start_pose)
        if len(start_pose) != 3 or not all(math.isfinite(v) for v in start_pose):
            raise ValueError("start_pose must be three finite numbers (x, y, yaw)")
        # The route projection is windowed around the previous fix; anchor
        # it at the known start so a closed into+out loop cannot snap to
        # its far end.
        self.route.locate(start_pose[:2])
        self._tracker = _RouteGatedTracker(camera_x_offset_m=camera_x_offset_m)
        self.state = "STOP"
        self.locked = False
        self._pose = start_pose
        self._s = 0.0
        self._manoeuvre = None
        self.last = {}

    @property
    def tier(self) -> str:
        return self.state

    def _window(self, ahead_m: float) -> np.ndarray:
        mask = (self._arc >= self._s - LOOKAHEAD_M) & (self._arc <= self._s + ahead_m)
        return self._points[mask]

    def predicted_boundaries(self, half: float):
        """Route centreline offset +-half ahead of the robot, robot frame:
        [left, right]."""
        points = self._window(BEV_MAX_RANGE_M + LOOKAHEAD_M)
        if len(points) < 2:
            return []
        tangent = np.gradient(points, axis=0)
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1)[:, None], 1e-9)
        normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
        return [_to_robot(points + half * normal, self._pose),
                _to_robot(points - half * normal, self._pose)]

    def agrees(self, target) -> bool:
        """A robot-frame target lies on the route's lane ahead."""
        points = self._window(LOOKAHEAD_MAX_M + LOOKAHEAD_M)
        if target is None or len(points) < 2:
            return False
        p = _to_world(target, self._pose)
        a, b = points[:-1], points[1:]
        ab = b - a
        t = np.clip(np.einsum("ij,ij->i", p - a, ab)
                    / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0.0, 1.0)
        gap = float(np.min(np.linalg.norm(p - (a + ab * t[:, None]), axis=1)))
        return gap <= AGREE_MAX_LATERAL_M

    def _route_observation(self) -> LaneObservation:
        x, y = _to_robot(np.array([self.route.point_ahead(self._pose[:2], LOOKAHEAD_M)]),
                         self._pose)[0]
        curvature = 2.0 * y / max(x * x + y * y, 1e-9)
        return LaneObservation(error=error_for_curvature(curvature, MEMORY_CONFIDENCE),
                               confidence=MEMORY_CONFIDENCE)

    def _abort(self):
        self._manoeuvre = "ABORTED"
        self.state = "MANOEUVRE_ABORT"

    def update(self, now_s, pose, bgr, ground, **kwargs) -> LaneObservation | None:
        if pose is not None:
            pose = tuple(float(v) for v in pose)
            if len(pose) != 3 or not all(math.isfinite(v) for v in pose):
                pose = None
        if pose is None or self._manoeuvre == "ABORTED":
            self._tracker.gate = None
            self._tracker.update(now_s, None, bgr, ground, **kwargs)
            if self._manoeuvre is not None:
                # Latched, or a manoeuvre that lost odometry cannot be measured.
                self._abort()
                return None
            self.state = "STOP"
            return None
        self._pose = pose
        fix = self.route.locate(pose[:2])
        self._s = float(self._seg_start[fix.segment_index] + fix.s_m)
        near_node = min(fix.distance_to_node_m, fix.s_m) <= JUNCTION_ARM_M
        self._tracker.gate = self if (near_node or not self.locked) else None
        observation = self._tracker.update(now_s, pose, bgr, ground, **kwargs)
        tier = self._tracker.tier
        if tier in _LOCK_TIERS:
            self.locked = True
        heading_error = abs(_wrap(pose[2] - fix.heading))
        self.last = {"fix": fix, "camera_tier": tier, "near_node": near_node,
                     "gated": self._tracker.gate is not None, "tracker": self._tracker.last}

        if self._manoeuvre is not None:
            m = self._manoeuvre
            m["travel"] += math.dist(pose[:2], m["xy"])
            m["xy"] = pose[:2]
            if (tier in _LOCK_TIERS and observation is not None
                    and heading_error <= REACQUIRE_HEADING_RAD):
                self._manoeuvre = None
            elif (m["travel"] > MANOEUVRE_MAX_TRAVEL_M
                  or not 0.0 <= now_s - m["t0"] <= MANOEUVRE_TIMEOUT_S
                  or heading_error > MANOEUVRE_MAX_HEADING_RAD):
                self._abort()
                return None
            else:
                self.state = "MANOEUVRE"
                return self._route_observation()
        if observation is not None:
            self.state = tier
            return observation
        if near_node and self.locked and heading_error <= MANOEUVRE_MAX_HEADING_RAD:
            self._manoeuvre = {"travel": 0.0, "xy": pose[:2], "t0": float(now_s)}
            self.state = "MANOEUVRE"
            return self._route_observation()
        self.state = "STOP"
        return None
