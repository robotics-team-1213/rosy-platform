"""Subject: the charge-bay pink guide line as the virtual dock (D-1013).

ROS-free. Given one camera frame this turns the magenta guide tape into the
``dock/observation`` payload the docking manager's ``approach="line"`` phases
consume: the line is the dock — ``(x, y)`` is the stop-face centre in base_link (behind the
robot, so x < 0; CORE's rear_errors reads along/lateral from it), ``yaw`` the bay inward axis.

Ground geometry is declared, not calibrated: only the Gazebo camera
(``camera_geometry_source`` GAZEBO under ``use_sim_time``) may project; the
node fails closed otherwise (the adapter's job). The along distance is
measured from the line's far (south, corridor-side) end plus the site constant
``line_total_m`` (stop face -> south end, unmeasured design value): past
``far_field_m`` that end leaves the view and ``along_measured`` is false — the
longitudinal signal is gone (bay_pit_sim: the last stretch keeps only the
distance cap), the lateral and heading stay valid for steering.

No motion output here. CORE stays the sole final ``cmd_vel`` publisher (D-2).
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from core_common.calibration_store import read_floor_paint_gate

HORIZON_MARGIN_PX = 3
MIN_COMPONENT_AREA_PX = 40
#: The mask must paint at least this many pixels before the line exists.
MIN_MASK_PIXELS = 60
#: Confidence saturates at this many mask pixels (a tape-width line at 0.3 m).
CONFIDENCE_PIXELS = 400.0


def _project(width: int, height: int, hfov_rad: float, pitch_rad: float, height_m: float):
    """(f_px, u0, v0): pinhole pieces for a down-tilted camera on the floor."""
    f = (width / 2.0) / math.tan(hfov_rad / 2.0)
    return f, width / 2.0, height / 2.0


def pixel_to_ground(u: float, v: float, *, width: int, height: int,
                    hfov_rad: float, pitch_rad: float, height_m: float):
    """One image pixel to base_link ground metres (x ahead, y left), or None
    when the ray does not reach the floor below the horizon."""
    f, u0, v0 = _project(width, height, hfov_rad, pitch_rad, height_m)
    delta = pitch_rad + math.atan((v - v0) / f)
    if delta <= 1e-4:
        return None
    ahead = height_m / math.tan(delta)
    return ahead, ahead * (u0 - u) / f


def horizon_row(width: int, height: int, hfov_rad: float, pitch_rad: float,
                height_m: float) -> float:
    f, _, v0 = _project(width, height, hfov_rad, pitch_rad, height_m)
    return v0 - f * math.tan(pitch_rad)


def ground_to_pixel(x_ahead: float, y_left: float, *, width: int, height: int,
                    hfov_rad: float, pitch_rad: float, height_m: float):
    """base_link ground metres to the pixel seeing them (the test renderer)."""
    f, u0, v0 = _project(width, height, hfov_rad, pitch_rad, height_m)
    delta = math.atan2(height_m, x_ahead)
    alpha = delta - pitch_rad
    if abs(alpha) >= math.pi / 2:
        return None
    v = v0 + f * math.tan(alpha)
    u = u0 - f * y_left / x_ahead
    if not (0.0 <= v < height and 0.0 <= u < width):
        return None
    return u, v


#: Ahead of a bay the camera sees the bay's own line and the corridor line across it (an L or a T).
#: Only a line within this angle of the robot's axis can be the bay line being reversed along.
AXIAL_MAX_RAD = math.radians(35.0)
#: A ground point within this distance of the candidate line belongs to it (tape ~2 cm wide).
INLIER_M = 0.015


def _consensus(pts: np.ndarray, *, axial: bool):
    """Inliers of the straight line with the most support whose direction is near base_link x (axial) or
    near y (the corridor line across the bay), or None."""
    n = len(pts)
    rng = np.random.default_rng(7)
    best = None
    for _ in range(300):
        i, j = rng.integers(0, n, 2)
        d = pts[j] - pts[i]
        length = float(np.hypot(*d))
        if length < 0.04:
            continue
        off_x = math.atan2(abs(d[1]), abs(d[0]))
        if (off_x if axial else math.pi / 2 - off_x) > AXIAL_MAX_RAD:
            continue
        normal = np.array([-d[1], d[0]]) / length
        inliers = np.abs((pts - pts[i]) @ normal) <= INLIER_M
        if best is None or inliers.sum() > best.sum():
            best = inliers
    if best is None or best.sum() < MIN_MASK_PIXELS:
        return None
    return pts[best]


def axial_line(pts: np.ndarray):
    """The points of the one straight line nearest the robot's axis, or None.

    Fitting every pink pixel to one line averages the bay line with the corridor line (2026-11-18,
    y8xs: a steady but wrong 16 deg). Deterministic sample consensus; the most inliers wins."""
    return _consensus(pts, axial=True)


def nominal_geometry(profile: dict) -> tuple[dict, float, int, int]:
    """(mount fields, hfov_rad, width, height) from camera_nominal.yaml (D-364/D-397).

    The observer's pinhole assumes a centred principal point; a profile that says otherwise
    is refused rather than projected wrong."""
    width, height, fx = int(profile["width"]), int(profile["height"]), float(profile["fx"])
    if abs(float(profile["cx"]) - width / 2.0) > 1.0 or abs(float(profile["cy"]) - height / 2.0) > 1.0:
        raise ValueError("principal point is not centred")
    mount = {k: float(profile[k]) for k in ("height_m", "pitch_rad", "x_offset_m")}
    return mount, 2.0 * math.atan(width / 2.0 / fx), width, height


class BayLineObserver:
    """``observe(frame, stamp) -> dock/observation payload`` (CAMERA_LINE)."""

    def __init__(self, *, mount, hfov_rad: float, width: int, height: int,
                 line_total_m: float, far_field_m: float = 0.45):
        if not (0.0 < hfov_rad < math.pi):
            raise ValueError("hfov_rad must be in (0, pi)")
        if line_total_m <= far_field_m:
            raise ValueError("line_total_m must exceed far_field_m")
        if width <= 0 or height <= 0:
            raise ValueError("frame dimensions must be positive")
        self._mount = mount
        self._hfov = float(hfov_rad)
        self._w, self._h = int(width), int(height)
        self._line_total_m = float(line_total_m)
        self._far_field_m = float(far_field_m)
        self._pink_gate = read_floor_paint_gate()

    def _payload(self, stamp: float, visible: bool, **fields) -> dict:
        body = {"source": "CAMERA_LINE", "visible": visible, "stamp": float(stamp),
                "tag_id": None}
        body.update(fields)
        return body

    def _crossbar(self, cloud: np.ndarray, stamp: float, pixels: int) -> dict:
        """Only the corridor line across the bay mouth is in view (the robot's nose at or past the bay line's
        corridor end, 2026-11-18 y8xs). It gives the bay axis (its normal) and the distance to the bay mouth,
        not the lateral: the payload says so and CORE fills that from its estimate or the map."""
        bar = _consensus(cloud, axial=False)
        if bar is None:
            return self._payload(stamp, False)
        centre = bar.mean(axis=0)
        _, _, vt = np.linalg.svd(bar - centre, full_matrices=False)
        normal = np.array([-vt[0][1], vt[0][0]])
        if normal[0] > 0.0:
            normal = -normal                     # the bay inward axis points behind the robot
        mouth = float(np.dot(normal, centre) / normal[0])   # where base_link x meets the corridor line
        if mouth - self._mount.x_offset_m > self._far_field_m - 0.02:
            return self._payload(stamp, False)
        stop = np.array([mouth, 0.0]) + normal * self._line_total_m   # lateral is a placeholder here
        return self._payload(stamp, True, x=float(stop[0]), y=float(stop[1]),
                             yaw=float(math.atan2(normal[1], normal[0])),
                             confidence=min(1.0, pixels / CONFIDENCE_PIXELS),
                             along_measured=True, lateral_measured=False)

    def observe(self, frame: np.ndarray, stamp: float) -> dict:
        hrow = horizon_row(self._w, self._h, self._hfov, self._mount.pitch_rad,
                           self._mount.height_m)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        raw = cv2.inRange(hsv, *self._pink_gate)
        raw[:max(0, min(raw.shape[0], int(math.ceil(hrow)) + HORIZON_MARGIN_PX))] = 0
        count, labels, stats, _ = cv2.connectedComponentsWithStats(raw, connectivity=8)
        keep = np.zeros(count, bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= MIN_COMPONENT_AREA_PX
        ys, xs = np.nonzero(keep[labels])
        if len(xs) < MIN_MASK_PIXELS:
            return self._payload(stamp, False)
        points = []
        for u, v in zip(xs, ys):
            g = pixel_to_ground(float(u), float(v), width=self._w, height=self._h,
                                hfov_rad=self._hfov, pitch_rad=self._mount.pitch_rad,
                                height_m=self._mount.height_m)
            if g is not None:
                # pixel_to_ground is camera-relative; the camera sits x_offset
                # ahead of base_link, so a point is that much farther from base.
                points.append((g[0] + self._mount.x_offset_m, g[1]))
        if len(points) < MIN_MASK_PIXELS:
            return self._payload(stamp, False)
        cloud = np.asarray(points, dtype=np.float64)
        pts = axial_line(cloud)
        if pts is None:
            return self._crossbar(cloud, stamp, len(xs))
        centre = pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts - centre, full_matrices=False)
        direction = vt[0]
        # The bay is behind the robot (the camera looks at the corridor side).
        if direction[0] > 0.0:
            direction = -direction
        yaw = math.atan2(direction[1], direction[0])
        # The line's lateral offset at the robot's station: its closest point.
        foot = centre - float(np.dot(centre, direction)) * direction
        # The far (corridor-side) end: the visible extent along -direction.
        along = (pts - centre) @ direction
        south = centre + direction * float(along.min())
        measured = float(south[0]) - self._mount.x_offset_m <= self._far_field_m - 0.02
        if not measured:
            # The end has left the view: the longitudinal signal is gone; place it at the far field
            # on the line so the value stays finite, flagged not measured.
            reach = self._far_field_m + self._mount.x_offset_m
            south = foot + direction * ((reach - float(foot[0])) / float(direction[0]))
        # DockObservation is the stop-face centre in base_link (CORE's rear_errors reads it so): from the
        # corridor end, line_total along the line into the bay (2026-11-18: this was the bare distance).
        stop = south + direction * self._line_total_m
        return self._payload(
            stamp, True, x=float(stop[0]), y=float(stop[1]), yaw=float(yaw),
            confidence=min(1.0, len(xs) / CONFIDENCE_PIXELS),
            along_measured=bool(measured))
