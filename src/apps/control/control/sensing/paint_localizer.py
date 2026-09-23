"""Subject: prototype B's pose, a particle filter over the checked-in paint map.

Spec 2026-09-22 lane-network junction spike §6 (B). ROS-free.

  map        the 260919 STL's floor paint (lane lines, roundabout, crosswalk
             bars: the camera sees the bars too) rasterised at PAINT_RASTER_M,
             and its distance field. The perimeter wall's bottom faces are
             floor-height triangles in the STL but a 155 mm wall stands on
             them in Gazebo, so they are left out (`_wall_footprint`).
  predict    each particle takes the odometry increment (in its own frame)
             plus noise proportional to it (MOTION_*)
  correct    the bird's-eye paint cells (lane_bev.BirdsEye, at most
             MATCH_SAMPLE_CELLS of them) are placed on the map from each
             particle; its score is exp(-mean distance / MATCH_SCALE_M),
             each distance capped at MATCH_TRUNCATE_M
  resample   systematic, when the effective particle count drops below half

Initialisation is from a known pose only (global initialisation is out of
scope). A frame with no ground plane or no odometry pose is a gap: no
output and no predict; the particles are kept, and the odometry increment
across the gap is applied on the next valid frame. A gap longer than
GAP_MAX_S, or one across which odometry moved more than GAP_MAX_TRAVEL_M,
drops the particles: there is no estimate again until `initialise`.

Each constant carries the measurement it was set from (offline loop:
test_paint_localizer, test_route_map). Paint matching is flat near the true
pose (a 25 mm line still covers most cells 10 mm off), so under a steady
sideways slip the estimate lags; once the slip stops it converges (see
test_it_converges_once_the_slip_stops).
"""

from __future__ import annotations

import importlib.util
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .lane import _BRIGHT
from .lane_bev import BirdsEye

#: Paint raster. The STL's paint edges are exact; 2 mm keeps a 25 mm line
#: 12 cells wide, finer than the 2.5 mm bird's-eye cell it is matched with.
PAINT_RASTER_M = 0.002

#: Initial spread about the given pose. The scenario start is a graph point
#: rounded to 0.1 mm and a Gazebo spawn is exact; 10 mm / 2 deg is what a
#: robot set down on its start mark can hold. The filter only recovers a
#: start error this size; it never searches for itself. (Offline 5 mm and
#: 20 mm pass too: end-position error 5.9 / 7.2 mm over the 12 scenarios.)
INIT_XY_SIGMA_M = 0.010
INIT_YAW_SIGMA_RAD = math.radians(2.0)

#: Odometry noise, proportional to the increment. The lateral-drift test
#: slips 2.5 mm sideways per 16 mm step (0.16 m/m) against odometry; the
#: particles must spread at least that fast to follow. End error of that
#: test over 8 seeds: 0.10 -> 21.7 mm worst (fails the 20 mm bound), 0.15
#: -> 20.0 mm worst, 0.20 -> 17.8 mm worst (14.5 mm at seed 7). 0.20 is
#: the smallest that passes on every seed. Yaw: 0.10 rad/rad is NOT
#: measured (no offline test slips yaw); it lets a 90 deg turn be 9 deg
#: off. A per-metre yaw term (10 deg/m) was tried and changed neither the
#: drift test nor any of the 12 scenarios, so there is none.
MOTION_XY_SIGMA_PER_M = 0.20
MOTION_YAW_SIGMA_PER_RAD = 0.10

#: Paint cells matched per frame. The start view has 4,212 paint cells;
#: 400 random ones keep one update at 6.8 ms median, 9.7 ms worst of 50
#: (300 particles, this Windows host; budget 30 ms).
MATCH_SAMPLE_CELLS = 400
#: Score scale. On the start view the mean capped distance is 1.33 mm at
#: the true pose, 2.35 mm 10 mm sideways, 7.7 mm 30 mm sideways, so a
#: 10 mm error costs a 0.82 weight ratio per frame at 5 mm. 3 mm follows
#: the drift test better (14.2 mm worst of 8 seeds) but a true-pose frame
#: in the scenarios then reads down to 0.15, leaving no room for MIN_MATCH
#: above a blank frame; 10 mm fails the drift test (21.2 mm worst).
MATCH_SCALE_M = 0.005
#: Distances beyond this count as this: paint that is not on the map (the
#: wall strip the offline renderer paints, glare, a shoe) then weighs every
#: particle alike instead of pulling the estimate towards it. Uncapped, a
#: still robot on the start view errs 4.3 mm / 0.84 deg (2.4 mm / 0.23 deg
#: at 30 mm); at 10 mm the drift test ends 19.5 mm off (worst of 8).
MATCH_TRUNCATE_M = 0.030

