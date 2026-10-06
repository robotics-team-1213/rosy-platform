"""Camera extrinsics from LiDAR walls, for the stationary calibration step.

ROS-free and numpy-only (D-47 addendum, D-364 section 3, D-379). A LiDAR return
is a vertical wall standing on the floor, WALL_HEIGHT_M tall. Its floor contact
and its top project to image rows that depend on the camera pitch, roll and
lens height. The fit picks the extrinsics that put those rows on the image's
horizontal brightness edges: bright wall over dark carpet at the contact
(negative vertical gradient), dark room over bright wall at the top (positive).

Frames (metres, radians):
  base    base_footprint on the floor: x forward, y left, z up.
  camera  pinhole at (x_offset_m, 0, height_m), pitched down by pitch_rad and
          rolled by roll_rad (clockwise in the image is positive); image
          column grows to the right (-y), row grows downwards.
  scan    robot yaw = scan angle - lidar_yaw_offset (sensing/lidar.py).

The fitted result is a candidate only. Nothing here changes a runtime
parameter: an operator applies it (D-47 addendum).
"""
from __future__ import annotations

import dataclasses
import math
import warnings
from dataclasses import dataclass

import numpy as np

# Track perimeter and inner walls (map_260905.world; D-379 video estimate).
WALL_HEIGHT_M = 0.155
# base_link -> rplidar_mount x in the sim URDF (rosy.urdf.xacro); used when TF has none.
LIDAR_X_OFFSET_M = -0.017
MIN_RANGE_M = 0.08    # closer returns are the robot's own body
MAX_RANGE_M = 1.6     # a far wall spans a few rows only
MIN_AHEAD_M = 0.3     # a wall closer than this has its top above the image
PROFILE_KEYS = ('width', 'height', 'fx', 'cx', 'cy', 'pitch_rad', 'height_m', 'x_offset_m')

# Search windows. Coarse pitch x height, then a fine pitch x height x roll box.
PITCH_RANGE_DEG = (0.0, 25.0)
HEIGHT_RANGE_M = (0.03, 0.10)
ROLL_RANGE_DEG = (-4.0, 4.0)
COARSE_PITCH_STEP_DEG = 0.5
COARSE_HEIGHT_STEP_M = 0.005
# The fine steps below are the robot's startup step (calibration_camera runs the whole grid
# on the Pi). The offline PC fit (tools/calibration/analyze_session.py) passes PC_FINE_STEPS:
# roll and height four and 2.5 times finer, about 20 times the grid. Pitch stays 0.1 deg:
# real track fits band it at 0.6 deg (D-47 table), so a finer pitch step resolves nothing.
FINE_PITCH_STEP_DEG = 0.1
FINE_HEIGHT_STEP_M = 0.0025
FINE_ROLL_STEP_DEG = 0.5
FINE_STEPS = {'pitch_deg': FINE_PITCH_STEP_DEG, 'roll_deg': FINE_ROLL_STEP_DEG, 'height_m': FINE_HEIGHT_STEP_M}
PC_FINE_STEPS = {'pitch_deg': 0.1, 'roll_deg': 0.1, 'height_m': 0.001}
# Parameter values whose best score stays within this share of the peak are
# "as good": their span is the reported uncertainty.
SCORE_BAND = 0.10
# Height is taken from the fit only when its band is narrower than this;
# otherwise the base profile height is kept and the fit is pitch/roll only.
HEIGHT_OBSERVABLE_SPAN_M = 0.02
# A candidate is recommended only when it beats the base profile by this much
# (edge response units, same scale as learning/training/perception/dataset/labels.py) and
# sees enough wall returns.
SCORE_MARGIN = 2.0
MIN_WALL_POINTS = 60
# The yaw cross-check flags the LiDAR mount when the camera prefers a yaw this far off.
YAW_CHECK_RANGE_DEG = 15.0
YAW_DISAGREE_DEG = 3.0


