"""Subject: saved-map observation agreement and expiring localization authority."""
from dataclasses import dataclass
import math
from typing import Optional

import numpy as np
#: Refinement around one global seed: +-5 cm in 1 cm steps, +-5 deg in 1 deg steps.
GLOBAL_OFFSETS = np.array(np.meshgrid(
    np.arange(-.05, .051, .01), np.arange(-.05, .051, .01), np.radians(np.arange(-5., 5.1, 1.)),
    indexing='ij')).reshape(3, -1).T
#: Two poses closer than this in both position and heading are one hypothesis.
SEPARATION_M = .18
SEPARATION_RAD = .3


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def apart(a, b):
    """True when two (x, y, yaw) poses are distinct hypotheses, not one blurred twice."""
    return math.dist(a[:2], b[:2]) > SEPARATION_M or abs(wrap(a[2]-b[2])) > SEPARATION_RAD


def valid_beams(ranges, angles):
    """Finite beams beyond the 5 cm lidar minimum, as arrays."""
    ranges, angles = np.asarray(ranges, dtype=float), np.asarray(angles, dtype=float)
    valid = np.isfinite(ranges) & (ranges > .05) & np.isfinite(angles)
    return ranges[valid], angles[valid]


@dataclass(frozen=True)
class AgreementBreakdown:
    """Per-beam diagnostic breakdown and occlusion-robust score for one sensor pose."""

    total: int
    hit: int
    miss_wall_pierced: int
    miss_foreground: int
    miss_unknown: int
    raw_score: float
    robust_score: float
    sectors_hit: int
    sector_mask: int
    fg_cluster_count: int
    rejected_reason: Optional[str]


def _count_foreground_clusters(ranges, angles, short_free, min_cluster_beams: int) -> tuple[int, int]:
    """Count short free-space stops forming contiguous angular foreground clusters."""
    n = len(ranges)
    if not n or not np.any(short_free):
        return 0, 0
    wrapped = ((angles + math.pi) % (2. * math.pi)) - math.pi
    order = np.argsort(wrapped, kind='mergesort')
    runs = []
    current = []
    for pos, idx in enumerate(order):
        if not short_free[idx]:
            if current:
                runs.append(current)
                current = []
            continue
        if not current:
            current = [idx]
            continue
        prev = current[-1]
        d_ang = abs(float(wrapped[idx] - wrapped[prev]))
        d_rng = abs(float(ranges[idx] - ranges[prev]))
        if d_ang <= 0.12 and d_rng <= 0.35:
            current.append(idx)
        else:
            runs.append(current)
            current = [idx]
    if current:
        runs.append(current)
    if (len(runs) >= 2 and runs[0][0] == order[0] and runs[-1][-1] == order[-1]
            and abs((float(wrapped[order[0]]) + 2. * math.pi) - float(wrapped[order[-1]])) <= 0.12
            and abs(float(ranges[order[0]]) - float(ranges[order[-1]])) <= 0.35):
        runs[0] = runs[-1] + runs[0]
        runs.pop()
    big = [len(run) for run in runs if len(run) >= min_cluster_beams]
    return int(sum(big)), int(len(big))


def planar_yaw(x, y, z, w):
    values = (x, y, z, w)
    if (not all(math.isfinite(v) for v in values) or
            abs(sum(v*v for v in values)-1.) > .01 or
            1.-2.*(x*x+y*y) < math.cos(math.radians(5))):
        raise ValueError('Localization requires a finite unit planar rotation')
    return math.atan2(2.*(w*z+x*y), 1.-2.*(y*y+z*z))


def lease_ready(status, now, timeout=.5):
    if not isinstance(status, dict) or status.get('ready') is not True:
        return False
    stamp = status.get('stamp_ns')
    if not isinstance(stamp, int) or isinstance(stamp, bool) or stamp <= 0:
        return False
    age = now - stamp * 1e-9
    return math.isfinite(age) and 0. <= age <= timeout


