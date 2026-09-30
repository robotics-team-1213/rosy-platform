"""Wheel odometry calibrated against LiDAR scan registration (no tape measure).

ROS-free, numpy only (D-47 addendum). Per motion segment (a run of one
constant command) the LiDAR motion comes from point-to-line ICP of each scan
against the segment's first scan, seeded by the previous estimate plus the
odometry increment, so a 360-degree pivot never loses its reference. Wheel
angles (joint_states) over the same segment then give:

  ds = r * (phi_r + phi_l) / 2            straights  -> wheel_radius r
  dth = (r / b) * (phi_r - phi_l)         pivots     -> wheel_separation b

by least squares, with standard errors from the residuals. Per-wheel radii,
the LiDAR mount yaw seen from straight drives, and actual/commanded gains are
reported beside them. The result is a candidate; nothing here changes a
runtime parameter.

Frames: base x forward, y left. A scan point at angle a is at robot heading
a - lidar_yaw_offset, the LiDAR origin at (lidar_x_m, 0) in base.
"""
from __future__ import annotations

import math

import numpy as np

MIN_RANGE_M = 0.08
MAX_RANGE_M = 4.0
ICP_ITERATIONS = 40
ICP_GATES_M = (0.20, 0.10, 0.05, 0.03)
ICP_TRIM = 0.8            # keep the best 80 % of matches
NORMAL_GAP_M = 0.06       # neighbours further apart than this give no normal
MIN_INLIER_SHARE = 0.4    # below this the registration is not trusted
SOURCE_STRIDE = 2         # every 2nd return of the moving scan (the key scan keeps all)
MIN_SEGMENT_S = 1.0
# A command component smaller than this is zero (m/s, rad/s).
COMMAND_EPS = 1e-3
STRAIGHT_MIN_M = 0.02
PIVOT_MIN_RAD = math.radians(5.0)


# --- SE(2) -----------------------------------------------------------------

def compose(a, b):
    """Pose a then b (b expressed in a's frame)."""
    c, s = math.cos(a[2]), math.sin(a[2])
    return (a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1], a[2] + b[2])


def inverse(a):
    c, s = math.cos(a[2]), math.sin(a[2])
    return (-c * a[0] - s * a[1], s * a[0] - c * a[1], -a[2])


def between(a, b):
    """b expressed in a's frame."""
    return compose(inverse(a), b)


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


# --- scans and ICP -----------------------------------------------------------

def scan_points(ranges, angle_min, angle_increment, range_min=0.0, range_max=math.inf,
                min_range=MIN_RANGE_M, max_range=MAX_RANGE_M):
    """Valid returns of one scan in the LiDAR frame, (N,2) in scan order."""
    r = np.asarray(ranges, dtype=np.float64)
    a = float(angle_min) + np.arange(r.size) * float(angle_increment)
    ok = np.isfinite(r) & (r >= max(float(range_min), min_range)) & (r <= min(float(range_max), max_range))
    return np.column_stack([r[ok] * np.cos(a[ok]), r[ok] * np.sin(a[ok])])


def _normals(pts):
    n = np.full(pts.shape, np.nan)
    if len(pts) < 3:
        return n
    t = pts[2:] - pts[:-2]
    gap = np.maximum(np.hypot(*(pts[1:-1] - pts[:-2]).T), np.hypot(*(pts[2:] - pts[1:-1]).T))
    length = np.hypot(t[:, 0], t[:, 1])
    ok = (gap < NORMAL_GAP_M) & (length > 1e-6)
    n[1:-1][ok] = np.column_stack([-t[ok, 1], t[ok, 0]]) / length[ok, None]
    return n


