"""Subject: dock tag detection — ArUco marker to robot-frame relative pose.

A dock carries one ArUco tag (``DICT_4X4_50``, side recorded in the dock-type
entry per DNC-007). This subject turns a BGR frame into a single relative
pose; it never decides whether the robot may move.

Without a :class:`CameraMount` the pose is camera-frame range with a bearing
yaw (the DNC-007 contract). With one, the camera's pitch and offset are
applied and the pose is the tag centre in base_link plus the yaw of the
tag's inward axis (from rvec: the face normal reversed, projected on the
floor), 0 when the robot squarely faces the tag. That is the stage-3
parking wedge's contract (docs/plans/2026-09-23-lane-network-parking-design.md). An unknown tag id or a
missing tag is None, never a guess — a lost dock must read as lost (DNC-004).

ROS-free: same contract for the onboard node and a deterministic fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np


_DICTIONARY = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_PARAMETERS = cv2.aruco.DetectorParameters()
# Sub-pixel corners: the parking tag is ~50 px wide at its stop range and a
# yaw from rvec needs its corners to a fraction of a pixel.
_PARAMETERS.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX


@dataclass(frozen=True)
class CameraMount:
    """Camera extrinsics on base_link: the optical centre `height_m` above
    the floor and `x_offset_m` ahead of base_link, pitched `pitch_rad` down.
    No roll and no yaw (the Pinky and Gazebo mounts have neither)."""

    height_m: float
    pitch_rad: float
    x_offset_m: float = 0.0

    def __post_init__(self) -> None:
        values = (self.height_m, self.pitch_rad, self.x_offset_m)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError("camera mount values must be finite numbers")
        if not self.height_m > 0:
            raise ValueError("height_m must be positive")

    def rotation(self) -> np.ndarray:
        """Columns: the optical frame's x right, y down, z forward in base_link."""
        s, c = math.sin(self.pitch_rad), math.cos(self.pitch_rad)
        return np.array([[0.0, -s, c], [-1.0, 0.0, 0.0], [0.0, -c, -s]])


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
                    dist_coeffs: np.ndarray,
                    mount: CameraMount | None = None) -> DockTagObservation | None:
    """Detect our tag and solve its relative pose, or None when absent/foreign.
    `mount` switches to the base_link contract (module docstring)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    detector = cv2.aruco.ArucoDetector(_DICTIONARY, _PARAMETERS)
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return None
    match = next((c for c, i in zip(corners, ids.flatten()) if int(i) == spec.tag_id), None)
    if match is None:
        return None
    half = float(spec.size_m) / 2.0
    # Tag frame (IPPE_SQUARE order): x right, y up, z out of the tag toward
    # the camera.
    obj = np.array([[-half, half, 0.0], [half, half, 0.0],
                    [half, -half, 0.0], [-half, -half, 0.0]])
    if mount is not None:
        return _mounted_pose(obj, match, spec, camera_matrix, dist_coeffs, mount)
    ok, rvec, tvec = cv2.solvePnP(
        obj, match.reshape(4, 2).astype(np.float64),
        camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        return None
    tx, _, tz = (float(v) for v in tvec.flatten())
    confidence = _confidence(obj, rvec, tvec, match, camera_matrix, dist_coeffs)
    # Camera x-right/z-forward to robot x-forward/y-left; bearing CCW-positive.
    x, y = tz, -tx
    return DockTagObservation(tag_id=spec.tag_id, x=x, y=y,
                              yaw=math.atan2(-tx, tz),
                              range_m=math.hypot(x, y),
                              revision=spec.revision,
                              confidence=confidence)


def _confidence(obj, rvec, tvec, match, camera_matrix, dist_coeffs) -> float:
    """Reprojection error maps to confidence: a perfect fit is 1.0, a fit
    several pixels off decays toward 0. A warped or half-hidden tag reads
    as unsure, never as a confident wrong pose."""
    projected, _ = cv2.projectPoints(obj, rvec, tvec, camera_matrix, dist_coeffs)
    err_px = float(np.mean(np.linalg.norm(
        projected.reshape(4, 2) - match.reshape(4, 2).astype(np.float64), axis=1)))
    return 1.0 / (1.0 + err_px)


def _mounted_pose(obj, match, spec, camera_matrix, dist_coeffs,
                  mount: CameraMount) -> DockTagObservation | None:
    """Tag centre in base_link and the yaw of its inward axis.

    IPPE_SQUARE has two solutions for a small oblique square; the flipped
    one tilts the face normal down into the floor (measured on the
    rendered wedge: -41 to -49 deg against the true +65). A tag stands on
    the floor facing up, so only solutions whose normal points up are
    kept, and of those the lower reprojection error wins."""
    image = match.reshape(4, 2).astype(np.float64)
    try:
        count, rvecs, tvecs, errors = cv2.solvePnPGeneric(
            obj, image, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    except cv2.error:
        return None
    rotation = mount.rotation()
    offset = np.array([mount.x_offset_m, 0.0, mount.height_m])
    best = None
    for rvec, tvec, error in zip(rvecs[:count], tvecs[:count], errors[:count]):
        normal = rotation @ cv2.Rodrigues(rvec)[0][:, 2]
        if normal[2] <= 0.0:
            continue
        if best is None or float(error[0]) < best[0]:
            best = (float(error[0]), rvec, tvec, normal)
    if best is None:
        return None
    _, rvec, tvec, normal = best
    centre = rotation @ np.asarray(tvec, float).reshape(3) + offset
    x, y = float(centre[0]), float(centre[1])
    return DockTagObservation(
        tag_id=spec.tag_id, x=x, y=y,
        yaw=math.atan2(-float(normal[1]), -float(normal[0])),
        range_m=math.hypot(x, y), revision=spec.revision,
        confidence=_confidence(obj, rvec, tvec, match, camera_matrix, dist_coeffs))