class Confidence:
    def __init__(self, stable_scans=10):
        self.required = max(1, stable_scans)
        self.count = 0
        self.last_stamp = -math.inf

    def observe(self, stamp, good):
        if not good or stamp < self.last_stamp:
            self.count = 0
        elif stamp > self.last_stamp:
            self.count += 1
        self.last_stamp = stamp
        return good and self.count >= self.required


class MapAgreement:
    def __init__(self, grid, resolution, origin, tolerance=.04):
        self.grid = np.asarray(grid)
        self.resolution = resolution
        self.origin = np.asarray(origin)
        # The occupied surface is uncertain by one grid cell. Unknown is never
        # a wall observation; matching unknown cells cannot authorize motion.
        occupied = self.grid >= 65
        self.likelihood = np.zeros(occupied.shape, dtype=float)
        self.near = np.zeros_like(occupied)
        eff_tol = max(float(tolerance), float(resolution) * math.sqrt(2))
        sigma = max(.025, .75 * float(resolution))
        self._ray_margin = max(.06, 2.0 * float(resolution))
        radius = int(math.ceil(eff_tol / resolution))
        h, w = occupied.shape
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if math.hypot(dx, dy) * resolution > eff_tol + 1e-7:
                    continue
                y0, y1 = max(0, dy), min(h, h + dy)
                x0, x1 = max(0, dx), min(w, w + dx)
                self.near[y0:y1, x0:x1] |= occupied[y0-dy:y1-dy, x0-dx:x1-dx]
        spread = int(math.ceil(max(.12, 3.0 * sigma) / resolution))
        for dy in range(-spread, spread + 1):
            for dx in range(-spread, spread + 1):
                y0, y1 = max(0, dy), min(h, h + dy)
                x0, x1 = max(0, dx), min(w, w + dx)
                if y1 <= y0 or x1 <= x0:
                    continue
                value = math.exp(-((dx*resolution)**2 + (dy*resolution)**2) / (2*sigma**2))
                dest = self.likelihood[y0:y1, x0:x1]
                np.maximum(dest, occupied[y0-dy:y1-dy, x0-dx:x1-dx] * value, out=dest)

    def score(self, sensor_pose, ranges, angles):
        ranges, angles = np.asarray(ranges), np.asarray(angles)
        valid = np.isfinite(ranges) & (ranges > .05) & np.isfinite(angles)
        if np.count_nonzero(valid) < 30 or not all(map(math.isfinite, sensor_pose)):
            return 0.
        ranges, angles = ranges[valid], angles[valid] + sensor_pose[2]
        xy = np.column_stack((np.cos(angles), np.sin(angles))) * ranges[:, None]
        xy += sensor_pose[:2]
        cells = np.floor((xy - self.origin) / self.resolution).astype(int)
        h, w = self.near.shape
        inside = (cells[:, 0] >= 0) & (cells[:, 0] < w) & (cells[:, 1] >= 0) & (cells[:, 1] < h)
        hit = np.zeros(len(cells), dtype=bool)
        hit[inside] = self.near[cells[inside, 1], cells[inside, 0]]
        # An endpoint behind an intervening wall is a false match, common in
        # repeated maze corridors. Check the observed free ray as well.
        steps = np.arange(.05, max(ranges), self.resolution * .75)
        if len(steps):
            distances = np.minimum(steps[None, :], np.maximum(0., ranges[:, None] - self._ray_margin))
            direction = np.column_stack((np.cos(angles), np.sin(angles)))
            ray = np.asarray(sensor_pose[:2]) + direction[:, None, :] * distances[:, :, None]
            ray_cells = np.floor((ray-self.origin) / self.resolution).astype(int)
            rx, ry = ray_cells[:, :, 0], ray_cells[:, :, 1]
            in_map = (rx >= 0) & (rx < w) & (ry >= 0) & (ry < h)
            blocked = np.ones(rx.shape, dtype=bool)
            blocked[in_map] = self.grid[ry[in_map], rx[in_map]] >= 65
            obstructed = np.any(blocked, axis=1)
            # Grid rasterization moves a grazing wall by up to one cell. A
            # parallel ray on either side handles that uncertainty; an actual
            # intervening wall still blocks all three rays.
            normal = np.column_stack((-np.sin(angles), np.cos(angles)))
            for sign in (-1., 1.):
                shifted = ray + sign*self.resolution*normal[:, None, :]
                indices = np.floor((shifted-self.origin)/self.resolution).astype(int)
                sx, sy = indices[:, :, 0], indices[:, :, 1]
                valid = (sx >= 0) & (sx < w) & (sy >= 0) & (sy < h)
                blocked = np.ones(sx.shape, dtype=bool)
                blocked[valid] = self.grid[sy[valid], sx[valid]] >= 65
                obstructed &= np.any(blocked, axis=1)
            hit &= ~obstructed
        return float(np.mean(hit))

    def explain(self, sensor_pose, ranges, angles, *, min_cluster_beams: int = 3) -> "AgreementBreakdown":
        """Classify beams into hit, wall-pierced, clustered foreground occlusion, and unknown/open."""
        ranges, angles = valid_beams(ranges, angles)
        total = int(len(ranges))
        if total == 0 or not all(math.isfinite(v) for v in sensor_pose):
            return AgreementBreakdown(0, 0, 0, 0, 0, 0.0, 0.0, 0, 0, 0, "no-beams")
        world_angles = angles + sensor_pose[2]
        xy = np.column_stack((np.cos(world_angles), np.sin(world_angles))) * ranges[:, None]
        xy += sensor_pose[:2]
        cells = np.floor((xy - self.origin) / self.resolution).astype(int)
        h, w = self.near.shape
        inside = (cells[:, 0] >= 0) & (cells[:, 0] < w) & (cells[:, 1] >= 0) & (cells[:, 1] < h)
        hit = np.zeros(total, dtype=bool)
        hit[inside] = self.near[cells[inside, 1], cells[inside, 0]]
        obstructed = np.zeros(total, dtype=bool)
        steps = np.arange(.05, max(ranges), self.resolution * .75)
        if len(steps):
            distances = np.minimum(steps[None, :], np.maximum(0., ranges[:, None] - self._ray_margin))
            direction = np.column_stack((np.cos(world_angles), np.sin(world_angles)))
            ray = np.asarray(sensor_pose[:2]) + direction[:, None, :] * distances[:, :, None]
            ray_cells = np.floor((ray - self.origin) / self.resolution).astype(int)
            rx, ry = ray_cells[:, :, 0], ray_cells[:, :, 1]
            in_map = (rx >= 0) & (rx < w) & (ry >= 0) & (ry < h)
            blocked = np.ones(rx.shape, dtype=bool)
            blocked[in_map] = self.grid[ry[in_map], rx[in_map]] >= 65
            obstructed = np.any(blocked, axis=1)
            normal = np.column_stack((-np.sin(world_angles), np.cos(world_angles)))
            for sign in (-1., 1.):
                shifted = ray + sign * self.resolution * normal[:, None, :]
                indices = np.floor((shifted - self.origin) / self.resolution).astype(int)
                sx, sy = indices[:, :, 0], indices[:, :, 1]
                valid = (sx >= 0) & (sx < w) & (sy >= 0) & (sy < h)
                blocked = np.ones(sx.shape, dtype=bool)
                blocked[valid] = self.grid[sy[valid], sx[valid]] >= 65
                obstructed &= np.any(blocked, axis=1)
            hit &= ~obstructed
        unknown = ~hit & ~obstructed & ~inside
        unknown[inside] |= (~hit[inside] & ~obstructed[inside]
                            & (self.grid[cells[inside, 1], cells[inside, 0]] < 0))
        short_free = ~hit & ~obstructed & ~unknown
        miss_foreground, fg_cluster_count = _count_foreground_clusters(ranges, angles, short_free, min_cluster_beams)
        hit_count = int(np.count_nonzero(hit))
        pierce_count = int(np.count_nonzero(obstructed))
        unknown_count = int(np.count_nonzero(unknown))
        raw_score = 0.0 if total < 30 else float(hit_count / total)
        sectors = (np.floor(((angles % (2. * math.pi)) / (2. * math.pi)) * 8.).astype(int)) % 8
        hit_sectors = np.unique(sectors[hit])
        sectors_hit = int(len(hit_sectors))
        sector_mask = sum(1 << int(s) for s in hit_sectors)
        eval_denom = total - miss_foreground - unknown_count
        if total < 30:
            reason = "insufficient-scan"
        elif pierce_count / total > 0.03:
            reason = "wall-piercing"
        elif sectors_hit < 4:
            reason = "sparse-sectors"
        elif raw_score < 0.55:
            reason = "low-raw-fit"
        elif miss_foreground / total > 0.30:
            reason = "excess-foreground"
        elif eval_denom < max(16, int(0.45 * total)):
            reason = "insufficient-wall-beams"
        else:
            reason = None
        robust = 0.0 if reason is not None else min(1.0, float(hit_count) / float(eval_denom))
        return AgreementBreakdown(
            total=total, hit=hit_count, miss_wall_pierced=pierce_count,
            miss_foreground=miss_foreground, miss_unknown=unknown_count,
            raw_score=raw_score, robust_score=robust, sectors_hit=sectors_hit,
            sector_mask=sector_mask, fg_cluster_count=fg_cluster_count,
            rejected_reason=reason,
        )

    def robust_score(self, sensor_pose, ranges, angles) -> float:
        """Occlusion-robust wall agreement score; 0.0 when safety gates reject."""
        return self.explain(sensor_pose, ranges, angles).robust_score

    def _qualities(self, poses, ranges, angles):
        a = poses[:, 2, None] + angles[None, :]
        x = poses[:, 0, None] + np.cos(a)*ranges
        y = poses[:, 1, None] + np.sin(a)*ranges
        ix = np.floor((x-self.origin[0]) / self.resolution).astype(int)
        iy = np.floor((y-self.origin[1]) / self.resolution).astype(int)
        h, w = self.grid.shape
        inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        values = np.zeros(ix.shape)
        values[inside] = self.likelihood[iy[inside], ix[inside]]
        return np.mean(values, axis=1)

    def footprint_clear(self, x, y, radius):
        if not all(math.isfinite(v) for v in (x, y, radius)) or radius <= 0:
            return False
        h, w = self.grid.shape
        ox, oy = self.origin
        if x-radius < ox or y-radius < oy or x+radius >= ox+w*self.resolution or y+radius >= oy+h*self.resolution:
            return False
        # The window must cover the inflated radius (as clear_poses does), not just the footprint.
        inflated = radius + self.resolution/math.sqrt(2)
        ix0, ix1 = max(0, int((x-inflated-ox)/self.resolution)), min(w, int((x+inflated-ox)/self.resolution)+1)
        iy0, iy1 = max(0, int((y-inflated-oy)/self.resolution)), min(h, int((y+inflated-oy)/self.resolution)+1)
        yy, xx = np.mgrid[iy0:iy1, ix0:ix1]
        overlaps = np.hypot(ox+(xx+.5)*self.resolution-x, oy+(yy+.5)*self.resolution-y) <= inflated
        return bool(np.all(self.grid[yy[overlaps], xx[overlaps]] == 0))

    def clear_poses(self, radius):
        """Cells where a footprint of `radius` is wholly free. Unknown is never free."""
        h, w = self.grid.shape
        free = self.grid == 0
        blocked = ~free
        clear = free.copy()
        inflated_radius = radius + self.resolution/math.sqrt(2)
        cells = int(math.ceil(inflated_radius/self.resolution))
        for dy in range(-cells, cells+1):
            for dx in range(-cells, cells+1):
                if math.hypot(dx, dy)*self.resolution > inflated_radius:
                    continue
                y0, y1 = max(0, dy), min(h, h+dy)
                x0, x1 = max(0, dx), min(w, w+dx)
                if y1 > y0 and x1 > x0:
                    clear[y0:y1, x0:x1] &= ~blocked[y0-dy:y1-dy, x0-dx:x1-dx]
        return clear

    def refine(self, seeds, ranges, angles, clear, offsets=None, *, use_robust: bool = False):
        """Best three refinements per seed as (0.7*agreement + 0.3*quality, agreement, pose).

        Inputs are valid sensor-frame beams (see `valid_beams`); poses are sensor poses."""
        offsets = GLOBAL_OFFSETS if offsets is None else offsets
        h, w = self.grid.shape
        results = []
        scorer = self.robust_score if use_robust else self.score
        for seed in seeds:
            poses = np.asarray(seed) + offsets
            indices = np.floor((poses[:, :2]-self.origin)/self.resolution).astype(int)
            inside = (indices[:, 0] >= 0) & (indices[:, 0] < w) & (indices[:, 1] >= 0) & (indices[:, 1] < h)
            allowed = np.zeros(len(poses), dtype=bool)
            allowed[inside] = clear[indices[inside, 1], indices[inside, 0]]
            poses = poses[allowed]
            if not len(poses):
                continue
            quality = self._qualities(poses, ranges, angles)
            for idx in np.argsort(quality)[-3:]:
                pose = poses[idx]
                agreement = scorer(pose, ranges, angles)
                results.append((agreement*.7 + float(quality[idx])*.3, agreement, pose))
        return results

    def global_results(self, ranges, angles, radius, clear=None, *, use_robust: bool = False):
        """Every refined sensor-pose candidate, best first, and a reason when there are none.

        Coarse-to-fine: 4 cm x 5 deg seeds, the 48 best distinct ones refined by
        GLOBAL_OFFSETS. Inputs are sensor-frame observations. `clear` is an
        optional precomputed `clear_poses(radius)` mask."""
        ranges, angles = valid_beams(ranges, angles)
        if len(ranges) < 30:
            return [], 'insufficient-scan'
        clear = self.clear_poses(radius) if clear is None else clear
        stride = max(1, round(.04/self.resolution))
        yy, xx = np.nonzero(clear[::stride, ::stride])
        if not len(xx):
            return [], 'no-footprint-clear-candidate'
        xy = np.column_stack((xx*stride+.5, yy*stride+.5))*self.resolution + self.origin
        candidates = []
        for theta in np.arange(-math.pi, math.pi, math.radians(5)):
            poses = np.column_stack((xy, np.full(len(xy), theta)))
            quality = self._qualities(poses, ranges[::2], angles[::2])
            for idx in np.argsort(quality)[-16:]:
                candidates.append((float(quality[idx]), poses[idx]))
        seeds = []
        for quality, pose in sorted(candidates, key=lambda item: item[0], reverse=True):
            if all(apart(pose, other) for other in seeds):
                seeds.append(pose)
            if len(seeds) >= 48:
                break
        results = self.refine(seeds, ranges, angles, clear, use_robust=use_robust)
        if not results:
            return [], 'no-refined-candidate'
        results.sort(key=lambda item: item[0], reverse=True)
        return results, None

    def global_match(self, ranges, angles, radius, minimum=.9, margin=.04):
        """Coarse-to-fine scan search. Repeated geometry must remain ambiguous.

        Returns a candidate, not driving authority. AMCL and subsequent fresh
        scans still have to confirm it. Inputs are sensor-frame observations.
        """
        results, reason = self.global_results(ranges, angles, radius)
        if reason:
            return {'unique': False, 'reason': reason}
        best = results[0]
        competitors = [r for r in results[1:] if apart(r[2], best[2])]
        gap = best[0] - competitors[0][0] if competitors else 1.
        return {'unique': bool(best[1] >= minimum and gap >= margin),
                'pose': best[2].tolist(), 'agreement': best[1], 'quality': best[0], 'margin': gap}