def icp(src, dst, init=(0.0, 0.0, 0.0), iterations=ICP_ITERATIONS):
    """Pose of the src scan in the dst scan's frame (point-to-line ICP).

    Returns ((x, y, yaw), {'inliers': share of src matched, 'rmse': m})."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    if len(src) < 10 or len(dst) < 10:
        return tuple(init), {'inliers': 0.0, 'rmse': math.inf}
    normals = _normals(dst)
    has = ~np.isnan(normals[:, 0])
    dst_n, nrm = dst[has], normals[has]
    x = np.array(init, dtype=float)
    info = {'inliers': 0.0, 'rmse': math.inf}
    per_gate = max(1, iterations // len(ICP_GATES_M))
    for gate in ICP_GATES_M:
        for _ in range(per_gate):
            c, s = math.cos(x[2]), math.sin(x[2])
            p = src @ np.array([[c, s], [-s, c]]) + x[:2]
            d2 = ((p[:, None, :] - dst_n[None, :, :]) ** 2).sum(axis=2)
            j = np.argmin(d2, axis=1)
            dist = np.sqrt(d2[np.arange(len(p)), j])
            keep = dist < gate
            if keep.sum() < 10:
                return tuple(x), {'inliers': float(keep.mean()), 'rmse': math.inf}
            cut = np.quantile(dist[keep], ICP_TRIM)
            keep &= dist <= cut
            q, n = dst_n[j[keep]], nrm[j[keep]]
            pk = p[keep]
            r = ((pk - q) * n).sum(axis=1)
            dp = pk - x[:2]
            jac = np.column_stack([n[:, 0], n[:, 1], n[:, 0] * -dp[:, 1] + n[:, 1] * dp[:, 0]])
            delta = np.linalg.lstsq(jac, -r, rcond=None)[0]
            x += delta
            info = {'inliers': float(keep.sum()) / len(src), 'rmse': float(np.sqrt(np.mean(r ** 2)))}
            if abs(delta[0]) + abs(delta[1]) < 1e-5 and abs(delta[2]) < 1e-5:
                break
    return (float(x[0]), float(x[1]), float(x[2])), info


# --- segments ---------------------------------------------------------------

def command_segments(commands, min_duration=MIN_SEGMENT_S):
    """[(t, linear, angular)] in time order -> runs of one non-zero command.

    Returns [{'t0', 't1', 'linear', 'angular'}] (median command of the run)."""
    out, run = [], []

    def close():
        if run and run[-1][0] - run[0][0] >= min_duration:
            v = np.array(run)
            out.append({'t0': float(v[0, 0]), 't1': float(v[-1, 0]),
                        'linear': float(np.median(v[:, 1])), 'angular': float(np.median(v[:, 2]))})

    for t, lin, ang in commands:
        moving = abs(lin) > COMMAND_EPS or abs(ang) > COMMAND_EPS
        if run and (not moving or np.sign(lin) != np.sign(run[-1][1]) or np.sign(ang) != np.sign(run[-1][2])):
            close()
            run = []
        if moving:
            run.append((float(t), float(lin), float(ang)))
    close()
    return out


def lidar_motion(scans, odom_guess, lidar_yaw_offset, lidar_x_m):
    """Base motion over one segment from its scans.

    scans: [(ranges, angle_min, angle_increment, range_min, range_max)] in
    time order; odom_guess: the base pose (x, y, yaw) at each scan from
    odometry (only increments are used, as ICP seeds), or None to seed each
    scan with the previous LiDAR increment (constant velocity), which keeps
    the result independent of an odometry that may be scaled or mirrored. Returns
    {'dx', 'dy', 'dth' (unwrapped), 'lidar_dx', 'lidar_dy', 'min_inliers', 'rmse'}
    in the base frame of the first scan, or {'error': ...}."""
    mount = (lidar_x_m, 0.0, -lidar_yaw_offset)
    to_lidar = lambda b: compose(compose(inverse(mount), b), mount)  # noqa: E731
    key = scan_points(*scans[0])
    pose = (0.0, 0.0, 0.0)           # LiDAR frame k in LiDAR frame 0
    last_step = (0.0, 0.0, 0.0)
    unwrapped, worst, rmses = 0.0, 1.0, []
    for k in range(1, len(scans)):
        step = to_lidar(between(odom_guess[k - 1], odom_guess[k])) if odom_guess is not None else last_step
        guess = compose(pose, step)
        est, info = icp(scan_points(*scans[k])[::SOURCE_STRIDE], key, init=guess)
        if info['inliers'] < MIN_INLIER_SHARE:
            return {'error': f'scan {k} did not register (inliers {info["inliers"]:.2f})'}
        worst, rmses = min(worst, info['inliers']), rmses + [info['rmse']]
        unwrapped += wrap(est[2] - pose[2])
        new = (est[0], est[1], unwrapped)
        last_step = between(pose, new)
        pose = new
    base = compose(compose(mount, pose), inverse(mount))
    return {'dx': base[0], 'dy': base[1], 'dth': unwrapped, 'lidar_dx': pose[0], 'lidar_dy': pose[1],
            'min_inliers': worst, 'rmse': float(np.median(rmses)) if rmses else 0.0}


# --- wheel model -------------------------------------------------------------

def _slope(x, y):
    """Least-squares y = k x through the origin: (k, standard error)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    sxx = float((x * x).sum())
    if len(x) == 0 or sxx <= 0:
        return None, None
    k = float((x * y).sum()) / sxx
    dof = len(x) - 1
    se = math.sqrt(float(((y - k * x) ** 2).sum()) / dof / sxx) if dof > 0 else None
    return k, se