@dataclass(frozen=True)
class CameraPose:
    width: int
    height: int
    fx: float
    cx: float
    cy: float
    pitch_rad: float
    height_m: float
    x_offset_m: float = 0.0
    roll_rad: float = 0.0

    @classmethod
    def from_profile(cls, profile, width=None, height=None):
        """A camera_nominal.yaml mapping, scaled to a width x height frame."""
        scale = 1.0 if width is None else float(width) / float(profile['width'])
        if height is not None and abs(float(height) / float(profile['height']) - scale) > 0.01 * scale:
            raise ValueError(f'frame {width}x{height} does not match the profile aspect')
        return cls(int(round(float(profile['width']) * scale)), int(round(float(profile['height']) * scale)),
                   float(profile['fx']) * scale, float(profile['cx']) * scale, float(profile['cy']) * scale,
                   float(profile['pitch_rad']), float(profile['height_m']),
                   float(profile.get('x_offset_m', 0.0)), float(profile.get('roll_rad', 0.0)))

    def replace(self, **kw):
        return dataclasses.replace(self, **kw)

    def project(self, pts):
        """(N,3) base-frame points -> (u, v, depth). depth <= 0 is behind the lens."""
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        dx = pts[:, 0] - self.x_offset_m
        dy = pts[:, 1]
        dz = pts[:, 2] - self.height_m
        s, c = math.sin(self.pitch_rad), math.cos(self.pitch_rad)
        depth = dx * c - dz * s
        up = dx * s + dz * c
        with np.errstate(divide='ignore', invalid='ignore'):
            x = -self.fx * dy / depth          # right of the optical axis, px
            y = -self.fx * up / depth          # below it, px
        sr, cr = math.sin(self.roll_rad), math.cos(self.roll_rad)
        return self.cx + cr * x - sr * y, self.cy + sr * x + cr * y, depth


def scan_to_base(ranges, angle_min, angle_increment, range_min, range_max, *,
                 yaw_offset_rad, x_offset_m=LIDAR_X_OFFSET_M, min_range_m=MIN_RANGE_M,
                 max_range_m=MAX_RANGE_M):
    """One scan -> (N,2) base-frame xy of its valid returns, in scan order."""
    r = np.asarray(ranges, dtype=np.float64)
    a = float(angle_min) + np.arange(r.size) * float(angle_increment) - float(yaw_offset_rad)
    ok = np.isfinite(r) & (r >= max(float(range_min), min_range_m)) & (r <= min(float(range_max), max_range_m))
    return np.column_stack([r[ok] * np.cos(a[ok]) + x_offset_m, r[ok] * np.sin(a[ok])])


def median_ranges(scans):
    """Per-beam median of stationary scans of equal length (inf/nan where no beam agrees)."""
    stack = np.asarray([np.asarray(s, dtype=np.float64) for s in scans])
    stack = np.where(np.isfinite(stack) & (stack > 0.0), stack, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)  # all-NaN beams: no return
        out = np.nanmedian(stack, axis=0) if len(stack) else np.array([])
    return np.where(np.isnan(out), np.inf, out)


def to_gray(image):
    """HxW or HxWx3 uint8 -> float32 gray (channel order does not matter much here)."""
    a = np.asarray(image, dtype=np.float32)
    return a if a.ndim == 2 else a[..., :3].mean(axis=2)


def vertical_gradient(gray):
    """Row r+1 minus row r-1, smoothed over 5 columns only (numpy only).

    No row smoothing: the edge must stay sharp in rows, which is what pins
    the lens height apart from the pitch (see fit_camera_extrinsic)."""
    g = np.asarray(gray, dtype=np.float32)
    k = np.ones(5, np.float32) / 5.0
    g = np.apply_along_axis(lambda row: np.convolve(row, k, mode='same'), 1, g)
    d = np.zeros_like(g)
    d[1:-1] = (g[2:] - g[:-2]) / 2.0
    return d


def wall_edge_score(cam: CameraPose, samples, wall_height_m=WALL_HEIGHT_M):
    """(mean edge response over projected wall contacts and tops, contacts used).

    samples: [(xy (N,2) base-frame wall returns, vertical_gradient image)].
    Contacts (bright wall over dark carpet: negative gradient) and tops (dark
    room over bright wall: positive) count separately, so a near wall whose
    top is above the image, or a board taller than a track wall, still pins
    its contact row. The score is None when no contact lands in the image."""
    total, items, n = 0.0, 0, 0
    for xy, grad in samples:
        xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        if len(xy) == 0:
            continue
        h, w = grad.shape
        for z, sign in ((0.0, -1.0), (wall_height_m, 1.0)):
            u, v, d = cam.project(np.column_stack([xy, np.full(len(xy), z)]))
            u, v = np.rint(u), np.rint(v)
            ok = (d > 0.05) & (u >= 0) & (u < w) & (v >= 0) & (v < h)
            if not ok.any():
                continue
            total += sign * float(grad[v[ok].astype(int), u[ok].astype(int)].sum())
            items += int(ok.sum())
            n += int(ok.sum()) if z == 0.0 else 0
    return (total / items if n else None), n


def _grid(lo, hi, step):
    return np.round(np.arange(lo, hi + step * 0.5, step), 6)


