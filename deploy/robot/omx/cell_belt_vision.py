#!/usr/bin/env python3
"""Container detection on the top frame for cell_belt_pose, without tools/sim (the cell release ships deploy/robot/omx and the
adapter only). A copy of tools/sim/omx_real2sim_helpers Camera.to_plane, the container mask of blobs, fold, rect and the
container branch of lane_blobs, with the footprint passed in (from the checkpoint's ENV_STATE.json) instead of module
constants. test/test_omx_policy_belt_pose.py compares it with the original on the real frames and synthetic input; change
both together."""
from __future__ import annotations

import math

import numpy as np

_KERNEL_3X3 = np.ones((3, 3), np.uint8)


class Camera:
    """The sim's pinhole for a surveyed camera (eye, focus, up, f_px at `height` rows)."""

    def __init__(self, cam, size):
        self.h, self.w = size
        self.eye = np.array(cam["eye"], float)
        fwd = np.array(cam["focus"], float) - self.eye
        self.fwd = fwd / np.linalg.norm(fwd)
        up = np.array(cam["up"], float) - self.fwd * (np.array(cam["up"], float) @ self.fwd)
        self.up = up / np.linalg.norm(up)
        self.right = np.cross(self.fwd, self.up)
        self.f = cam["f_px"] * self.h / cam["height"]

    def to_plane(self, uv, z):
        uv = np.asarray(uv, float).reshape(-1, 2)
        d = self.fwd + ((uv[:, :1] - self.w / 2) * self.right - (uv[:, 1:] - self.h / 2) * self.up) / self.f
        return (self.eye + (z - self.eye[2]) / d[:, 2:] * d)[:, :2]


def container_outlines(frame):
    """Outline pixels of every orange, yellow, green or purple blob (the container mask of omx_real2sim blobs)."""
    import cv2

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = (((hsv[..., 0] < 18) & (hsv[..., 1] > 120) & (hsv[..., 2] > 120))
         | ((hsv[..., 0] >= 23) & (hsv[..., 0] < 30) & (hsv[..., 1] > 140) & (hsv[..., 2] > 140))
         | ((((hsv[..., 0] >= 35) & (hsv[..., 0] < 88)) | (hsv[..., 0] >= 135)) & (hsv[..., 1] > 110) & (hsv[..., 2] > 125)))
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, _KERNEL_3X3)
    for c in cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]:
        if cv2.contourArea(c) >= 150:
            yield c.reshape(-1, 2)


def fold(yaw):
    return (yaw + math.pi / 2) % math.pi - math.pi / 2


def rect(points):
    """Centre (m), long-axis yaw (rad, folded into [-90, 90) deg) and (length, width) m of plane points."""
    import cv2

    (cx, cy), (a, b), ang = cv2.minAreaRect((points * 1000).astype(np.float32))
    return (cx / 1000, cy / 1000), fold(math.radians(ang if a >= b else ang + 90)), (max(a, b) / 1000, min(a, b) / 1000)


def containers(frame, cam, belt_top, box, tol):
    """(every container-coloured blob as rect(), the footprint-matching ones as dict(xy, yaw, size, partial)) on the
    container top. box = (length, width, height) m; tol = (length, width, partial_min) m, as lane_blobs uses
    LANE, SIZE_TOL[0], SIZE_TOL[1] + 0.004 and PARTIAL_MIN for a container."""
    seen, found = [], []
    for px in container_outlines(frame):
        xy, yaw, size = rect(cam.to_plane(px, belt_top + box[2]))
        seen.append((xy, yaw, size))
        if abs(size[1] - box[1]) > tol[1] or not tol[2] <= size[0] <= box[0] + tol[0]:
            continue
        if size[1] > box[1]:  # oblique side wall widens the contour toward the camera
            v = (-math.sin(yaw), math.cos(yaw))
            sh = (.5 if (cam.eye[0] - xy[0]) * v[0] + (cam.eye[1] - xy[1]) * v[1] >= 0 else -.5) * (size[1] - box[1])
            xy, size = (xy[0] - sh * v[0], xy[1] - sh * v[1]), (size[0], box[1])
        at_bottom = int(px[:, 1].max()) >= frame.shape[0] - 2 and int(px[:, 1].min()) > 2
        if at_bottom and size[0] < box[0]:
            sh = (box[0] - size[0]) / 2
            xy = (xy[0] - sh * math.cos(yaw), xy[1] - sh * math.sin(yaw))
            size = (box[0] if size[0] >= box[0] - tol[0] else size[0], size[1])
        partial = size[0] < box[0] - tol[0]
        if not partial or at_bottom:
            found.append(dict(xy=xy, yaw=yaw, size=size, partial=partial))
    return seen, found
