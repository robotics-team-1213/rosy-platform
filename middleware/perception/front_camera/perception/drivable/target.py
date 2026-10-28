"""Ground projection and centre pursuit geometry for drivable steering."""

import math

import numpy as np

ROW_BAND_M = 0.03
#: tightest arc the target asks for (1/m): map_v2_fleet's NE corner is a ~0.12 m radius quarter turn; at 5
#: (0.2 m) the v2 Gazebo lap swung out to the wall there, nose 0.13 m off it and no room to pivot (r9, r10)
MAX_TARGET_CURVATURE = 9.0

#: a remembered boundary point this close to the path robot->target blocks that target
CROSS_TOL_M = 0.015
#: boundary points nearer than this along the arc are not judged (projection and odometry noise)
CROSS_MIN_ALONG_M = 0.06


def _exit_rows(xs, rows, edge, minimum_rows, near_m):
    """Admission, point and reach use one connected frame-border opening."""
    nearest = float(xs.min())
    hit = np.flatnonzero(edge & (xs > nearest + 0.04))
    split = np.flatnonzero((np.diff(hit) > 1) | (np.diff(rows[hit]) > 2)) + 1
    runs = [run for run in np.split(hit, split) if len(run) >= minimum_rows]
    if not runs:
        return hit[:0], False
    close = [run for run in runs if float(xs[run].min()) <= nearest + near_m]
    chosen = (min(close, key=lambda run: float(xs[run].min())) if close
              else max(runs, key=lambda run: float(xs[run].max())))
    return chosen, bool(close)


def _crosses(points, tx, ty):
    """Lateral offset of the nearest remembered boundary point within CROSS_TOL_M of the arc the
    robot drives to (tx, ty) (tangent to its heading, as a pure-pursuit arc), or None. The chord
    would cut the inside of every bend."""
    d2 = tx * tx + ty * ty
    if d2 < 1e-6 or not points:
        return None
    k = 2.0 * ty / d2                                    # signed curvature, left +
    pts = np.asarray(points, float)
    if abs(k) < 1e-6:
        along, across = pts[:, 0], np.abs(pts[:, 1])
        length = tx
    else:
        r = 1.0 / k                                       # circle centre (0, r)
        dist = np.hypot(pts[:, 0], pts[:, 1] - r)
        across = np.abs(dist - abs(r))
        ang = np.arctan2(pts[:, 0], np.sign(r) * (r - pts[:, 1]))   # angle travelled along the arc
        along = ang * abs(r)
        length = math.atan2(tx, math.copysign(1.0, r) * (r - ty)) * abs(r)
    hit = (along > CROSS_MIN_ALONG_M) & (along < length) & (across < CROSS_TOL_M)
    if not hit.any():
        return None
    first = int(np.argmin(np.where(hit, along, np.inf)))
    return float(pts[first, 1])


def _row_x(rows, ground, x_offset):
    """base_link x of the floor at each image row (inf at or above the horizon)."""
    ray = ground.pitch_rad + np.arctan((np.asarray(rows, float) - ground.principal_y) / ground.focal_px)
    with np.errstate(divide="ignore"):
        return np.where(ray > 0.0, ground.height_m / np.tan(np.maximum(ray, 1e-9)), np.inf) + x_offset


def _col_y(cols, rows, ground):
    """base_link y (left +) of image columns at those rows (GroundPlane.lateral)."""
    denominator = (ground.focal_px * math.sin(ground.pitch_rad)
                   + (np.asarray(rows, float) - ground.principal_y) * math.cos(ground.pitch_rad))
    return (ground.principal_x - np.asarray(cols, float)) * ground.height_m / np.maximum(denominator, 1e-9)


def _floor_prefix(way, rows, cols, xs, ys):
    """Actual raw points connected by floor pixels, nearest first."""
    points, previous = [], None
    for i in range(len(rows) - 1, -1, -1):
        col, row = int(cols[i]), int(rows[i])
        if not (0 <= col < way.shape[1] and way[row, col] and math.isfinite(xs[i]) and math.isfinite(ys[i])):
            break
        if previous is not None:
            pc, pr = previous
            if pr - row > 2:
                break
            count = max(abs(col - pc), abs(row - pr)) + 1
            cc = np.rint(np.linspace(pc, col, count)).astype(int)
            rr = np.rint(np.linspace(pr, row, count)).astype(int)
            if not way[rr, cc].all():
                break
        points.append((float(xs[i]), float(ys[i])))
        previous = col, row
    return points


