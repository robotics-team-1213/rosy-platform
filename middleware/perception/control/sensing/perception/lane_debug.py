"""Subject: a four-panel picture of one lane-following decision.

Observation only: it reads a follower's `last` intermediate results and
never feeds back into perception or motion.
  camera   the frame with the paint threshold tinted red
  bev      bird's-eye grid (a route follower's: its camera tracker's,
           last["tracker"] on `view`), forward up: paint grey, left boundary green,
           right boundary blue, a branch candidate orange, centre band
           yellow, target magenta, the robot a white triangle at the origin
  status   mode, ladder tier, junction signal, error and confidence
  map      lane graph (route grey, parking bays teal) with the odom pose
"""

import math

import cv2
import numpy as np

PANEL_W, PANEL_H = 320, 180
_GREEN, _BLUE, _YELLOW, _MAGENTA, _GREY = (60, 220, 60), (230, 120, 40), (40, 220, 240), \
    (230, 60, 230), (120, 120, 120)
_ORANGE = (0, 140, 255)
_WHITE = (255, 255, 255)
_PARKING = (200, 180, 60)

#: A camera stamp shortfall this small against the requested period is
#: float jitter in the sec/nanosec -> float conversion, not a genuinely
#: early frame; treating it as "not yet due" silently drops every other
#: frame at a matching publish rate (measured: 1.2 - 1.0 ==
#: 0.19999999999999996 < 0.2 at 5 Hz camera / 5 Hz max_hz).
_RATE_TOLERANCE_S = 1e-3


def next_publish_due(last_published_s, stamp_s, max_hz):
    """True if a sample at `stamp_s` should publish, given the last publish
    at `last_published_s` and a `max_hz` cap. Pure and ROS-free so the rate
    limiter is unit-testable without a node."""
    if last_published_s is None:
        return True
    period = 1.0 / max(0.1, float(max_hz))
    elapsed = float(stamp_s) - float(last_published_s)
    return elapsed < 0.0 or elapsed >= period - _RATE_TOLERANCE_S


def _fit(img):
    return cv2.resize(img, (PANEL_W, PANEL_H), interpolation=cv2.INTER_NEAREST)


def _camera(frame, threshold):
    bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if frame.ndim == 2 else frame.copy()
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    tint = bgr.copy()
    tint[gray > threshold] = (40, 40, 230)
    return _fit(cv2.addWeighted(bgr, 0.55, tint, 0.45, 0.0))


