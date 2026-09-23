"""Subject: prototype B's steering, the planned route pursued from the paint pose.

Spec 2026-09-22 lane-network junction spike §6 (B). ROS-free. Per frame:

  pose       PaintLocalizer over the checked-in paint map, started at the
             known start pose
  target     LaneRoute.point_ahead(estimate, LOOKAHEAD_M): the lane_graph
             centreline of the route (into, out, ...), so the branch is the
             route's, never the paint's
  pursuit    k = 2 y / r^2 to the target in base_link, mapped through CORE's
             line_follow law (lane_bev.error_for_curvature); CORE unchanged
  cross-check LaneBoundaryTracker runs on the same frame (odometry pose);
             where its centre line crosses the robot's station it must lie
             on the route as the estimate places it, within MAX_DISAGREE_M
             (DISAGREE_MIN_FRAMES in a row; not within JUNCTION_SKIP_M of
             a graph node)

Fail-closed (§6): no estimate, spread over MAX_SPREAD_M, match under
MIN_MATCH or a camera/route disagreement is no output, and CORE stops.
`state` is "ROUTE" while there is an output, else "STOP"; `last["reason"]`
names the stop condition.
"""

from __future__ import annotations

import functools
import math

import numpy as np

from .lane import LaneObservation
from .lane_bev import MEMORY_CONFIDENCE, error_for_curvature
from .lane_boundaries import LaneBoundaryTracker
from .lane_route import DirectedSegment, LaneRoute
from .paint_localizer import PaintLocalizer, PaintMap

#: Pure-pursuit lookahead along the route from the estimate's projection.
#: Offline max centre deviation over the 12 scenarios: 0.10 m -> 17 mm,
#: 0.12 -> 21 mm, 0.15 -> 31 mm, 0.20 -> 53 mm (3 fail). Offline odometry
#: is perfect; 0.12 keeps the curvature a pose error causes (2 dy / L^2)
#: 30 % below 0.10's for a small cost in corner cutting.
LOOKAHEAD_M = 0.12
#: Largest position spread (sqrt of the covariance's largest eigenvalue)
#: that may still steer: design §7's 20 mm end-position bound. Offline the
#: 12 scenarios peak at 12.4 mm; blind travel adds 3.2 mm in quadrature
#: per 16 mm step (MOTION_XY_SIGMA_PER_M), so MIN_MATCH trips first on
#: bare floor.
MAX_SPREAD_M = 0.02
#: Smallest paint match that may still steer. Offline the 12 scenarios
#: never read below 0.35 (01: the renderer's wall strip, left out of the
#: map, in view; 0.32 at other lookaheads); a frame with no paint reads 0, and a 30 mm pose error on
#: the start view reads ~0.21 (mean capped distance 7.7 mm).
MIN_MATCH = 0.25
#: Half a lane half-width (0.0925 m / 2): the camera's centre line and the
#: route disagree by more than this and one of them is wrong.
MAX_DISAGREE_M = 0.046
#: ... over this many compared frames in a row (a frame with nothing to
#: compare neither counts nor resets). Offline, with a 1-6 mm pose error,
#: the camera centre line and the graph centreline part by more than
#: MAX_DISAGREE_M outside junctions for single frames (00: 67 mm, 07: 53,
#: 11: 62, on spoke bends where the tracker's one-line iso-line is not the
#: graph's curve), 2 in a row at LOOKAHEAD_M 0.15-0.20; an 80 mm pose bias
#: holds every frame.
DISAGREE_MIN_FRAMES = 3
#: Within this of a graph node there is no comparison: lane_graph joins
#: the centrelines at the node point, while the camera centre line there is
#: the mouth's. Measured offline (12 scenarios, station comparison):
#: 90th percentile 68 mm and maximum off-scale under 0.10 m, maximum 145 mm
#: at 0.10-0.15 m, maximum 39 mm at 0.15-0.20 m.
JUNCTION_SKIP_M = 0.15
#: Half-length of the robot's station along base_link x: two BEV cells.
STATION_HALF_M = 0.005
#: Route vertices further than this from the compared point are not
#: searched (graph points are ~0.01 m apart; this is > 2 x MAX_DISAGREE_M).
ROUTE_SEARCH_M = 0.25
#: Confidence is CORE's speed scale: match / MATCH_FULL, times a spread
#: factor that is 1 up to half MAX_SPREAD_M and falls to 0 at it, floored
#: at lane_bev's MEMORY_CONFIDENCE (the speed lane following already drives
#: on remembered paint), which is above CORE's minimum. MATCH_FULL: a
#: clean lane view at the true pose reads 0.66-0.85 offline.
MATCH_FULL = 0.6
CONFIDENCE_FLOOR = MEMORY_CONFIDENCE


@functools.lru_cache(maxsize=1)
def _bundle_map() -> PaintMap:
    return PaintMap.from_bundle()