def _local_floor(way, rows, xs, centre, ground, max_x):
    """Observed near-floor ROI for alignment, not a lane centre or road end."""
    denominator = ground.focal_px * math.sin(ground.pitch_rad) + (rows - ground.principal_y) * math.cos(ground.pitch_rad)
    cols = np.clip(np.rint(ground.principal_x - centre * denominator / ground.height_m), 0, way.shape[1] - 1).astype(int)
    points = _floor_prefix(way, rows, cols, xs, _col_y(cols, rows, ground))
    end = next((i for i, point in enumerate(points) if point[0] >= max_x), len(points))
    points = points[:end]
    return points if len(points) >= 4 and all(0.0 < x < max_x for x, _ in points) else []


def _centre_target(xs, centre, lookahead):
    """(point, curvature, band). Input follows the centre from near to far in row order.
    Curvature is that span's heading change when it bends with the chord and harder;
    the chord wins for a return onto a straighter centre. The point is on that arc.
    """
    xs, centre = np.asarray(xs, float), np.asarray(centre, float)
    order = np.arange(xs.size)
    keep = np.isfinite(xs[order]) & np.isfinite(centre[order]) & (xs[order] > 0.0)
    order, band = order[keep], np.zeros(xs.shape, bool)
    if order.size == 0:
        return None, 0.0, band
    sx, sy = xs[order], centre[order]
    px, py = np.concatenate(([0.0], sx)), np.concatenate(([0.0], sy))
    arc = np.concatenate(([0.0], np.cumsum(np.hypot(np.diff(px), np.diff(py)))))
    reach = min(float(lookahead), float(arc[-1]))
    near = np.abs(arc[1:] - reach) <= ROW_BAND_M
    if not near.any():
        near = np.zeros(sx.shape, bool)
        near[int(np.argmin(np.abs(arc[1:] - reach)))] = True
    tx, ty = float(np.median(sx[near])), float(np.median(sy[near]))
    d2 = tx * tx + ty * ty
    k_chord = 0.0 if d2 < 1e-6 else 2.0 * ty / d2
    heading = np.arctan2(np.diff(py), np.diff(px))
    walked = heading[arc[1:] <= reach + 1e-6]
    k_path = 0.0
    if walked.size >= 2 and reach > 1e-3:
        k_path = math.atan2(math.sin(walked[-1] - walked[0]), math.cos(walked[-1] - walked[0])) / reach
    k = k_path if abs(k_path) > abs(k_chord) and k_path * k_chord >= 0.0 else k_chord
    k = float(max(-MAX_TARGET_CURVATURE, min(MAX_TARGET_CURVATURE, k)))
    point = (reach, ty) if abs(k) < 1e-3 else (
        math.sin(k * reach) / k, (1.0 - math.cos(k * reach)) / k)
    band[order[near]] = True
    return point, k, band


def _arc_floor(way, ground, x_offset, curvature, reach):
    """Visible source-arc raster support: False is known non-way, None is unknown."""
    along = np.linspace(0.0, reach, 2 * max(way.shape) + 1)
    x, y = ((along, np.zeros_like(along)) if abs(curvature) < 1e-6 else
            (np.sin(curvature * along) / curvature, (1.0 - np.cos(curvature * along)) / curvature))
    forward = x - x_offset
    sine, cosine = math.sin(ground.pitch_rad), math.cos(ground.pitch_rad)
    depth = forward * cosine + ground.height_m * sine
    with np.errstate(divide='ignore', invalid='ignore'):
        u = ground.principal_x - ground.focal_px * y / depth
        v = ground.principal_y + ground.focal_px * (ground.height_m * cosine - forward * sine) / depth
    visible = np.flatnonzero((depth > 0.0) & np.isfinite(u) & np.isfinite(v)
        & (u >= 0.0) & (u <= way.shape[1] - 1) & (v >= 0.0) & (v <= way.shape[0] - 1))
    if not len(visible):
        return None
    cols, rows = np.rint(u[visible]).astype(int), np.rint(v[visible]).astype(int)
    if not way[rows, cols].all():
        return False
    jumps = np.flatnonzero((np.maximum(np.abs(np.diff(cols)), np.abs(np.diff(rows))) > 1)
                          & (np.diff(visible) == 1))
    for i in jumps:
        count = max(abs(cols[i + 1] - cols[i]), abs(rows[i + 1] - rows[i])) + 1
        cc = np.rint(np.linspace(cols[i], cols[i + 1], count)).astype(int)
        rr = np.rint(np.linspace(rows[i], rows[i + 1], count)).astype(int)
        if not way[rr, cc].all():
            return False
    return True


