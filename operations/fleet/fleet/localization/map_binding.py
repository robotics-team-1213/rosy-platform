"""D-1022: bind a robot's saved SLAM map to the active site map frame.

A binding is ``site = R(yaw) * robot_map + t`` fitted by Fleet itself from point pairs, judged on held-out
points, and recorded with the content id of the grid the robot actually loaded (``map_grid_id``). The rigid
fit, its 180 degree and mirror checks follow ``tools/calibration/slam_map_align.py`` (copied, as D-989 did,
because that tool is not in the Fleet deployment).

``propose_from_walls`` needs no markers or tape: the arena is a known rectangle, so the robot map's occupied
cells give the walls; the minimum-area rectangle of those cells is matched to the site rectangle. A rectangle
fits two ways (0 and 180 degrees); a seed (one site point where the robot is known to be) picks the one.
The proposal is only pairs: the binding is still judged and approved like any other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

MAX_RESIDUAL_M = 0.05
MIN_SPAN_M = 1.0
MAX_HOLDOUT_M = 0.05
MIN_SPREAD_M = 0.05  # rms distance from the best line; below this the points are collinear
#: Wall rectangle sides may differ from the site arena by this share (map resolution, wall thickness).
RECT_TOLERANCE = 0.12

Point = tuple[float, float]


class BindingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Fit:
    yaw: float
    tx: float
    ty: float
    residuals: tuple[float, ...]

    @property
    def max(self) -> float:
        return max(self.residuals)

    @property
    def rms(self) -> float:
        return math.sqrt(sum(r * r for r in self.residuals) / len(self.residuals))

    def apply(self, p: Sequence[float]) -> Point:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return (c * p[0] - s * p[1] + self.tx, s * p[0] + c * p[1] + self.ty)

    def inverse(self, p: Sequence[float]) -> Point:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        x, y = p[0] - self.tx, p[1] - self.ty
        return (c * x + s * y, -s * x + c * y)


def _mean(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _spread(pts) -> float:
    """Smallest principal rms of the points: about 0 when they lie on one line."""
    mx, my = _mean(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts) / len(pts)
    syy = sum((p[1] - my) ** 2 for p in pts) / len(pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / len(pts)
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    return math.sqrt(max(0.0, tr / 2 - math.sqrt(max(0.0, tr * tr / 4 - det))))


def _with_yaw(robot, site, yaw) -> Fit:
    c, s = math.cos(yaw), math.sin(yaw)
    (rx, ry), (sx, sy) = _mean(robot), _mean(site)
    tx, ty = sx - (c * rx - s * ry), sy - (s * rx + c * ry)
    fit = Fit(yaw, tx, ty, ())
    return Fit(yaw, tx, ty, tuple(math.dist(fit.apply(r), q) for r, q in zip(robot, site)))


def fit_rigid(robot: Sequence[Point], site: Sequence[Point]) -> Fit:
    if len(robot) != len(site) or len(robot) < 3:
        raise BindingError("TOO_FEW_PAIRS", "a binding needs at least 3 point pairs")
    for name, pts in (("robot map", robot), ("site", site)):
        if _spread(pts) < MIN_SPREAD_M:
            raise BindingError("COLLINEAR", f"{name} points lie on one line; add a point off the line")
    (rx, ry), (sx, sy) = _mean(robot), _mean(site)
    num = sum((r[0] - rx) * (q[1] - sy) - (r[1] - ry) * (q[0] - sx) for r, q in zip(robot, site))
    den = sum((r[0] - rx) * (q[0] - sx) + (r[1] - ry) * (q[1] - sy) for r, q in zip(robot, site))
    return _with_yaw(robot, site, math.atan2(num, den))


def judge(robot: Sequence[Point], site: Sequence[Point], holdout: Sequence[tuple[Point, Point]] = (), *,
          max_residual: float = MAX_RESIDUAL_M, min_span: float = MIN_SPAN_M,
          max_holdout: float = MAX_HOLDOUT_M, require_holdout: bool = True) -> tuple[Fit, list[float]]:
    """The fit Fleet records, or BindingError. Returns (fit, holdout errors in metres)."""
    fit = fit_rigid(robot, site)
    if fit.max > max_residual:
        mirrored = fit_rigid([(p[0], -p[1]) for p in robot], site)
        code = "MIRRORED" if mirrored.max <= max_residual else "RESIDUAL"
        raise BindingError(code, f"max residual {fit.max:.3f} m exceeds {max_residual} m")
    if _with_yaw(robot, site, fit.yaw + math.pi).max <= max_residual:
        raise BindingError("AMBIGUOUS_FLIP", "the 180 degree alternative fits as well; add points off the symmetry")
    span = max(math.dist(a, b) for a in site for b in site)
    if span < min_span:
        raise BindingError("SPAN", f"pairs span {span:.2f} m, need at least {min_span} m")
    if require_holdout and not holdout:
        raise BindingError("HOLDOUT_REQUIRED", "at least one held-out point pair is required")
    errors = [math.dist(fit.apply(r), q) for r, q in holdout]
    if any(e > max_holdout for e in errors):
        raise BindingError("HOLDOUT", f"held-out error {max(errors):.3f} m exceeds {max_holdout} m")
    return fit, errors


# ---------------------------------------------------------------- marker-free proposal from the walls

def _hull(points: Sequence[Point]) -> list[Point]:
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def min_area_rect(points: Sequence[Point]) -> tuple[Point, float, float, float]:
    """(centre, long side, short side, angle of the long side) of the smallest enclosing rectangle."""
    hull = _hull(points)
    if len(hull) < 3:
        raise BindingError("NO_WALLS", "the robot map has too few occupied cells to find walls")
    best = None
    for i in range(len(hull)):
        (x1, y1), (x2, y2) = hull[i], hull[(i + 1) % len(hull)]
        theta = math.atan2(y2 - y1, x2 - x1)
        c, s = math.cos(-theta), math.sin(-theta)
        xs = [c * p[0] - s * p[1] for p in hull]
        ys = [s * p[0] + c * p[1] for p in hull]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if best is None or area < best[0]:
            u, v = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            cx, cy = math.cos(theta) * u - math.sin(theta) * v, math.sin(theta) * u + math.cos(theta) * v
            best = (area, (cx, cy), max(xs) - min(xs), max(ys) - min(ys), theta)
    _, centre, w, h, theta = best
    if w < h:
        w, h, theta = h, w, theta + math.pi / 2
    return centre, w, h, theta


def propose_from_walls(occupied: Sequence[Point], arena: tuple[float, float, float, float], *,
                       seed_robot: Point, seed_site: Point,
                       tolerance: float = RECT_TOLERANCE) -> tuple[list[Point], list[Point]]:
    """Pairs (robot map corners, site corners) from the arena walls, oriented by one seed.

    ``arena`` is (min_x, min_y, max_x, max_y) of the site rectangle (long side along x). ``seed_robot`` is the
    robot's own map pose and ``seed_site`` where it is known to stand (its bay, a taped start); only the
    choice between the two 180 degree fits uses it, so it may be off by much less than half the arena.
    """
    min_x, min_y, max_x, max_y = arena
    site_w, site_h = max_x - min_x, max_y - min_y
    if site_w < site_h:
        raise BindingError("ARENA", "arena long side must be along x")
    centre, w, h, theta = min_area_rect(occupied)
    if abs(w - site_w) > tolerance * site_w or abs(h - site_h) > tolerance * site_h:
        raise BindingError("WALLS_MISMATCH", f"walls {w:.2f} x {h:.2f} m do not match the arena "
                           f"{site_w:.2f} x {site_h:.2f} m")
    hw, hh = w / 2, h / 2
    c, s = math.cos(theta), math.sin(theta)
    robot_corners = [(centre[0] + c * dx - s * dy, centre[1] + s * dx + c * dy)
                     for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
    site_corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    options = []
    for turn in (0, 2):  # the same rectangle read the other way round
        site = site_corners[turn:] + site_corners[:turn]
        fit = fit_rigid(robot_corners, site)
        options.append((math.dist(fit.apply(seed_robot), seed_site), robot_corners, site))
    options.sort(key=lambda o: o[0])
    if options[1][0] - options[0][0] < 0.25 * min(site_w, site_h):
        raise BindingError("SEED_AMBIGUOUS", "the seed does not tell the two orientations apart; "
                           "use a seed away from the arena centre")
    return options[0][1], options[0][2]


def bound_pose(fit: Fit, pose: Sequence[float]) -> tuple[float, float, float]:
    """A robot map pose (x, y, yaw) in the site frame."""
    x, y = fit.apply(pose[:2])
    yaw = math.atan2(math.sin(pose[2] + fit.yaw), math.cos(pose[2] + fit.yaw))
    return (x, y, yaw)