def _band(values, scores, peak):
    """Span of parameter values whose best score is within SCORE_BAND of the peak."""
    keep = [v for v, s in zip(values, scores) if s is not None and s >= peak - SCORE_BAND * abs(peak)]
    return (min(keep), max(keep)) if keep else (None, None)


def _profile(table, index):
    """Best score per value of one parameter over the others: (values, scores)."""
    best = {}
    for key, (s, _n) in table.items():
        if s is not None and (key[index] not in best or s > best[key[index]]):
            best[key[index]] = s
    values = sorted(best)
    return values, [best[v] for v in values]


def fit_camera_extrinsic(base: CameraPose, samples, wall_height_m=WALL_HEIGHT_M, fit_height=True, steps=None):
    """Pitch, roll and (if observable) lens height that align LiDAR walls with image edges.

    Returns a dict: pitch_rad, roll_rad, height_m, height_source ('fit' or
    'base'), score, score_at_base, wall_points, uncertainty (half band widths)
    and recommended; or {'error': ...} when no wall return is in view.

    steps: the fine grid steps {pitch_deg, roll_deg, height_m}, default FINE_STEPS (the
    robot's); the result's fit_step states them, and a band is resolved to one step. The
    fine height window stays inside HEIGHT_RANGE_M, so an optimum on its edge reads at_bound."""
    steps = dict(FINE_STEPS if steps is None else steps)
    score_at_base, n_base = wall_edge_score(base, samples, wall_height_m)

    def coarse(heights):
        table = {}
        for h in heights:
            for p in _grid(*PITCH_RANGE_DEG, COARSE_PITCH_STEP_DEG):
                table[(float(p), float(h))] = wall_edge_score(
                    base.replace(pitch_rad=math.radians(p), height_m=float(h), roll_rad=0.0),
                    samples, wall_height_m)
        return {k: v for k, v in table.items() if v[0] is not None}

    scored = coarse(_grid(*HEIGHT_RANGE_M, COARSE_HEIGHT_STEP_M) if fit_height else [base.height_m])
    if not scored:
        return {'error': 'no LiDAR wall return in view', 'score_at_base': score_at_base,
                'wall_points': n_base}
    p0, h0 = max(scored, key=lambda k: scored[k][0])
    h_lo, h_hi = _band(*_profile(scored, 1), scored[(p0, h0)][0])
    height_observable = fit_height and h_lo is not None and h_hi - h_lo < HEIGHT_OBSERVABLE_SPAN_M
    if not height_observable and h0 != base.height_m:
        at_base = coarse([base.height_m])
        p0, h0 = max(at_base, key=lambda k: at_base[k][0]) if at_base else (p0, base.height_m)
    fine = {}
    fine_heights = (_grid(max(h0 - 2 * COARSE_HEIGHT_STEP_M, HEIGHT_RANGE_M[0]),
                          min(h0 + 2 * COARSE_HEIGHT_STEP_M, HEIGHT_RANGE_M[1]), steps['height_m'])
                    if height_observable else np.array([h0]))
    for h in fine_heights:
        for p in _grid(p0 - 1.0, p0 + 1.0, steps['pitch_deg']):
            for r in _grid(*ROLL_RANGE_DEG, steps['roll_deg']):
                fine[(float(p), float(h), float(r))] = wall_edge_score(
                    base.replace(pitch_rad=math.radians(p), height_m=float(h), roll_rad=math.radians(r)),
                    samples, wall_height_m)
    fine = {k: v for k, v in fine.items() if v[0] is not None}
    best = max(fine, key=lambda k: fine[k][0])
    peak, n = fine[best]
    p_lo, p_hi = _band(*_profile(fine, 0), peak)
    r_lo, r_hi = _band(*_profile(fine, 2), peak)
    if height_observable:
        # The fine table resolves height to its step; where its band reaches the fine
        # window the coarse band's extent is kept too.
        f_lo, f_hi = _band(*_profile(fine, 1), peak)
        if f_lo is not None:
            h_lo, h_hi = ((f_lo, f_hi) if fine_heights[0] < f_lo and f_hi < fine_heights[-1]
                          else (min(f_lo, h_lo), max(f_hi, h_hi)))
    # An optimum on the edge of a search window is not an optimum: the scene
    # (walls of unknown height, lane tape) fooled the score.
    at_bound = (min(abs(best[0] - PITCH_RANGE_DEG[0]), abs(best[0] - PITCH_RANGE_DEG[1])) < 1e-6
                or min(abs(best[2] - ROLL_RANGE_DEG[0]), abs(best[2] - ROLL_RANGE_DEG[1])) < 1e-6
                or (height_observable and min(abs(best[1] - HEIGHT_RANGE_M[0]),
                                              abs(best[1] - HEIGHT_RANGE_M[1])) < 1e-6))
    recommended = (not at_bound and n >= MIN_WALL_POINTS and
                   (score_at_base is None or peak >= score_at_base + SCORE_MARGIN))
    return {
        'pitch_rad': math.radians(best[0]), 'roll_rad': math.radians(best[2]), 'height_m': best[1],
        'height_source': 'fit' if height_observable else 'base',
        'score': round(peak, 3), 'score_at_base': None if score_at_base is None else round(score_at_base, 3),
        'wall_points': n,
        'uncertainty': {'pitch_deg': round((p_hi - p_lo) / 2, 2), 'roll_deg': round((r_hi - r_lo) / 2, 2),
                        'height_m': round((h_hi - h_lo) / 2, 4) if h_lo is not None else None},
        'fit_step': steps,
        'recommended': bool(recommended),
        'at_bound': bool(at_bound),
        'why': ('fit beats the base profile' if recommended else
                'optimum on the search bound (scene walls not usable)' if at_bound else
                'too few wall returns in view' if n < MIN_WALL_POINTS else
                'fit not better than the base profile by the margin'),
    }