def fit_wheels(segments, nominal_radius, nominal_separation):
    """segments: [{'kind': 'straight'|'pivot', 'phi_l', 'phi_r' (wheel angle change, rad),
    'ds' (signed base forward travel, m), 'dth' (base rotation, rad)}] from LiDAR.

    Returns wheel_radius, wheel_separation (with standard errors and the
    number of segments behind each), per-wheel radii and the left/right ratio."""
    straight = [s for s in segments if s['kind'] == 'straight']
    pivots = [s for s in segments if s['kind'] == 'pivot']
    out = {'nominal': {'wheel_radius': nominal_radius, 'wheel_separation': nominal_separation},
           'segments': {'straight': len(straight), 'pivot': len(pivots)}}
    r, r_se = _slope([(s['phi_r'] + s['phi_l']) / 2 for s in straight], [s['ds'] for s in straight])
    if r is None:
        r, r_se, out['wheel_radius_source'] = nominal_radius, None, 'nominal (no straight segment)'
    else:
        out['wheel_radius_source'] = 'lidar'
    out['wheel_radius'], out['wheel_radius_se'] = r, r_se
    c, c_se = _slope([s['phi_r'] - s['phi_l'] for s in segments], [s['dth'] for s in segments]) \
        if pivots else (None, None)
    if c:
        b = r / c
        rel = math.hypot((r_se or 0.0) / r, (c_se or 0.0) / c)
        out['wheel_separation'], out['wheel_separation_se'] = b, b * rel if (r_se is not None or c_se) else None
    else:
        out['wheel_separation'], out['wheel_separation_se'] = None, None
    # Per wheel: ds = (r_l phi_l + r_r phi_r) / 2 over every segment; pivots,
    # where the base barely translates, pin the ratio.
    a = np.array([[s['phi_l'] / 2, s['phi_r'] / 2] for s in segments], float)
    y = np.array([s['ds'] for s in segments], float)
    if len(segments) >= 3 and straight and pivots and np.linalg.matrix_rank(a) == 2:
        (rl, rr), *_ = np.linalg.lstsq(a, y, rcond=None)
        out['wheel_radius_left'], out['wheel_radius_right'] = float(rl), float(rr)
        out['right_to_left_ratio'] = float(rr / rl) if rl else None
    return out


def segment_record(kind, joint0, joint1, motion, command=None, duration=None, wheel_signs=(1.0, 1.0)):
    """One fit_wheels segment plus the per-segment evidence the report keeps.

    joint0/joint1: (left, right) wheel joint positions (rad) at the segment
    ends; wheel_signs turn them into forward-positive angles (Pinky Pro:
    (1, -1), the right encoder counts backwards, bringup.py). Straight travel
    is the length of the LiDAR translation, so a wrong mount yaw cannot
    shorten it by the cosine."""
    phi_l = wheel_signs[0] * (joint1[0] - joint0[0])
    phi_r = wheel_signs[1] * (joint1[1] - joint0[1])
    ds = math.copysign(math.hypot(motion['dx'], motion['dy']), motion['dx']) if kind == 'straight' else motion['dx']
    rec = {'kind': kind, 'phi_l': phi_l, 'phi_r': phi_r, 'ds': ds, 'dy': motion['dy'],
           'dth': motion['dth'], 'rmse': motion['rmse'], 'min_inliers': motion['min_inliers']}
    if kind == 'straight' and abs(motion['lidar_dx']) + abs(motion['lidar_dy']) > 0:
        # Direction of LiDAR-frame travel = the scan angle of the nose (reverse: +pi).
        heading = math.atan2(motion['lidar_dy'], motion['lidar_dx'])
        rec['lidar_nose_deg'] = math.degrees((heading + (math.pi if motion['dx'] < 0 else 0.0)) % (2 * math.pi))
    if command is not None and duration:
        lin, ang = command
        if abs(lin) > COMMAND_EPS:
            rec['linear_gain'] = math.hypot(motion['dx'], motion['dy']) / abs(lin * duration)
        if abs(ang) > COMMAND_EPS:
            rec['angular_gain'] = motion['dth'] / (ang * duration)
    return rec


def summarize(records, nominal_radius, nominal_separation, lidar_yaw_offset):
    """fit_wheels plus gains, asymmetry and the LiDAR yaw seen from straights."""
    out = fit_wheels(records, nominal_radius, nominal_separation)
    for name in ('linear_gain', 'angular_gain'):
        vals = [r[name] for r in records if name in r]
        if vals:
            out[name] = {'mean': float(np.mean(vals)), 'values': [round(v, 4) for v in vals]}
    left = [r['angular_gain'] for r in records if 'angular_gain' in r and r['dth'] > 0]
    right = [r['angular_gain'] for r in records if 'angular_gain' in r and r['dth'] < 0]
    if left and right:
        out['pivot_gain_left_right'] = [float(np.mean(left)), float(np.mean(right))]
    noses = [r['lidar_nose_deg'] for r in records if 'lidar_nose_deg' in r
             and abs(r['ds']) >= STRAIGHT_MIN_M]
    if noses:
        mean = math.degrees(math.atan2(np.mean(np.sin(np.radians(noses))), np.mean(np.cos(np.radians(noses)))))
        out['lidar_yaw_from_motion'] = {'mean_deg': round(mean % 360.0, 2), 'values_deg': [round(v, 2) for v in noses],
                                        'configured_deg': round(math.degrees(lidar_yaw_offset) % 360.0, 2)}
    return out
