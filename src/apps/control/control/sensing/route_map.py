"""Subject: prototype B's steering, the planned route pursued from the paint pose.

Spec 2026-09-22 lane-network junction spike §6 (B). ROS-free. Per frame:

  pose       PaintLocalizer over the checked-in paint map, started at the
             known start pose
  target     LaneRoute.point_ahead(estimate, LOOKAHEAD_M): the lane_graph
             centreline of the route (into, out, ...), so the branch is the
             route's, never the paint's
  pursuit    k = 2 y / r^2 to the target in base_link, mapped through CORE's
             line_follow law (lane_bev.error_for_curvature); CORE unchanged
  cross-check a LaneBoundaryTracker runs on the same frame (odometry pose;
             seeded, like prototype A's, from the route's predicted
             boundaries at the estimate when no lane-width pair is in view).
             Its fresh path, placed on the map by the estimate, must lie on
             a lane_graph centreline: DISAGREE when DISAGREE_MIN_FRAMES of
             the last DISAGREE_WINDOW compared frames are more than
             MAX_DISAGREE_M off (`_disagreement`). `last["coverage"]` is the
             fraction of frames compared so far.

Fail-closed (§6): no estimate, spread over MAX_SPREAD_M, match under
MIN_MATCH, a camera/route disagreement, or a pursuit target that is the
route's end within LOOKAHEAD_M / 2 or behind the robot is no output, and
CORE stops.
`state` is "ROUTE" while there is an output, else "STOP"; `last["reason"]`
names the stop condition.
"""

from __future__ import annotations

import functools
import math

import numpy as np

from .lane import LaneObservation
from .lane_bev import BEV_MAX_RANGE_M, _to_robot, error_for_curvature
from .lane_bev import LOOKAHEAD_M as CAMERA_LOOKAHEAD_M
from .lane_route import DirectedSegment, LaneRoute
from .paint_localizer import PaintLocalizer, PaintMap
from .route_camera import _RouteGatedTracker

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
#: Smallest paint match that may still steer. `match` is posterior-weighted
#: (PaintLocalizer's Estimate: the particle weights times their scores),
#: not the score at the mean pose, so a spread-out or bimodal cloud reads
#: lower than its best particle. Offline the 12 scenarios
#: never read below 0.35 (01: the renderer's wall strip, left out of the
#: map, in view; 0.32 at other lookaheads); a frame with no paint reads 0, and a 30 mm pose error on
#: the start view reads ~0.21 (mean capped distance 7.7 mm).
MIN_MATCH = 0.25
#: Camera/route disagreement: the fresh camera path (the tracker's centre
#: band, or its one-line iso-line) is placed on the map from the steering
#: pose; per compared frame the statistic is the median distance of its
#: cells to the nearest lane centreline (`_disagreement`). Offline, 12
#: clean scenarios (seed 7, 447 compared frames of 555): median 1.8-3.9 mm
#: per scenario, largest 8.1 mm apart from two single-frame spikes (00:
#: 39.5, 11: 39.9 mm, a band cut by a mouth). A 50 mm pose bias (either
#: side) reads a per-scenario median of 30-45 mm. The threshold is half
#: that bias; it also stays above B's end-estimate error on the moderate
#: drift grid (worst 7.6 mm, test_drift_grid).
MAX_DISAGREE_M = 0.025
#: DISAGREE when at least DISAGREE_MIN_FRAMES of the last DISAGREE_WINDOW
#: compared frames exceed MAX_DISAGREE_M (a frame with nothing to compare
#: neither counts nor is kept): the single-frame spikes above never trip
#: it; every 50 mm bias run has 4 of 4 over.
DISAGREE_WINDOW = 4
DISAGREE_MIN_FRAMES = 2
#: Only path cells within this of a centreline are compared: the lane
#: half-width. A band cell further out is between lanes (a mouth's open
#: side, a crosswalk bar's iso-line); a pose bias up to the half-width
#: stays inside and is measured.
CORRIDOR_M = 0.0925
#: A frame is compared only when the kept cells span this much along x
#: (base_link): shorter pieces are a band's stub, not a lane.
COMPARE_MIN_LENGTH_M = 0.03
#: At most this many path cells, evenly spaced, are compared per frame.
COMPARE_MAX_CELLS = 150
#: Lane centrelines compared with: every lane_graph segment piece within
#: this of the steering pose (the bird's-eye view reaches 0.40 m past
#: base_link). Not only the route's: past a node B's own camera tracker,
#: which does not know the route, may keep to the branch the route leaves
#: (measured offline with this check restricted to the route: the band
#: drifts 12 -> 44 mm off the route over 0.08 m while the robot drives the
#: route correctly, 00, 05, 09). A lane the camera follows is on SOME
#: centreline, including both into and out at a node; a pose error moves
#: it off all of them (the nearest other centreline is a lane width away).
CENTRELINE_RADIUS_M = 0.60
#: Confidence is CORE's speed scale. The estimate's quality, a match
#: factor (0 at MIN_MATCH rising linearly to 1 at MATCH_FULL) times a
#: spread factor (1 up to half MAX_SPREAD_M, falling linearly to 0 at it),
#: maps linearly onto [CONFIDENCE_MIN, 1]. MATCH_FULL: a clean lane view at
#: the true pose reads 0.66-0.85 offline. CONFIDENCE_MIN sits above CORE's
#: 0.35 minimum (speed scale 0.08: ~6 mm/s at cruise 0.08 m/s), so a
#: barely-accepted estimate creeps where the old floor at MEMORY_CONFIDENCE
#: (scale 0.38) drove as fast as remembered paint.
MATCH_FULL = 0.6
CONFIDENCE_MIN = 0.4


