"""D-379 auto-label geometry: NOMINAL camera, LiDAR mount, planar poses.

Frames (all metres, radians):
  base   base_footprint on the floor: x forward, y left, z up.
  odom   the odometry frame; a pose is (x, y, yaw) of base in odom.
  camera pinhole at (x_offset_m, 0, height_m) in base, pitched down by pitch_rad;
         image column grows to the right (-y), image row grows downwards.

The camera numbers come from the NOMINAL profile (D-364 section 3,
src/products/pinky_pro/profile/config/camera_nominal.yaml). The LiDAR mount comes
from the sim URDF (src/sim/description/urdf/rosy.urdf.xacro): base_footprint ->
base_link z 0.028, base_link -> rplidar_mount xyz (-0.017, 0, 0.067),
rplidar_mount -> rplidar_link z 0.030 and yaw pi, so the scan plane is 0.125 m
above the floor, 0.017 m behind base, and scan angle 0 points backwards. The real
Pinky Pro agrees on the yaw (lidar_forward_deg 180; src/hmi/pilot/logs.md: front
2.6 m and right wall 0.14 m matched the camera). The height is the URDF value,
not a tape measurement of the real robot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
PROFILE_PATH = REPO / "src" / "products" / "pinky_pro" / "profile" / "config" / "camera_nominal.yaml"

# rosy.urdf.xacro: 0.028 + 0.067 + 0.030; x of rplidar_mount in base_link.
LIDAR_HEIGHT_M = 0.125
LIDAR_X_OFFSET_M = -0.017
LIDAR_FORWARD_DEG = 180.0
# Track perimeter and inner walls: 0.155 m (map_260905.world, and the video
# estimate in docs/validation/perception-real-video/2026-09-24/p0_track_measurements.md).
WALL_HEIGHT_M = 0.155


@dataclass(frozen=True)
class Camera:
    width: int
    height: int
    fx: float
    cx: float
    cy: float
    pitch_rad: float
    height_m: float
    x_offset_m: float

    @classmethod
    def from_profile(cls, path=PROFILE_PATH, width: int | None = None, height: int | None = None):
        import yaml
        p = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        scale = 1.0 if width is None else float(width) / float(p["width"])
        if height is not None and abs(float(height) / float(p["height"]) - scale) > 0.01 * scale:
            raise ValueError(f"frame {width}x{height} does not match the profile aspect")
        return cls(int(round(p["width"] * scale)), int(round(p["height"] * scale)),
                   float(p["fx"]) * scale, float(p["cx"]) * scale, float(p["cy"]) * scale,
                   float(p["pitch_rad"]), float(p["height_m"]), float(p.get("x_offset_m", 0.0)))

    @property
    def horizon_row(self) -> float:
        return self.cy - self.fx * math.tan(self.pitch_rad)

    def project(self, pts) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(N,3) base-frame points -> (u, v, depth). depth <= 0 is behind the lens."""
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        dx = pts[:, 0] - self.x_offset_m
        dy = pts[:, 1]
        dz = pts[:, 2] - self.height_m
        s, c = math.sin(self.pitch_rad), math.cos(self.pitch_rad)
        depth = dx * c - dz * s
        up = dx * s + dz * c
        with np.errstate(divide="ignore", invalid="ignore"):
            u = self.cx - self.fx * dy / depth
            v = self.cy - self.fx * up / depth
        return u, v, depth

    def ground_row(self, forward_m: float) -> float:
        """Image row of a floor point straight ahead of base at forward_m."""
        _, v, _ = self.project([[forward_m, 0.0, 0.0]])
        return float(v[0])


@dataclass(frozen=True)
class Lidar:
    height_m: float = LIDAR_HEIGHT_M
    x_offset_m: float = LIDAR_X_OFFSET_M
    forward_deg: float = LIDAR_FORWARD_DEG
    mirrored: bool = False  # True if the driver reports angles clockwise

    def points(self, ranges, angle_min: float, angle_increment: float,
               range_min: float, range_max: float, max_range: float | None = None):
        """Scan -> ((N,2) base-frame xy of valid returns, (N,) ranges, (N,) scan index)."""
        r = np.asarray(ranges, dtype=np.float64)
        idx = np.arange(r.size)
        hi = range_max if max_range is None else min(range_max, max_range)
        ok = np.isfinite(r) & (r >= max(range_min, 1e-3)) & (r <= hi)
        a = angle_min + idx * angle_increment
        if self.mirrored:
            a = -a
        a = a - math.radians(self.forward_deg)
        x = r * np.cos(a) + self.x_offset_m
        y = r * np.sin(a)
        return np.stack([x[ok], y[ok]], axis=1), r[ok], idx[ok]


# --- planar poses ---------------------------------------------------------

def wrap(a):
    return (np.asarray(a) + np.pi) % (2 * np.pi) - np.pi


class PoseSeries:
    """Odometry poses sorted by time; linear interpolation (yaw unwrapped)."""

    def __init__(self, t, x, y, yaw):
        order = np.argsort(np.asarray(t, dtype=np.float64))
        self.t = np.asarray(t, dtype=np.float64)[order]
        self.x = np.asarray(x, dtype=np.float64)[order]
        self.y = np.asarray(y, dtype=np.float64)[order]
        self.yaw = np.unwrap(np.asarray(yaw, dtype=np.float64)[order])

    def __len__(self):
        return int(self.t.size)

    def at(self, t: float, max_gap: float = 0.25):
        """(x, y, yaw) at t, or None outside the series or across a gap > max_gap."""
        if self.t.size == 0 or t < self.t[0] or t > self.t[-1]:
            return None
        i = int(np.searchsorted(self.t, t))
        if i == 0:
            return float(self.x[0]), float(self.y[0]), float(self.yaw[0])
        t0, t1 = self.t[i - 1], self.t[i]
        if t1 - t0 > max_gap:
            return None
        w = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
        return (float(self.x[i - 1] + w * (self.x[i] - self.x[i - 1])),
                float(self.y[i - 1] + w * (self.y[i] - self.y[i - 1])),
                float(self.yaw[i - 1] + w * (self.yaw[i] - self.yaw[i - 1])))

    def window(self, t0: float, t1: float):
        """Poses with t0 <= t <= t1 as (t, x, y, yaw) arrays."""
        a, b = np.searchsorted(self.t, t0), np.searchsorted(self.t, t1, side="right")
        return self.t[a:b], self.x[a:b], self.y[a:b], self.yaw[a:b]


def to_frame(pose_from, pose_to, xy):
    """xy points given in the base frame at pose_from -> base frame at pose_to."""
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    x0, y0, a0 = pose_from
    c0, s0 = math.cos(a0), math.sin(a0)
    wx = x0 + c0 * xy[:, 0] - s0 * xy[:, 1]
    wy = y0 + s0 * xy[:, 0] + c0 * xy[:, 1]
    return world_to_base(pose_to, np.stack([wx, wy], axis=1))


def world_to_base(pose, xy):
    x1, y1, a1 = pose
    c1, s1 = math.cos(a1), math.sin(a1)
    dx, dy = xy[:, 0] - x1, xy[:, 1] - y1
    return np.stack([c1 * dx + s1 * dy, -s1 * dx + c1 * dy], axis=1)
