"""Subject: the camera preview in drivable keep mode -- what the steering actually used, no motion.

way_runs     the steered drivable way, every 4th pixel, run-length coded for keep_debug (`drivable_way`).
drivable     True when keep_debug says the drivable way steers (or was asked to).
chain_rows   decision-chain rows 1 PERCEPTION and 2 STEERING, and the headline, from one keep_debug.
draw_drivable  the way (green), the rest dimmed, the exit, the target with its arc, header and rows.

CORE gates, stuck and Fleet/AI (rows 3-5) are not on the robot's ROS graph; the dashboard draws them
from GET /line-follow (core_ui_logic.js lineDecisionChain).
"""
import math

import cv2
import numpy as np

WAY_STEP = 4   # 320x240 -> 80x60: about 1 kB of JSON per frame, no extra inference
MAX_RUNS = 600   # <= ~3.6 kB added to keep_debug
GREEN, AMBER, RED, WHITE, MUTED = (60, 220, 60), (0, 190, 255), (60, 60, 255), (245, 248, 250), (140, 155, 168)
MAGENTA, BG = (230, 60, 230), (12, 18, 28)


def way_runs(way, age_s):
    """{w, h, runs, age_s}: row-major run lengths of the way sampled every 4th (else 8th) pixel, starting
    with a not-way run; None when even 8 is too ragged (CORE drops a keep_debug above 16 kB)."""
    for step in (WAY_STEP, 2 * WAY_STEP):
        grid = np.asarray(way)[step // 2::step, step // 2::step] > 0
        flat = grid.ravel()
        runs = ([0] if flat[0] else []) + np.diff(np.r_[0, np.flatnonzero(flat[1:] != flat[:-1]) + 1, flat.size]).tolist()
        if len(runs) <= MAX_RUNS:
            return dict(w=int(grid.shape[1]), h=int(grid.shape[0]), runs=runs, age_s=round(float(age_s), 3))
    return None


def way_mask(doc):
    """The sampled way back as an h x w bool array, or None for a malformed document."""
    try:
        w, h, runs = int(doc['w']), int(doc['h']), [int(r) for r in doc['runs']]
    except (KeyError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0 or sum(runs) != w * h or min(runs, default=0) < 0:
        return None
    return np.repeat(np.arange(len(runs)) % 2 == 1, runs).reshape(h, w)


def drivable(keep):
    return isinstance(keep, dict) and (keep.get('paint_source_used') == 'learned_drivable'
                                       or keep.get('paint_target_requested') == 'drivable')


def floor_px(projection, x, y):
    """(column, row) of a base_link floor point -- LaneKeeper.to_pixel on keep_debug's ground_projection."""
    try:
        h, pitch, f = projection['height_m'], projection['pitch_rad'], projection['focal_px']
        forward = x - projection['camera_x_offset_m']
        if forward <= 0.0:
            return None
        row = projection['principal_y'] + f * math.tan(math.atan2(h, forward) - pitch)
        return projection['principal_x'] - y * (f * math.sin(pitch) + (row - projection['principal_y'])
                                                 * math.cos(pitch)) / h, row
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def _num(value, fmt):
    return format(value, fmt) if isinstance(value, (int, float)) and not isinstance(value, bool) else '-'


def chain_rows(keep):
    """((headline, colour), [(row text, colour)]) for rows 1 PERCEPTION and 2 STEERING."""
    source, way = keep.get('paint_source_used'), keep.get('paint_drivable') or {}
    steer, strategy = keep.get('drivable_steer') or {}, str(keep.get('strategy') or 'none')
    age = (keep.get('drivable_way') or {}).get('age_s', keep.get('paint_mask_age_s'))
    perception = (GREEN if source == 'learned_drivable' and way.get('reason', 'ok') == 'ok'
                  else AMBER if source == 'learned_drivable' else RED)
    rows = [(f"1 PERCEPTION {source} | way {way.get('reason', '-')} | near {_num(way.get('near_fraction'), '.0%')}"
             f" | {way.get('branches', '-')} br | age {_num(age, '.2f')}s", perception)]
    target = keep.get('target_m') or [None, None]
    stopped = strategy == 'none' or keep.get('error') is None
    limited = 'pivot' in strategy or 'off_line' in strategy or 'crosswalk' in strategy or steer.get('exit_from_memory')
    guide = f" | guide {_num(steer.get('guide_deg'), '+.0f')}deg" if 'guide_deg' in steer else ''
    rows.append((f"2 STEERING {strategy} | tgt {_num(target[0], '.2f')},{_num(target[1], '+.2f')}"
                 f" | ahead {_num(steer.get('ahead_m'), '.2f')} | exit {steer.get('exit') or '-'}{guide}",
                 RED if stopped else AMBER if limited else GREEN))
    if perception == RED:
        return (f"STOPPED BY: PERCEPTION - {source} (not the drivable way)", RED), rows
    if stopped:
        return (f"STOPPED BY: STEERING - {keep.get('reason') or 'no target'}", RED), rows
    return ('CAMERA STEERS | CORE gates, stuck, Fleet: dashboard rows 3-5', WHITE), rows


def draw_drivable(image, *, scale, keep):
    """Draw what the drivable keep steered from onto the preview (scaled from keep's image_size)."""
    h, w = image.shape[:2]
    font = max(1, w / 400)

    def text(label, xy, colour, size):
        cv2.putText(image, label, xy, cv2.FONT_HERSHEY_SIMPLEX, size * font, colour, 1, cv2.LINE_AA)

    def px(x, y):
        point = floor_px(keep.get('ground_projection') or {}, x, y)
        if point is None or not all(math.isfinite(v) and abs(v) < 4 * max(w, h) for v in point):
            return None
        return int(round(point[0] * scale)), int(round(point[1] * scale))

    mask = way_mask(keep.get('drivable_way') or {})
    if mask is not None:
        mask = cv2.resize(mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
        image[~mask] = (image[~mask] * .5).astype(np.uint8)   # not the way: dimmed
        image[mask] = (image[mask] * .65 + np.array(GREEN) * .35).astype(np.uint8)
    steer = keep.get('drivable_steer') or {}
    for side, point in (steer.get('exit_point_m') or {}).items():
        p = px(*point) if isinstance(point, (list, tuple)) and len(point) == 2 else None
        if p is not None:
            chosen = side == steer.get('exit')
            cv2.drawMarker(image, p, AMBER if chosen else MUTED, cv2.MARKER_DIAMOND, 12, 2 if chosen else 1)
            text(f"EXIT {side.upper()}" + ('' if chosen else ' (not taken)'), (p[0] - 20, p[1] - 8),
                 AMBER if chosen else MUTED, .3)
    target = keep.get('target_m')
    if isinstance(target, (list, tuple)) and len(target) == 2 and all(isinstance(v, (int, float)) for v in target):
        x, y = target
        radius = (x * x + y * y) / (2 * y) if abs(y) > 1e-4 else None   # pure-pursuit circle tangent at the robot
        arc = [px(x * t, y * t) if radius is None else
               px(radius * math.sin(t * math.atan2(x, radius - y)), radius * (1 - math.cos(t * math.atan2(x, radius - y))))
               for t in np.linspace(0, 1, 16)]
        arc = [p for p in arc if p is not None and 0 <= p[1] < h]
        if len(arc) > 1:
            cv2.polylines(image, [np.array(arc, np.int32)], False, MAGENTA, 2)
        if arc:
            cv2.circle(image, arc[-1], 6, MAGENTA, 2)
            text(f"TARGET ahead {_num(steer.get('ahead_m'), '.2f')}m", (arc[-1][0] + 8, arc[-1][1] - 8), MAGENTA, .32)
    if isinstance(steer.get('guide_deg'), (int, float)):   # the route prior's heading (line/lane_guide), left +
        a = math.radians(steer['guide_deg'])
        base = (w - 22, 74)
        cv2.arrowedLine(image, base, (int(base[0] - 16 * math.sin(a)), int(base[1] - 16 * math.cos(a))), AMBER, 2,
                        tipLength=.4)
        text('GUIDE', (w - 44, 98), AMBER, .28)
    cv2.rectangle(image, (0, 29), (w - 1, 50), BG, -1)
    revision = str(keep.get('paint_model_revision') or '')[-8:]
    text(f"DRIVABLE | {keep.get('strategy') or 'none'} | e={_num(keep.get('error'), '+.2f')}"
         f" | {keep.get('paint_source_used')} {revision}", (5, 45), GREEN, .36)
    text('legacy lanes/regions hidden: not used for steering', (5, 62), MUTED, .27)
    (headline, colour), rows = chain_rows(keep)
    cv2.rectangle(image, (0, h - 59), (w - 1, h - 1), BG, -1)
    text(headline, (6, h - 42), colour, .40)
    for row, (label, colour) in enumerate(rows):
        text(label, (6, h - 25 + 16 * row), colour, .30)
