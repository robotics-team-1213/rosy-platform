"""Forward model shared by the OMX joint-zero plan and fit: FK to a gripper marker's corners, seen by the top camera.

Offline only: nothing here talks to an arm. Units: joints in the cell's `.pos` unit ("norm", x1.8 = degrees) or degrees;
FK in mm in link0 (z_profile.py); the cell calibration record (cell_frame) is in metres in the arm frame, taken equal to
link0 plus `origin_mm` (UNVERIFIED: the sim assumed 0).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[2] / "deploy/robot/omx"))
from omx_zero_fit import (JOINT_RANGE_DEG, PRIOR_DEG, PRIOR_SIGMA_DEG, TABLE_PRIOR_MM,  # noqa: E402,F401
                          TABLE_SIGMA_MM)
import cell_frame as cf  # noqa: E402

JOINTS = ("shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos")
NORM_DEG = 1.8  # z_profile unit="norm"
WRIST_CAM_MM = np.array([36.24, 0.0, 45.84])  # z_profile wrist_cam_rel_link5
# (up edge, left edge, normal) of the marker in the link5 frame; up x left = normal (viewed from the normal's side)
_FACES = {"+z": ("x", "y"), "-z": ("x", "-y"), "-x": ("z", "y"), "+x": ("z", "-y"), "+y": ("z", "x"), "-y": ("x", "z")}
_AX = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}


def _vec(s):
    return (-1 if s.startswith("-") else 1) * np.array(_AX[s.lstrip("-")], float)


def to_deg(q, unit):
    return np.asarray(q, float) * (NORM_DEG if unit == "norm" else 1.0)


def _ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def link5_pose(q_deg, zero_deg, table_mm=0.0):
    """(origin mm, rotation) of link5. Same chain as z_profile.fk_landmarks_mm (a test pins them) but unrounded."""
    q = np.radians(np.asarray(q_deg, float) - np.asarray(zero_deg, float))
    p, r = np.array([-11.25, 0.0, 34.0 + table_mm]), _rz(q[0])
    p, r = p + r @ [0.0, 0.0, 63.5], r @ _ry(q[1])
    p, r = p + r @ [41.5, 0.0, 113.15], r @ _ry(q[2])
    p, r = p + r @ [162.0, 0.0, 0.0], r @ _ry(q[3])
    p, r = p + r @ [28.7, 0.0, 0.0], r @ _rx(q[4])
    return p, r


def tcp_z_mm(q_deg, zero_deg, table_mm, tcp_x_mm=74.1):
    p, r = link5_pose(q_deg, zero_deg, table_mm)
    return float((p + r @ [tcp_x_mm, 0.0, 0.0])[2])


@dataclass(frozen=True)
class Marker:
    id: int
    size_mm: float
    centre_mm: tuple  # marker centre in the link5 frame (MEASURE it: ruler from joint 5)
    normal: str = "+z"  # which link5 face carries it
    yaw_deg: float = 0.0  # turn of the print about its normal

    def local_corners(self):
        """The 4 corners (OpenCV order TL, TR, BR, BL as seen looking at the face) in the link5 frame, mm."""
        up, left = (_vec(s) for s in _FACES[self.normal])
        h, y = self.size_mm / 2, np.radians(self.yaw_deg)
        up, left = np.cos(y) * up + np.sin(y) * left, np.cos(y) * left - np.sin(y) * up
        return np.array(self.centre_mm, float) + h * np.array([up + left, up - left, -up - left, -up + left])

    def normal_local(self):
        return np.cross(*(_vec(s) for s in _FACES[self.normal]))


def marker_points_mm(q_deg, zero_deg, marker, table_mm=0.0):
    p, r = link5_pose(q_deg, zero_deg, table_mm)
    return p + marker.local_corners() @ r.T


def pixels(points_mm, record, camera, origin_mm=(0.0, 0.0, 0.0)):
    """Pixels of mm FK points in the calibration record's camera (`camera` = (R, t) camera in base, metres)."""
    pts = (np.asarray(points_mm, float) + np.asarray(origin_mm, float)) / 1000.0
    return np.array([cf.project(p, record["K"], record["dist"], camera) for p in pts])


def camera_of(record):
    cb = record["camera_in_base"]
    return np.asarray(cb["R"], float), np.asarray(cb["t"], float)


def view_ok(q_deg, zero_deg, marker, record, origin_mm=(0.0, 0.0, 0.0), margin_px=25, max_tilt_deg=55.0,
            min_z_mm=30.0, tcp_x_mm=74.1):
    """The marker's four corners are on the sensor, facing the camera within max_tilt, the tool above the table."""
    p5, r = link5_pose(q_deg, zero_deg)
    pts = p5 + marker.local_corners() @ r.T
    low = [pts[:, 2].min(), p5[2], (p5 + r @ [tcp_x_mm, 0, 0])[2], (p5 + r @ WRIST_CAM_MM)[2]]
    if min(low) < min_z_mm:
        return False
    cam = camera_of(record)
    c_arm = pts.mean(0) + np.asarray(origin_mm)
    to_cam = cam[1] * 1000.0 - c_arm
    if (r @ marker.normal_local()) @ to_cam / np.linalg.norm(to_cam) < np.cos(np.radians(max_tilt_deg)):
        return False
    if (c_arm / 1000.0 - cam[1]) @ cam[0][:, 2] < 0.05:  # behind or on the lens
        return False
    w, h = record["size"]
    uv = pixels(pts, record, cam, origin_mm)
    return bool((uv[:, 0] > margin_px).all() and (uv[:, 0] < w - margin_px).all()
                and (uv[:, 1] > margin_px).all() and (uv[:, 1] < h - margin_px).all())