def confidence_for(match: float, spread_m: float) -> float:
    """CORE confidence for an accepted estimate; see CONFIDENCE_MIN."""
    match_q = min(1.0, max(0.0, (match - MIN_MATCH) / (MATCH_FULL - MIN_MATCH)))
    spread_q = min(1.0, max(0.0, 2.0 * (1.0 - spread_m / MAX_SPREAD_M)))
    return CONFIDENCE_MIN + (1.0 - CONFIDENCE_MIN) * match_q * spread_q


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
        # The route projection is windowed around the previous fix; anchor
        # it at the known start (as prototype A does).
        self._route.locate(tuple(float(v) for v in start_pose)[:2])
        segs = [DirectedSegment.from_graph(graph, key) for key in keys]
        self._points = np.vstack([segs[0].points] + [seg.points[1:] for seg in segs[1:]])
        self._arc = np.concatenate(
            [[0.0], np.cumsum(np.linalg.norm(np.diff(self._points, axis=0), axis=1))])
        self._seg_start_s = np.concatenate([[0.0], np.cumsum([seg.length_m for seg in segs])])
        pieces = [np.asarray(seg["points"], float) for seg in graph["segments"].values()]
        self._piece_a = np.vstack([p[:-1] for p in pieces])
        self._piece_b = np.vstack([p[1:] for p in pieces])
        self._localizer = PaintLocalizer(
            _bundle_map() if paint_map is None else paint_map,
            camera_x_offset_m=camera_x_offset_m, particles=particles,
            seed=seed).initialise(start_pose)
        self._camera = _RouteGatedTracker(camera_x_offset_m=camera_x_offset_m)
        self._seed_pose = None
        self._compared = []          # over-threshold flags, last DISAGREE_WINDOW compared frames
        self._frames = 0
        self._compared_frames = 0
        self._state = "STOP"
        self.last = {}

    @property
    def state(self) -> str:
        return self._state

    def _steer_pose(self, estimate):
        """The pose that steers and is cross-checked (tests bias it)."""
        return estimate.pose

    # Seed gate for the camera tracker (see _RouteGatedTracker): predicted
    # boundaries from the estimate; targets are never vetoed, since the
    # camera must stay an independent check on that estimate.
    def predicted_boundaries(self, half: float):
        """Route centreline +-half near the estimate, robot frame: [left, right]."""
        pose = self._seed_pose
        s = self._route_s(pose[:2])
        mask = ((self._arc >= s - CAMERA_LOOKAHEAD_M)
                & (self._arc <= s + BEV_MAX_RANGE_M + CAMERA_LOOKAHEAD_M))
        points = self._points[mask]
        if len(points) < 2:
            return []
        tangent = np.gradient(points, axis=0)
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1)[:, None], 1e-9)
        normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
        return [_to_robot(points + half * normal, pose), _to_robot(points - half * normal, pose)]

    @staticmethod
    def agrees(_target) -> bool:
        return True

    def _route_s(self, xy) -> float:
        """Arc length of `xy`'s projection (LaneRoute's windowed search)."""
        fix = self._route.locate(xy)
        return float(self._seg_start_s[fix.segment_index] + fix.s_m)

    def update(self, now_s, pose, bgr, ground, **lane_kwargs) -> LaneObservation | None:
        self._state = "STOP"
        estimate = self._localizer.update(now_s, pose, bgr, ground, **lane_kwargs)
        self._seed_pose = None if estimate is None else self._steer_pose(estimate)
        self._camera.gate = None if self._seed_pose is None else self
        camera = self._camera.update(now_s, pose, bgr, ground, **lane_kwargs)
        self._frames += 1
        self.last = {"estimate": estimate, "camera": camera, "reason": None,
                     "coverage": self._compared_frames / self._frames}
        if estimate is None:
            return self._stop("NO_ESTIMATE")
        if estimate.spread_m > MAX_SPREAD_M:
            return self._stop("SPREAD")
        if estimate.match < MIN_MATCH:
            return self._stop("MATCH")
        steer_pose = self._seed_pose
        x, y, yaw = steer_pose
        self.last["steer_pose"] = steer_pose

        disagree = self._disagreement(steer_pose)
        if disagree is not None:
            self._compared_frames += 1
            self._compared = (self._compared + [disagree > MAX_DISAGREE_M])[-DISAGREE_WINDOW:]
        self.last["disagree_m"] = disagree
        self.last["coverage"] = self._compared_frames / self._frames
        if sum(self._compared) >= DISAGREE_MIN_FRAMES:
            return self._stop("DISAGREE")

        tx, ty = self._route.point_ahead((x, y), LOOKAHEAD_M)
        c, s = math.cos(yaw), math.sin(yaw)
        dx, dy = tx - x, ty - y
        ahead, left = c * dx + s * dy, -s * dx + c * dy
        range2 = ahead * ahead + left * left
        at_end = self._route_s((x, y)) + LOOKAHEAD_M >= self._arc[-1]
        if range2 <= 1e-9 or (at_end and (ahead <= 0.0 or range2 < (LOOKAHEAD_M / 2.0) ** 2)):
            # The target is the route's end, within half the lookahead or
            # behind the robot. (Mid-route a target beside the robot is a
            # tight turn, not an end.)
            return self._stop("END")
        self.last["target"] = (ahead, left)
        confidence = confidence_for(estimate.match, estimate.spread_m)
        self._state = "ROUTE"
        return LaneObservation(error=error_for_curvature(2.0 * left / range2, confidence),
                               confidence=confidence)

    def _stop(self, reason: str) -> None:
        self._state = "STOP"
        self.last["reason"] = reason

    def _disagreement(self, steer_pose):
        """Median distance (m) from the fresh camera path to the nearest
        lane centreline, both placed by `steer_pose`; None when there is
        nothing to compare.

        The path is the tracker's pursued band (centre band for BOTH, a
        one-line iso-line for ONE) restricted to cells the camera observes
        this frame, so boundary memory never enters. Cells further than
        CORRIDOR_M from every centreline are dropped; what is left must span
        COMPARE_MIN_LENGTH_M. Junctions are not skipped: there the nearest
        centreline is into's or out's (or another branch's), whichever lane
        the band is in."""
        if self._camera.tier not in ("BOTH", "ONE"):
            return None
        path = self._camera.last.get("path")
        view = self._camera._view
        if path is None or view is None:
            return None
        cells = np.flatnonzero(path & view.observable)
        if len(cells) == 0:
            return None
        if len(cells) > COMPARE_MAX_CELLS:
            cells = cells[np.linspace(0, len(cells) - 1, COMPARE_MAX_CELLS).astype(int)]
        px, py = view.x.flat[cells], view.y.flat[cells]
        x, y, yaw = steer_pose
        c, s = math.cos(yaw), math.sin(yaw)
        points = np.stack([x + c * px - s * py, y + s * px + c * py], axis=1)
        distance = self._distance_to_centrelines(points, (x, y))
        inside = distance <= CORRIDOR_M
        if not inside.any() or np.ptp(px[inside]) < COMPARE_MIN_LENGTH_M:
            return None
        return float(np.median(distance[inside]))

    def _distance_to_centrelines(self, points: np.ndarray, xy) -> np.ndarray:
        """Distance from each (n, 2) point to the lane_graph centreline
        pieces within CENTRELINE_RADIUS_M of `xy`."""
        a, b = self._piece_a, self._piece_b
        keep = np.hypot(*(a - xy).T) <= CENTRELINE_RADIUS_M
        if not keep.any():
            return np.full(len(points), np.inf)
        a, b = a[keep], b[keep]
        ab = b - a
        ab2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12)
        ap = points[:, None, :] - a[None, :, :]
        t = np.clip(np.einsum("nij,ij->ni", ap, ab) / ab2, 0.0, 1.0)
        nearest = a[None] + t[..., None] * ab[None]
        return np.min(np.hypot(*(points[:, None, :] - nearest).transpose(2, 0, 1)), axis=1)
