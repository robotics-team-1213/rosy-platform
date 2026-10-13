"""Subject: move a learned paint mask from the frame it was made on to a later frame (D-570).

Paint lies on the floor, and odometry says how the robot moved between the two frame stamps,
so an older mask is re-projected through the ground plane instead of being thrown away:
pixel -> floor point (old base_link) -> new base_link -> pixel. Same pinhole as GroundPlane /
BirdsEye (pitch only, square pixels, lens `camera_x_offset_m` ahead of base_link). Floor that
the old frame did not see stays empty; nothing is invented. No odometry, or more motion than
the bounds allow, means no warp: the caller falls back.
"""

from __future__ import annotations

import bisect
import math
from collections import deque

import cv2
import numpy as np

#: Two odometry samples further apart than this bracket no pose (a dropped stream, not motion).
ODOM_HISTORY_MAX_GAP_S = 0.2
#: A frame stamp may run this far past the newest odometry sample (odom arrives after the
#: image); the pose is carried on at the last measured velocity, never further.
ODOM_HISTORY_MAX_LEAD_S = 0.1


class OdomHistory:
    """Bounded (stamp, x, y, yaw) odometry history; pose at any stamp inside it, interpolated."""

    def __init__(self, maxlen: int = 200):
        self._samples: deque = deque(maxlen=maxlen)

    def clear(self) -> None:
        self._samples.clear()

    def add(self, stamp: float, x: float, y: float, yaw: float) -> None:
        if self._samples and stamp <= self._samples[-1][0]:
            if stamp < self._samples[-1][0]:   # the odometry clock went back: an old history lies
                self._samples.clear()
            else:
                return
        self._samples.append((float(stamp), float(x), float(y), float(yaw)))

    def pose_at(self, stamp: float):
        """(x, y, yaw) at `stamp`, or None when the history does not cover it."""
        samples = list(self._samples)
        if len(samples) < 2 or not math.isfinite(stamp):
            return None
        stamps = [s[0] for s in samples]
        i = bisect.bisect_left(stamps, stamp)
        if i == 0:
            return samples[0][1:] if stamp == stamps[0] else None
        if i == len(samples):
            a, b = samples[-2], samples[-1]
            if stamp - b[0] > ODOM_HISTORY_MAX_LEAD_S:
                return None
        else:
            a, b = samples[i - 1], samples[i]
        if b[0] - a[0] > ODOM_HISTORY_MAX_GAP_S:
            return None
        f = (stamp - a[0]) / (b[0] - a[0])
        dyaw = math.remainder(b[3] - a[3], math.tau)
        return (a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]),
                math.remainder(a[3] + f * dyaw, math.tau))


def _ground_to_pixel(ground, camera_x_offset_m: float) -> np.ndarray:
    """3x3 homography from a floor point (x, y, 1) in base_link to a pixel (u, v, 1)."""
    s, c = math.sin(ground.pitch_rad), math.cos(ground.pitch_rad)
    h, x0 = ground.height_m, camera_x_offset_m
    # camera X right = -y; Y down = h cos p - (x - x0) sin p; Z forward = (x - x0) cos p + h sin p
    m = np.array([[0.0, -1.0, 0.0],
                  [-s, 0.0, h * c + x0 * s],
                  [c, 0.0, h * s - x0 * c]])
    k = np.array([[ground.focal_px, 0.0, ground.principal_x],
                  [0.0, ground.focal_px, ground.principal_y],
                  [0.0, 0.0, 1.0]])
    return k @ m


def _se2(pose) -> np.ndarray:
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s, x], [s, c, y], [0.0, 0.0, 1.0]])


def mask_homography(ground, camera_x_offset_m: float, pose_src, pose_dst, shape, horizon_cut_row: int,
                    *, max_dxy_m: float, max_dyaw_rad: float):
    """(H old pixel -> new pixel, |dxy| m, dyaw rad), or 'motion_bound' when the motion between
    the two odometry poses is past the bounds or puts the new view's floor behind the old lens."""
    move = np.linalg.inv(_se2(pose_dst)) @ _se2(pose_src)        # old base_link -> new base_link
    dxy = math.hypot(pose_dst[0] - pose_src[0], pose_dst[1] - pose_src[1])
    dyaw = math.remainder(pose_dst[2] - pose_src[2], math.tau)
    if not (dxy <= max_dxy_m and abs(dyaw) <= max_dyaw_rad):
        return 'motion_bound'
    g = _ground_to_pixel(ground, camera_x_offset_m)
    height, width = shape
    # The visible floor of the new frame is the convex quad of these corners; depth in the old
    # camera is linear on the floor, so positive at the corners means positive everywhere
    # (cv2 would otherwise fold floor from behind the old lens into the picture).
    corners = np.array([[0, horizon_cut_row, 1], [width - 1, horizon_cut_row, 1],
                        [0, height - 1, 1], [width - 1, height - 1, 1]], float).T
    floor_new = np.linalg.solve(g, corners)
    floor_old = np.linalg.solve(move, floor_new / floor_new[2])
    if not np.all((g @ floor_old)[2] > 0):
        return 'motion_bound'
    return g @ move @ np.linalg.inv(g), dxy, dyaw


def warp_mask(mask: np.ndarray, homography: np.ndarray, horizon_cut_row: int) -> np.ndarray:
    """The mask seen from the new frame: nearest neighbour, unseen floor 0, sky rows 0."""
    out = cv2.warpPerspective(mask, homography, (mask.shape[1], mask.shape[0]),
                              flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    out[:max(0, horizon_cut_row)] = 0
    return out