#: Particles resample when the effective count falls below this fraction.
RESAMPLE_FRACTION = 0.5

#: Longest gap (no pose or no ground plane) the particles survive. CORE
#: stops the robot 0.3 s (stale_after_s) after the last evidence and
#: latches LOST at 3.0 s (lost_after_s); a gap of five 5 Hz frames is
#: odometry or camera trouble, not a dropped message, and the pose the
#: particles hold is no longer worth resuming from.
GAP_MAX_S = 1.0
#: Largest odometry move across a gap that is still applied as one
#: increment: its MOTION_XY_SIGMA_PER_M spread is then 0.20 x 0.10 m =
#: 20 mm, route_map's MAX_SPREAD_M. Further, and the filter would only
#: resume to stop on its spread.
GAP_MAX_TRAVEL_M = 0.10


@dataclass(frozen=True)
class Estimate:
    """Filter output: weighted mean pose (x, y, yaw), the square root of the
    largest eigenvalue of the particle position covariance, and the
    posterior-weighted paint score (0..1; 0 with no paint in view)."""

    pose: tuple[float, float, float]
    spread_m: float
    match: float


def _load_stl_scene(bundle: Path):
    path = bundle / "scripts" / "stl_scene.py"
    spec = importlib.util.spec_from_file_location("stl_scene_for_paint_map", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_scene(next(bundle.glob("260919*.STL")))


def _wall_footprint(triangle, scene) -> bool:
    """True for a floor triangle lying wholly in the perimeter wall ring."""
    thickness = max(min(w.size_x, w.size_y) for w in scene.walls)
    hx, hy = scene.size_x / 2.0, scene.size_y / 2.0
    tol = 1e-6
    return all(abs(v[0]) >= hx - thickness - tol or abs(v[1]) >= hy - thickness - tol
               for v in triangle)


class PaintMap:
    """Distance (m) from a floor point to the nearest paint, ROS map frame."""

    def __init__(self, paint: np.ndarray, x0: float, y1: float,
                 raster_m: float = PAINT_RASTER_M) -> None:
        self.paint = paint.astype(bool)
        self.x0, self.y1, self.raster_m = float(x0), float(y1), float(raster_m)
        self.distance = (cv2.distanceTransform(
            (~self.paint).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
            * self.raster_m).astype(np.float32)

    @classmethod
    def from_scene(cls, scene) -> PaintMap:
        r = PAINT_RASTER_M
        x0, y1 = -scene.size_x / 2.0, scene.size_y / 2.0
        paint = np.zeros((math.ceil(scene.size_y / r) + 1,
                          math.ceil(scene.size_x / r) + 1), np.uint8)
        for triangle in scene.lines:
            if _wall_footprint(triangle, scene):
                continue
            pts = np.array([[(v[0] - x0) / r, (y1 - v[1]) / r] for v in triangle])
            cv2.fillPoly(paint, [np.rint(pts * 16).astype(np.int32)], 255, shift=4)
        return cls(paint > 0, x0, y1, r)

    @classmethod
    def from_bundle(cls, bundle_dir: str | Path | None = None) -> PaintMap:
        """The map_v2_fleet bundle: the source tree's by default, or an
        installed share/control/map/map_v2_fleet."""
        bundle = (Path(__file__).resolve().parents[2] / "map" / "map_v2_fleet"
                  if bundle_dir is None else Path(bundle_dir))
        return cls.from_scene(_load_stl_scene(bundle))

    def distance_at(self, points: np.ndarray) -> np.ndarray:
        """Distance for (..., 2) map points; +inf off the map."""
        return self.distance_at_cells((self.y1 - points[..., 1]) / self.raster_m,
                                      (points[..., 0] - self.x0) / self.raster_m)

    def distance_at_cells(self, row: np.ndarray, col: np.ndarray) -> np.ndarray:
        """Distance at fractional raster (row, col); +inf off the map."""
        rows, cols = self.distance.shape
        r = np.rint(row).astype(np.intp)
        c = np.rint(col).astype(np.intp)
        inside = (r >= 0) & (r < rows) & (c >= 0) & (c < cols)
        out = self.distance.take(r * cols + c, mode="clip")
        return np.where(inside, out, np.float32(np.inf))


def _wrap(angle):
    return np.arctan2(np.sin(angle), np.cos(angle))


class PaintLocalizer:
    """Particle filter; see the module docstring."""

    def __init__(self, paint_map: PaintMap, *, camera_x_offset_m: float,
                 particles: int = 300, seed: int | None = None) -> None:
        if isinstance(particles, bool) or not isinstance(particles, int) or particles < 1:
            raise ValueError("particles must be a positive integer")
        if (isinstance(camera_x_offset_m, bool)
                or not isinstance(camera_x_offset_m, (int, float))
                or not math.isfinite(camera_x_offset_m)):
            raise ValueError("camera_x_offset_m must be a finite number")
        self.map = paint_map
        self.count = particles
        self._camera_x = float(camera_x_offset_m)
        self._rng = np.random.default_rng(seed)
        self._view = None
        self._view_key = None
        self._particles = None      # (N, 3) x, y, yaw
        self._weights = None
        self._last_odom = None
        self._gap_since = None
        self.last: Estimate | None = None

    def initialise(self, pose) -> PaintLocalizer:
        x, y, yaw = (float(v) for v in pose)
        n = self.count
        self._particles = np.stack([
            x + self._rng.normal(0.0, INIT_XY_SIGMA_M, n),
            y + self._rng.normal(0.0, INIT_XY_SIGMA_M, n),
            yaw + self._rng.normal(0.0, INIT_YAW_SIGMA_RAD, n)], axis=1)
        self._weights = np.full(n, 1.0 / n)
        self._last_odom = None
        self._gap_since = None
        self.last = None
        return self

    def clear(self) -> None:
        self._particles = None
        self._weights = None
        self._last_odom = None
        self._gap_since = None
        self.last = None

    def _birds_eye(self, ground, shape) -> BirdsEye:
        key = (ground.height_m, ground.pitch_rad, ground.focal_px, ground.principal_x,
               ground.principal_y, ground.max_range_m, shape[0], shape[1], self._camera_x)
        if key != self._view_key:
            self._view = BirdsEye(ground, shape[1], shape[0], self._camera_x)
            self._view_key = key
        return self._view

    def update(self, now_s: float, odom_pose, bgr: np.ndarray, ground, *,
               bright_threshold: int = _BRIGHT, **_lane_kwargs) -> Estimate | None:
        """One frame. `odom_pose` is base_link in the odometry frame; only
        its increments are used. Other lane keyword arguments are accepted
        and ignored, so callers can pass the same set as to the trackers.
        No pose or no ground plane is a gap (see the module docstring)."""
        if odom_pose is not None:
            odom_pose = tuple(float(v) for v in odom_pose)
            if len(odom_pose) != 3 or not all(math.isfinite(v) for v in odom_pose):
                odom_pose = None
        if self._particles is None:
            return None
        now_s = float(now_s)
        if ground is None or odom_pose is None:
            if self._gap_since is None:
                self._gap_since = now_s
            elif not 0.0 <= now_s - self._gap_since <= GAP_MAX_S:
                self.clear()
            self.last = None
            return None
        if self._gap_since is not None:
            since, self._gap_since = self._gap_since, None
            last = self._last_odom
            if (not 0.0 <= now_s - since <= GAP_MAX_S
                    or (last is not None and math.hypot(odom_pose[0] - last[0],
                                                        odom_pose[1] - last[1])
                        > GAP_MAX_TRAVEL_M)):
                self.clear()
                return None
        if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
            raise ValueError("camera frame must be a non-empty grayscale or BGR array")

        self._predict(odom_pose)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        view = self._birds_eye(ground, gray.shape)
        paint = view.sample(gray > bright_threshold).astype(bool)
        cells = np.flatnonzero(paint)
        if len(cells) > MATCH_SAMPLE_CELLS:
            cells = self._rng.choice(cells, MATCH_SAMPLE_CELLS, replace=False)

        match = 0.0
        if len(cells):
            score = self._score(view.x.flat[cells], view.y.flat[cells])
            weights = self._weights * score
            total = weights.sum()
            if total > 0.0 and math.isfinite(total):
                self._weights = weights / total
                match = float(np.dot(self._weights, score))
            if 1.0 / float(np.sum(self._weights ** 2)) < RESAMPLE_FRACTION * self.count:
                self._resample()
        self.last = self._estimate(match)
        return self.last

    def _predict(self, odom) -> None:
        last, self._last_odom = self._last_odom, odom
        if last is None:
            return
        c, s = math.cos(last[2]), math.sin(last[2])
        wx, wy = odom[0] - last[0], odom[1] - last[1]
        dx, dy = c * wx + s * wy, -s * wx + c * wy
        dyaw = math.atan2(math.sin(odom[2] - last[2]), math.cos(odom[2] - last[2]))
        travel = math.hypot(dx, dy)
        if travel == 0.0 and dyaw == 0.0:
            return
        n = self.count
        sigma_xy = MOTION_XY_SIGMA_PER_M * travel
        sigma_yaw = MOTION_YAW_SIGMA_PER_RAD * abs(dyaw)
        ndx = dx + self._rng.normal(0.0, sigma_xy, n)
        ndy = dy + self._rng.normal(0.0, sigma_xy, n)
        p = self._particles
        pc, ps = np.cos(p[:, 2]), np.sin(p[:, 2])
        p[:, 0] += pc * ndx - ps * ndy
        p[:, 1] += ps * ndx + pc * ndy
        p[:, 2] = _wrap(p[:, 2] + dyaw + self._rng.normal(0.0, sigma_yaw, n))

    def _score(self, cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
        """exp(-mean capped distance / MATCH_SCALE_M) per particle, for
        robot-frame paint cells (cx, cy), worked in raster units."""
        m, p = self.map, self._particles
        inv = 1.0 / m.raster_m
        cx = (cx * inv).astype(np.float32)
        cy = (cy * inv).astype(np.float32)
        pc = np.cos(p[:, 2]).astype(np.float32)[:, None]
        ps = np.sin(p[:, 2]).astype(np.float32)[:, None]
        col = ((p[:, 0] - m.x0) * inv).astype(np.float32)[:, None] + (pc * cx - ps * cy)
        row = ((m.y1 - p[:, 1]) * inv).astype(np.float32)[:, None] - (ps * cx + pc * cy)
        distance = np.minimum(m.distance_at_cells(row, col), np.float32(MATCH_TRUNCATE_M))
        return np.exp(-distance.mean(axis=1, dtype=np.float64) / MATCH_SCALE_M)

    def _resample(self) -> None:
        n = self.count
        positions = (self._rng.random() + np.arange(n)) / n
        index = np.minimum(np.searchsorted(np.cumsum(self._weights), positions), n - 1)
        self._particles = self._particles[index].copy()
        self._weights = np.full(n, 1.0 / n)

    def _estimate(self, match: float) -> Estimate:
        p, w = self._particles, self._weights
        mean = w @ p[:, :2]
        yaw = math.atan2(float(w @ np.sin(p[:, 2])), float(w @ np.cos(p[:, 2])))
        centred = p[:, :2] - mean
        covariance = (centred * w[:, None]).T @ centred
        spread = math.sqrt(max(0.0, float(np.linalg.eigvalsh(covariance)[-1])))
        return Estimate(pose=(float(mean[0]), float(mean[1]), yaw), spread_m=spread,
                        match=match)
