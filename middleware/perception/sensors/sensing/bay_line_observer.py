"""Subject: the charge-bay pink guide line as the virtual dock (D-1013).

ROS-free. Given one camera frame this turns the magenta guide tape into the
``dock/observation`` payload the docking manager's ``approach="line"`` phases
consume: the line is the dock — ``x`` is the along distance to the stop face,
``y`` the line's lateral offset in base_link, ``yaw`` the bay inward axis.

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

#: HSV bounds for magenta guide tape (OpenCV H 140-170, S >= 80, V >= 60).
PINK_HSV_LOW = (140, 80, 60)
PINK_HSV_HIGH = (170, 255, 255)
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

    def _payload(self, stamp: float, visible: bool, **fields) -> dict:
        body = {"source": "CAMERA_LINE", "visible": visible, "stamp": float(stamp),
                "tag_id": None}
        body.update(fields)
        return body

    def observe(self, frame: np.ndarray, stamp: float) -> dict:
        hrow = horizon_row(self._w, self._h, self._hfov, self._mount.pitch_rad,
                           self._mount.height_m)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        raw = cv2.inRange(hsv, PINK_HSV_LOW, PINK_HSV_HIGH)
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
        pts = np.asarray(points, dtype=np.float64)
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
        # Points are base_link; the camera sits x_offset ahead, so the
        # camera->end distance is the point's x minus that offset.
        south_base = float(south[0])
        d_south = south_base - self._mount.x_offset_m
        measured = d_south <= self._far_field_m - 0.02
        if not measured:
            # The end has left the view: the longitudinal signal is gone; the
            # saturated value stays finite for rear_errors, flagged not measured.
            south_base = self._far_field_m + self._mount.x_offset_m
        x = self._line_total_m - south_base
        return self._payload(
            stamp, True, x=float(x), y=float(foot[1]), yaw=float(yaw),
            confidence=min(1.0, len(xs) / CONFIDENCE_PIXELS),
            along_measured=bool(measured))