def _bev(last):
    paint = last.get("paint")
    if paint is None:
        return np.zeros((PANEL_H, PANEL_W, 3), np.uint8), 1
    img = np.zeros(paint.shape + (3,), np.uint8)
    img[paint > 0] = _GREY
    for key, colour in (("memory", _GREEN), ("right_memory", _BLUE)):
        grid = last.get(key)
        if grid is not None:
            img[grid > 0] = colour
    branch = last.get("branch_mask")
    if branch is not None:
        img[branch] = _ORANGE
    band = last.get("centre_band")
    if band is None:
        band = last.get("path")
    if band is not None:
        img[band > 0] = _YELLOW
    img = img[::-1, :]                       # forward (row index up) at the top
    size = max(img.shape[:2])
    square = np.zeros((size, size, 3), np.uint8)
    square[:img.shape[0], (size - img.shape[1]) // 2:(size - img.shape[1]) // 2 + img.shape[1]] = img
    panel = cv2.resize(square, (PANEL_H, PANEL_H), interpolation=cv2.INTER_NEAREST)
    out = np.zeros((PANEL_H, PANEL_W, 3), np.uint8)
    out[:, (PANEL_W - PANEL_H) // 2:(PANEL_W + PANEL_H) // 2] = panel
    return out, size


def _bev_pixel(view, size, x, y):
    """Panel pixel centre for a robot-frame point, matching the exact
    integer offset `_bev` used to square and scale the grid (a plain `/ 2`
    here would drift half a cell from the image whenever `size - cols` is
    odd), and using the cell centre (`+0.5`) rather than its floor corner."""
    i, j = view.cell(x, y)
    offset = (size - view.cols) // 2
    row = ((view.rows - 1 - i) + 0.5) * PANEL_H / size
    col = (PANEL_W - PANEL_H) / 2 + (offset + j + 0.5) * PANEL_H / size
    return int(round(col)), int(round(row))


def _mark_target(panel_and_size, last, view):
    panel, size = panel_and_size
    target = last.get("target")
    if target is None or view is None:
        return panel
    col, row = _bev_pixel(view, size, *target)
    cv2.circle(panel, (col, row), 5, _MAGENTA, -1)
    return panel


def _mark_robot(panel_and_size, view):
    """The robot itself, a white triangle pointing forward (+x) at the
    bird's-eye origin -- so the panel reads as "what's around me", not just
    "what's ahead of me"."""
    panel, size = panel_and_size
    if view is None:
        return panel
    col, row = _bev_pixel(view, size, 0.0, 0.0)
    triangle = np.array(
        [[col, row - 6], [col - 5, row + 5], [col + 5, row + 5]], np.int32)
    cv2.fillPoly(panel, [triangle], _WHITE)
    return panel


def _status(mode, tier, junction, observation, source):
    panel = np.full((PANEL_H, PANEL_W, 3), 24, np.uint8)
    lines = [f"mode   {mode}", f"tier   {tier}", f"signal {junction or '-'}"]
    if observation is None:
        lines += ["output NONE (CORE stops)"]
    else:
        lines += [f"error  {observation.error:+.3f}", f"conf   {observation.confidence:.2f}"]
    lines += [f"source {source or '-'}"]
    for k, text in enumerate(lines):
        cv2.putText(panel, text, (10, 28 + 26 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (240, 240, 240), 1, cv2.LINE_AA)
    return panel


def _map(graph, pose, pose_label):
    """Never raises: a malformed or partial `graph` (a hand-edited yaml, or
    one mid-write) must still leave the other three panels legible, so a
    bad segment or bay is skipped rather than crashing the whole overlay."""
    panel = np.full((PANEL_H, PANEL_W, 3), 30, np.uint8)
    sx, sy = PANEL_W / 2.9, PANEL_H / 1.35
    scale = min(sx, sy)

    def px(x, y):
        return int(PANEL_W / 2 + x * scale), int(PANEL_H / 2 - y * scale)

    segments = graph.get("segments") if isinstance(graph, dict) else None
    for seg in (segments.values() if isinstance(segments, dict) else []):
        try:
            pts = np.array([px(float(x), float(y)) for x, y in seg["points"]], np.int32)
            if len(pts) >= 2:
                cv2.polylines(panel, [pts], False, (170, 170, 170), 1, cv2.LINE_AA)
        except (KeyError, TypeError, ValueError):
            continue

    parking = graph.get("parking") if isinstance(graph, dict) else None
    bays = parking.get("points") if isinstance(parking, dict) else None
    for bay in (bays or []):
        try:
            x, y = bay
            cv2.drawMarker(panel, px(float(x), float(y)), _PARKING,
                           cv2.MARKER_SQUARE, 6, 1, cv2.LINE_AA)
        except (TypeError, ValueError):
            continue

    if pose is not None:
        x, y, yaw = pose
        tip = px(x + 0.06 * math.cos(yaw), y + 0.06 * math.sin(yaw))
        cv2.circle(panel, px(x, y), 5, (40, 40, 240), -1)
        cv2.line(panel, px(x, y), tip, (40, 40, 240), 2)
    cv2.putText(panel, pose_label, (8, PANEL_H - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (200, 200, 200), 1, cv2.LINE_AA)
    return panel


def render_debug(frame, follower, observation, *, mode, pose=None, graph=None,
                 bright_threshold=180, pose_label="odom pose"):
    last = dict(getattr(follower, "last", {}) or {})
    # Route followers keep their camera tracker's results under "tracker"
    # and its bird's-eye grid under `view`.
    tracker = last.get("tracker")
    bev_last = tracker if isinstance(tracker, dict) else last
    view = getattr(follower, "view", None) or getattr(follower, "_view", None)
    bev_panel_and_size = _bev(bev_last)
    if bev_last.get("paint") is not None:
        bev_img = _mark_target(bev_panel_and_size, bev_last, view)
        bev_img = _mark_robot((bev_img, bev_panel_and_size[1]), view)
    else:
        bev_img = np.zeros((PANEL_H, PANEL_W, 3), np.uint8)
    top = np.hstack([_camera(frame, bright_threshold), bev_img])
    tier = last.get("tier") or getattr(follower, "state", "-")
    bottom = np.hstack([_status(mode, tier, bev_last.get("junction"), observation,
                                bev_last.get("source")),
                        _map(graph, pose, pose_label)])
    return np.vstack([top, bottom])