class RouteMapFollower:
    """Planned-route pursuit from the paint-localised pose; see the module
    docstring."""

    def __init__(self, graph, keys, *, start_pose, camera_x_offset_m: float,
                 seed: int | None = None, paint_map: PaintMap | None = None,
                 particles: int = 300) -> None:
        self._route = LaneRoute(graph, keys)
        self._polyline = np.vstack([DirectedSegment.from_graph(graph, k).points for k in keys])
        self._localizer = PaintLocalizer(
            _bundle_map() if paint_map is None else paint_map,
            camera_x_offset_m=camera_x_offset_m, particles=particles,
            seed=seed).initialise(start_pose)
        self._camera = LaneBoundaryTracker(camera_x_offset_m=camera_x_offset_m)
        self._nodes = np.array(list(graph["nodes"].values()), float)
        self._disagree_run = 0
        self._offset_m = 0.0
        self._state = "STOP"
        self.last = {}

    @property
    def state(self) -> str:
        return self._state

    def force_pose_offset(self, metres: float) -> None:
        """TEST-ONLY hook: shift every later estimate `metres` to its left
        (negative: right) before it steers, to exercise the camera/route
        disagreement stop. Never call this outside tests."""
        self._offset_m = float(metres)

    def update(self, now_s, pose, bgr, ground, **lane_kwargs) -> LaneObservation | None:
        self._state = "STOP"
        estimate = self._localizer.update(now_s, pose, bgr, ground, **lane_kwargs)
        camera = self._camera.update(now_s, pose, bgr, ground, **lane_kwargs)
        self.last = {"estimate": estimate, "camera": camera, "reason": None}
        if estimate is None:
            return self._stop("NO_ESTIMATE")
        if estimate.spread_m > MAX_SPREAD_M:
            return self._stop("SPREAD")
        if estimate.match < MIN_MATCH:
            return self._stop("MATCH")
        x, y, yaw = estimate.pose
        if self._offset_m:
            x -= self._offset_m * math.sin(yaw)
            y += self._offset_m * math.cos(yaw)
        steer_pose = (x, y, yaw)
        self.last["steer_pose"] = steer_pose

        disagree = None
        if np.min(np.hypot(*(self._nodes - (x, y)).T)) > JUNCTION_SKIP_M:
            disagree = self._disagreement(steer_pose)
        if disagree is not None:
            self._disagree_run = self._disagree_run + 1 if disagree > MAX_DISAGREE_M else 0
        self.last["disagree_m"] = disagree
        if self._disagree_run >= DISAGREE_MIN_FRAMES:
            return self._stop("DISAGREE")

        tx, ty = self._route.point_ahead((x, y), LOOKAHEAD_M)
        c, s = math.cos(yaw), math.sin(yaw)
        dx, dy = tx - x, ty - y
        ahead, left = c * dx + s * dy, -s * dx + c * dy
        range2 = ahead * ahead + left * left
        if range2 <= 1e-9:
            return self._stop("END")
        self.last["target"] = (ahead, left)
        quality = (min(1.0, estimate.match / MATCH_FULL)
                   * min(1.0, 2.0 * (1.0 - estimate.spread_m / MAX_SPREAD_M)))
        confidence = max(CONFIDENCE_FLOOR, quality)
        self._state = "ROUTE"
        return LaneObservation(error=error_for_curvature(2.0 * left / range2, confidence),
                               confidence=confidence)

    def _stop(self, reason: str) -> None:
        self._state = "STOP"
        self.last["reason"] = reason

    def _disagreement(self, steer_pose):
        """Lateral disagreement (m) at the robot: where the camera's centre
        line crosses the robot's own station (base_link x within
        STATION_HALF_M of 0), its distance to the route placed by
        `steer_pose`. None when the camera has no fresh centre line (BOTH or
        ONE tier) or it does not reach the robot's station.

        Only the robot's station is compared. Ahead of it the camera's band
        may end or follow the branch the route does not take; its nearest
        point is then that end, on the other branch or across the mouth
        (measured with a 2-8 mm pose error: 06 read 53 mm, 07 57 mm, 04
        51 mm, all at a junction mouth with the band starting ahead)."""
        if self._camera.tier not in ("BOTH", "ONE"):
            return None
        path = self._camera.last.get("path")
        view = self._camera._view
        if path is None or view is None:
            return None
        station = path & (np.abs(view.x) <= STATION_HALF_M)
        if not station.any():
            return None
        px, py = view.x[station], view.y[station]
        k = int(np.argmin(np.abs(py)))
        x, y, yaw = steer_pose
        c, s = math.cos(yaw), math.sin(yaw)
        point = np.array([[x + c * px[k] - s * py[k], y + s * px[k] + c * py[k]]])
        return float(self._distance_to_route(point)[0])

    def _distance_to_route(self, points: np.ndarray) -> np.ndarray:
        """Distance from each (n, 2) point to the route polyline pieces
        within ROUTE_SEARCH_M of their mean."""
        a, b = self._polyline[:-1], self._polyline[1:]
        centre = points.mean(axis=0)
        keep = np.hypot(*(a - centre).T) <= ROUTE_SEARCH_M
        if not keep.any():
            return np.full(len(points), np.inf)
        a, b = a[keep], b[keep]
        ab = b - a
        ab2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12)
        ap = points[:, None, :] - a[None, :, :]
        t = np.clip(np.einsum("nij,ij->ni", ap, ab) / ab2, 0.0, 1.0)
        nearest = a[None] + t[..., None] * ab[None]
        return np.min(np.hypot(*(points[:, None, :] - nearest).transpose(2, 0, 1)), axis=1)
