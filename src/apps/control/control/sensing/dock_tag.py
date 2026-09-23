"""Subject: dock tag detection — ArUco marker to robot-frame relative pose.

A dock carries one ArUco tag (``DICT_4X4_50``, side recorded in the dock-type
entry per DNC-007). This subject turns a BGR frame into a single relative
pose; it never decides whether the robot may move. An unknown tag id or a
missing tag is None, never a guess — a lost dock must read as lost (DNC-004).

ROS-free: same contract for the onboard node and a deterministic fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np


_DICTIONARY = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def _detect_markers(gray: np.ndarray):
    """(corners, ids, rejected) on either side of the OpenCV 4.7 ArUco API split.

    The device image takes OpenCV from Ubuntu 24.04's `python3-opencv`, which
    is 4.6: it has only the module-level `cv2.aruco.detectMarkers`. OpenCV 4.7
    added `ArucoDetector`, and later releases (5.x on the dev host) dropped the
    module-level call. Choose by what exists rather than catching
    `AttributeError`, so a genuine error inside detection is not mistaken for a
    missing API.
    """
    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = cv2.aruco.ArucoDetector(_DICTIONARY, cv2.aruco.DetectorParameters())
        return detector.detectMarkers(gray)
    return cv2.aruco.detectMarkers(gray, _DICTIONARY)


@dataclass(frozen=True)
class DockTagSpec:
    """Immutable tag contract. Size comes from the dock-type entry (DNC-005);
    without it there is no pose (SRS: fail-closed)."""

    tag_id: int
    size_m: float
    revision: str = "dock-tag-v1"

    def __post_init__(self) -> None:
        if type(self.tag_id) is not int or self.tag_id < 0:
            raise ValueError("tag_id must be a non-negative integer")
        if not isinstance(self.size_m, (int, float)) or not self.size_m > 0:
            raise ValueError("size_m must be positive")
        if not self.revision:
            raise ValueError("revision must be non-empty")


@dataclass(frozen=True)
class DockTagObservation:
    """Robot-frame relative pose. x forward, y left, yaw CCW — the same frame
    the docking state machine drives in (DNC-002)."""

    tag_id: int
    x: float
    y: float
    yaw: float
    range_m: float
    revision: str
    confidence: float = 1.0   # reprojection-based; 1.0 is a perfect fit
    at: float = 0.0           # capture clock; the lifecycle wrapper stamps it


def detect_dock_tag(bgr: np.ndarray, spec: DockTagSpec,
                    camera_matrix: np.ndarray,
                    dist_coeffs: np.ndarray) -> DockTagObservation | None:
    """Detect our tag and solve its relative pose, or None when absent/foreign."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    corners, ids, _ = _detect_markers(gray)
    if ids is None:
        return None
    match = next((c for c, i in zip(corners, ids.flatten()) if int(i) == spec.tag_id), None)
    if match is None:
        return None
    half = float(spec.size_m) / 2.0
    # Tag frame: x right, y down, z out of the tag toward the camera.
    obj = np.array([[-half, half, 0.0], [half, half, 0.0],
                    [half, -half, 0.0], [-half, -half, 0.0]])
    ok, rvec, tvec = cv2.solvePnP(
        obj, match.reshape(4, 2).astype(np.float64),
        camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        return None
    tx, _, tz = (float(v) for v in tvec.flatten())
    # Reprojection error maps to confidence: a perfect fit is 1.0, a fit
    # several pixels off decays toward 0. A warped or half-hidden tag reads
    # as unsure, never as a confident wrong pose.
    projected, _ = cv2.projectPoints(obj, rvec, tvec, camera_matrix, dist_coeffs)
    err_px = float(np.mean(np.linalg.norm(
        projected.reshape(4, 2) - match.reshape(4, 2).astype(np.float64), axis=1)))
    confidence = 1.0 / (1.0 + err_px)
    # Camera x-right/z-forward to robot x-forward/y-left; bearing CCW-positive.
    x, y = tz, -tx
    return DockTagObservation(tag_id=spec.tag_id, x=x, y=y,
                              yaw=math.atan2(-tx, tz),
                              range_m=math.hypot(x, y),
                              revision=spec.revision,
                              confidence=confidence)
