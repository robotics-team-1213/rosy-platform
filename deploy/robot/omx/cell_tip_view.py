#!/usr/bin/env python3
"""Where the jaw tip is in the top and side frames at a stop: FK of the stopped joints, projected with the cameras' surveyed
poses, and a crop around it. 2026-11-07: a box in front hid arm_b's tip in the side view, and whole frames, a vision model
and the frames in time order did not tell a contact from a finished descent; a person looking at the tip's crop could.

Config `tip_view` (site data, in the frame the cameras were surveyed in: learning/envs/isaac/cell_model_inventory.yaml
`layout`, whose work table top is z 0.072, so a base on the 12 mm plate is at z 0.084):

  "tip_view": {"base": {"xy": [0.104, 0.153], "yaw_deg": -94.3, "z": 0.084},
               "cameras": {"top": {"eye": [-0.0411, 0.0374, 0.6652], "focus": [0.0722, 0.0401, 0.1783],
                                   "up": [0.974, 0.0071, 0.2266], "f_px": 615},
                           "side": {"eye": [-0.5078, 0.0019, 0.1471], "focus": [-0.0082, -0.0166, 0.1445],
                                    "up": [0.0061, 0.0257, 0.9997], "f_px": 950}}}

Absent, nothing is drawn. Reads only.
"""
from __future__ import annotations

import math

import numpy as np

HALF_PX = {"top": 70, "side": 90}  # about 6 cm around the tip in the top view, 5 cm in the side view (640 x 480)


def to_cell(tcp, base: dict) -> np.ndarray:
    """Arm frame (m, FK zero on the plate) -> the surveyed frame (m)."""
    x, y, z = tcp
    yaw = math.radians(base["yaw_deg"])
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([base["xy"][0] + c * x - s * y, base["xy"][1] + s * x + c * y, base["z"] + z])


def project(camera: dict, point, size=(640, 480)) -> tuple[float, float]:
    """Pinhole with the principal point at the centre, as learning/envs/isaac/test/test_container_stack.py."""
    eye = np.asarray(camera["eye"], float)
    forward = np.asarray(camera["focus"], float) - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, camera["up"])
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    d = np.asarray(point, float) - eye
    return size[0] / 2 + camera["f_px"] * d @ right / (d @ forward), size[1] / 2 + camera["f_px"] * d @ down / (d @ forward)


def crop(frame, uv, half: int):
    """2*half square centred on uv, padded black past the edge, the tip circled."""
    import cv2

    u, v = (int(round(c)) for c in uv)
    out = cv2.copyMakeBorder(frame, half, half, half, half, cv2.BORDER_CONSTANT)[v:v + 2 * half, u:u + 2 * half].copy()
    cv2.circle(out, (half, half), 5, (0, 255, 255), 1)
    return out


def fk_tip(state) -> tuple:
    """The jaw tip (m, arm frame) of joint state units, with the session's TCP (ROSY_OMX_TCP_X_M)."""
    from grasp_planner import load_kinematics, norm_to_rad

    kin, _, _ = load_kinematics(None)
    p = kin.fk([norm_to_rad(v) for v in state[:5]])
    return float(p.x), float(p.y), float(p.z)


def tip_crops(frames: dict, tcp, spec: dict) -> dict:
    """camera -> crop around the projected tip, for the cameras with both a frame and a surveyed pose."""
    point = to_cell(tcp, spec["base"])
    out = {}
    for name, camera in spec["cameras"].items():
        frame = frames.get(name)
        if frame is not None:
            h, w = frame.shape[:2]
            out[name] = crop(frame, project(camera, point, (w, h)), HALF_PX.get(name, 80))
    return out