def yaw_check(cam: CameraPose, scans_and_grads, yaw_offset_rad, *, x_offset_m=LIDAR_X_OFFSET_M,
              wall_height_m=WALL_HEIGHT_M, span_deg=YAW_CHECK_RANGE_DEG, step_deg=1.0):
    """Camera evidence on the LiDAR mount yaw, at a fixed camera.

    scans_and_grads: [((ranges, angle_min, angle_increment, range_min, range_max), gradient)].
    Returns configured and best yaw (deg), their scores and whether they disagree."""
    curve = {}
    for d in _grid(-span_deg, span_deg, step_deg):
        yaw = yaw_offset_rad + math.radians(d)
        samples = [(_ahead(scan_to_base(*scan, yaw_offset_rad=yaw, x_offset_m=x_offset_m)), grad)
                   for scan, grad in scans_and_grads]
        curve[float(d)] = wall_edge_score(cam, samples, wall_height_m)[0]
    scored = {k: v for k, v in curve.items() if v is not None}
    if not scored:
        return {'error': 'no LiDAR wall return in view'}
    best = max(scored, key=scored.get)
    configured = math.degrees(yaw_offset_rad)
    return {'configured_deg': round(configured, 2), 'best_deg': round(configured + best, 2),
            'score_at_configured': None if curve.get(0.0) is None else round(curve[0.0], 3),
            'score_at_best': round(scored[best], 3),
            'disagrees': bool(abs(best) > YAW_DISAGREE_DEG and
                              (curve.get(0.0) is None or scored[best] >= curve[0.0] + SCORE_MARGIN))}


def _ahead(xy, min_ahead_m=MIN_AHEAD_M):
    return xy[xy[:, 0] > min_ahead_m] if len(xy) else xy


def wall_samples(scans_and_grads, yaw_offset_rad, x_offset_m=LIDAR_X_OFFSET_M):
    """[(scan tuple, gradient)] -> [(wall xy ahead of the camera, gradient)] for the fit."""
    return [(_ahead(scan_to_base(*scan, yaw_offset_rad=yaw_offset_rad, x_offset_m=x_offset_m)), grad)
            for scan, grad in scans_and_grads]


def candidate_profile(base_profile, fit, *, revision, source, yaw=None):
    """A camera_nominal.yaml-shaped candidate plus revision/source/score/uncertainty.

    Intrinsics and x_offset_m come from base_profile unchanged. roll_rad is
    reported; the runtime ground models ignore it today (pitch/height only)."""
    out = {k: base_profile[k] for k in base_profile if k in PROFILE_KEYS or k == 'max_range_m'}
    out.update(pitch_rad=round(float(fit['pitch_rad']), 5), height_m=round(float(fit['height_m']), 4),
               roll_rad=round(float(fit['roll_rad']), 5))
    out.update(revision=str(revision), source=str(source), score=fit['score'],
               score_at_base=fit['score_at_base'], wall_points=fit['wall_points'],
               uncertainty=fit['uncertainty'], fit_step=fit.get('fit_step', FINE_STEPS),
               height_source=fit['height_source'],
               recommended=fit['recommended'], why=fit['why'],
               base={'pitch_rad': float(base_profile['pitch_rad']), 'height_m': float(base_profile['height_m'])})
    if yaw is not None:
        out['lidar_yaw_check'] = yaw
    return out