def _observed_target(choice, xs, centre, lookahead, way, ground, x_offset):
    """Correct a known off-floor source estimate only with a supported same-band chord."""
    point, curvature, band = choice
    if point is None:
        return choice
    tx, ty = float(np.median(xs[band])), float(np.median(centre[band]))
    chord = max(-MAX_TARGET_CURVATURE, min(MAX_TARGET_CURVATURE, 2.0 * ty / (tx * tx + ty * ty)))
    if abs(curvature) <= abs(chord) + 1e-9:
        return choice
    valid = np.isfinite(xs) & np.isfinite(centre) & (xs > 0.0)
    reach = min(lookahead, float(np.hypot(np.diff(np.r_[0.0, xs[valid]]),
                                        np.diff(np.r_[0.0, centre[valid]])).sum()))
    if (_arc_floor(way, ground, x_offset, curvature, reach) is not False
            or _arc_floor(way, ground, x_offset, chord, reach) is not True):
        return choice
    point = (reach, ty) if abs(chord) < 1e-3 else (math.sin(chord * reach) / chord,
                                                  (1.0 - math.cos(chord * reach)) / chord)
    return point, chord, band


#: rows averaged before an edge's slope is taken for the one-edge centre offset
EDGE_SMOOTH_ROWS = 7


def one_edge_centre(xs, edge, offset, seen=None):
    """(x, y) arrays: each edge point (xs, edge; base_link, left +) moved `offset` along the edge's left
    normal (negative: right), the slope taken over a moving average of EDGE_SMOOTH_ROWS pixel-stepped rows.
    `seen` (default all): rows where the edge is the way's edge, not the frame border; a window with an
    unseen row keeps the across-row offset (slope 0), a frame border step is no bend."""
    k = min(EDGE_SMOOTH_ROWS, len(xs))
    smooth = lambda v: np.convolve(np.pad(v, (k // 2, k - 1 - k // 2), mode="edge"), np.ones(k) / k, "valid")  # noqa: E731
    with np.errstate(divide="ignore", invalid="ignore"):   # rows at one range give an infinite slope
        slope = np.nan_to_num(np.gradient(smooth(edge), smooth(xs)), nan=0.0, posinf=1e6, neginf=-1e6)
    if seen is not None:
        slope = np.where(smooth(np.asarray(seen, float)) > 1.0 - 1e-9, slope, 0.0)
    norm = np.hypot(1.0, slope)
    return xs - offset * slope / norm, edge + offset / norm


def _to_world(point, pose):
    x, y, yaw = pose
    return (x + math.cos(yaw) * point[0] - math.sin(yaw) * point[1], y + math.sin(yaw) * point[0] + math.cos(yaw) * point[1])


def _to_current(point, source_pose, current_pose):
    """A base_link point at source_pose seen from current_pose ((x, y, yaw) odometry)."""
    if source_pose is None or current_pose is None:
        return point
    xs, ys, yaws = source_pose
    xc, yc, yawc = current_pose
    wx = xs + math.cos(yaws) * point[0] - math.sin(yaws) * point[1]
    wy = ys + math.sin(yaws) * point[0] + math.cos(yaws) * point[1]
    dx, dy = wx - xc, wy - yc
    return (math.cos(yawc) * dx + math.sin(yawc) * dy, -math.sin(yawc) * dx + math.cos(yawc) * dy)
