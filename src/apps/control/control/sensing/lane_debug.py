"""Subject: a four-panel picture of one lane-following decision.

Observation only: it reads a follower's `last` intermediate results and
never feeds back into perception or motion.
  camera   the frame with the paint threshold tinted red
  bev      bird's-eye grid, forward up: paint grey, left boundary green,
           right boundary blue, centre band yellow, target magenta
  status   mode, ladder tier, junction signal, error and confidence
  map      lane graph with the odometry pose (in Gazebo odom is ground truth;
           on a Device it is only the robot's own estimate -- labelled)
"""

import math

import cv2
import numpy as np

PANEL_W, PANEL_H = 320, 180
_GREEN, _BLUE, _YELLOW, _MAGENTA, _GREY = (60, 220, 60), (230, 120, 40), (40, 220, 240), \
    (230, 60, 230), (120, 120, 120)


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


def _mark_target(panel_and_size, last, view):
    panel, size = panel_and_size
    target = last.get("target")
    if target is None or view is None:
        return panel
    i, j = view.cell(*target)
    row = (view.rows - 1 - i) * PANEL_H / size
    col = (PANEL_W - PANEL_H) / 2 + (j + (size - view.cols) / 2) * PANEL_H / size
    cv2.circle(panel, (int(col), int(row)), 5, _MAGENTA, -1)
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
    panel = np.full((PANEL_H, PANEL_W, 3), 30, np.uint8)
    sx, sy = PANEL_W / 2.9, PANEL_H / 1.35
    scale = min(sx, sy)

    def px(x, y):
        return int(PANEL_W / 2 + x * scale), int(PANEL_H / 2 - y * scale)

    for seg in (graph or {}).get("segments", {}).values():
        pts = np.array([px(x, y) for x, y in seg["points"]], np.int32)
        cv2.polylines(panel, [pts], False, (170, 170, 170), 1, cv2.LINE_AA)
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
    view = getattr(follower, "_view", None)
    bev_panel_and_size = _bev(last)
    top = np.hstack([_camera(frame, bright_threshold),
                     _mark_target(bev_panel_and_size, last, view) if last.get("paint") is not None
                     else np.zeros((PANEL_H, PANEL_W, 3), np.uint8)])
    tier = last.get("tier") or getattr(follower, "state", "-")
    bottom = np.hstack([_status(mode, tier, last.get("junction"), observation, last.get("source")),
                        _map(graph, pose, pose_label)])
    return np.vstack([top, bottom])
