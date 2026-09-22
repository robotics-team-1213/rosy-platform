"""Shared lane-following simulation for host tests: inverse-projection
renderer over a 1 mm floor raster, CORE line_follow law mirror, closed loop.

Moved verbatim from test_lane_edge.py so every lane test drives the same
simulated camera; see that file's module docstring for the measured grey
levels behind FLOOR, BODY and the paint dimming fit.
"""

import importlib.util
import math
from pathlib import Path

import cv2
import numpy as np

from control.sensing.camera_ground import simulation_ground_plane

ROOT = Path(__file__).resolve().parents[1]
H = 0.0925
LW = 0.025
CAM_X = 0.034
W, HT = 320, 180
FLOOR, BODY = 109, 218
DT = 0.2
KW = dict(bright_threshold=180, lane_half_width_m=H,
          roi_top_fraction=0.25, roi_bottom_fraction=0.75, washed_fraction=0.75)

GROUND = simulation_ground_plane(
    source="GAZEBO", simulation_enabled=True, use_sim_time=True,
    width_px=W, height_px=HT, height_m=0.060194,
    pitch_rad=math.radians(25.0), hfov_rad=1.1519, max_range_m=0.6)

_FWD = np.full((HT, W), np.nan)
_LAT = np.full((HT, W), np.nan)
for _r in range(HT):
    _d = GROUND.distance(_r)
    if _d is not None:
        _FWD[_r, :] = _d
        _LAT[_r, :] = [GROUND.lateral(_c, _r) for _c in range(W)]


class World:
    """Floor paint on a 1 mm raster; world x right, y up (ROS odom frame)."""

    def __init__(self, x0=-1.5, x1=1.5, y0=-1.0, y1=1.0):
        self.x0, self.y1 = x0, y1
        self.paint = np.zeros((int(round((y1 - y0) * 1000)), int(round((x1 - x0) * 1000))),
                              np.uint8)

    def px(self, points):
        pts = np.asarray(points, float)
        return np.stack([(pts[:, 0] - self.x0) * 1000, (self.y1 - pts[:, 1]) * 1000], axis=1)

    def line(self, points, width=LW):
        pts = np.rint(self.px(points) * 16).astype(np.int32)
        cv2.polylines(self.paint, [pts], False, 255, int(round(width * 1000)),
                      lineType=cv2.LINE_8, shift=4)
        return self

    def rect(self, cx, cy, sx, sy):
        corners = [(cx - sx / 2, cy - sy / 2), (cx + sx / 2, cy - sy / 2),
                   (cx + sx / 2, cy + sy / 2), (cx - sx / 2, cy + sy / 2)]
        cv2.fillPoly(self.paint, [np.rint(self.px(corners) * 16).astype(np.int32)], 255,
                     shift=4)
        return self

    def render(self, pose):
        x, y, yaw = pose
        forward = _FWD + CAM_X
        left = -_LAT
        wx = x + forward * math.cos(yaw) - left * math.sin(yaw)
        wy = y + forward * math.sin(yaw) + left * math.cos(yaw)
        valid = np.isfinite(wx)
        col = np.where(valid, np.rint((wx - self.x0) * 1000), -1).astype(int)
        row = np.where(valid, np.rint((self.y1 - wy) * 1000), -1).astype(int)
        inside = valid & (col >= 0) & (row >= 0) & (col < self.paint.shape[1]) \
            & (row < self.paint.shape[0])
        frame = np.full((HT, W), FLOOR, np.uint8)
        painted = np.zeros((HT, W), bool)
        painted[inside] = self.paint[row[inside], col[inside]] > 0
        frame[painted] = np.clip(np.rint(229.0 - 35.0 * _FWD[painted]), 0, 255)
        frame[139:, :] = BODY
        return frame


def offset_polyline(points, distance):
    """Left offset (+) of a polyline with mitred joints, like the track paint."""
    pts = np.asarray(points, float)
    d = np.diff(pts, axis=0)
    d /= np.linalg.norm(d, axis=1)[:, None]
    n = np.stack([-d[:, 1], d[:, 0]], axis=1)
    out = [pts[0] + distance * n[0]]
    for k in range(1, len(pts) - 1):
        m = n[k - 1] + n[k]
        m /= np.linalg.norm(m)
        out.append(pts[k] + distance * m / float(np.dot(m, n[k])))
    out.append(pts[-1] + distance * n[-1])
    return np.array(out)


def lane(centreline):
    world = World()
    world.line(offset_polyline(centreline, H)).line(offset_polyline(centreline, -H))
    return world


def core_command(obs):
    """CORE line_follow tick(): min_confidence 0.35, cruise 0.08, gain 0.8."""
    if obs is None or obs.confidence < 0.35:
        return 0.0, 0.0
    scale = max(0.0, min(1.0, (obs.confidence - 0.35) / 0.65))
    linear = 0.08 * scale * max(0.2, 1.0 - 0.65 * abs(obs.error))
    angular = max(-0.7, min(0.7, -0.8 * obs.error))
    return linear, angular


def drive(world, follower, *, steps, pose=(0.0, 0.0, 0.0), odom=True, stop=None):
    log = []
    for k in range(steps):
        obs = follower.update(k * DT, pose if odom else None, world.render(pose), GROUND, **KW)
        log.append((pose, obs, follower.state))
        v, w = core_command(obs)
        mid = pose[2] + w * DT / 2.0
        pose = (pose[0] + v * DT * math.cos(mid), pose[1] + v * DT * math.sin(mid),
                pose[2] + w * DT)
        if stop is not None and stop(pose, k):
            break
    return log, pose


def distance_to_polyline(point, polyline):
    p = np.asarray(point, float)
    best = math.inf
    for a, b in zip(polyline[:-1], polyline[1:]):
        ab = b - a
        t = max(0.0, min(1.0, float(np.dot(p - a, ab) / np.dot(ab, ab))))
        best = min(best, float(np.linalg.norm(p - (a + t * ab))))
    return best


def stl_world():
    path = ROOT / "map" / "map_v2_fleet" / "scripts" / "stl_scene.py"
    spec = importlib.util.spec_from_file_location("stl_scene_for_lane_sim", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scene = module.load_scene(next((ROOT / "map" / "map_v2_fleet").glob("260919*.STL")))
    world = World(-1.405, 1.405, -0.63, 0.63)
    for triangle in scene.lines:
        corners = np.rint(world.px([v[:2] for v in triangle]) * 16).astype(np.int32)
        cv2.fillPoly(world.paint, [corners], 255, shift=4)
    return world


START = (-1.26955, 0.24255, -math.pi / 2)
