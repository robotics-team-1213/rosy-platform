"""Subject: keep-mode steering straight from the learned drivable way (D-597 amendment 2).

User intent (2026-10-10): steer to the centre of the drivable lane space. The synthetic boundary
paint (drivable_paint.boundary_paint) made the tape keeper pair two strips a lane width apart; a
wider way (ring, junction mouth) or an edge at the frame border left it one-sided or with no
boundary at all (an L-corner against a wall: HOLD camera_line_not_visible). This steers from the
way itself, pure numpy, no ROS:

way_target   the way (frame-size mask, one inference) + ground plane -> the pursuit point in
             base_link (x ahead, y left) and how far the way runs straight ahead.
             Per image row the way spans [first, last] columns; an edge on the frame border is
             unseen (open). Centre per row: both edges seen -> their middle; one seen -> that edge
             lane_half_width toward the open side; none -> the middle of the view. The pursuit
             point is the median centre over the rows within ROW_BAND_M of the lookahead (or the
             way's farthest rows when it ends nearer). ahead_m is how far the robot's own
             corridor (|y| <= CORRIDOR_HALF_M) stays on the way.
DrivableSteer per camera frame: the newest way's target moved into the current pose by odometry
             (the way is not re-warped), error = -y / lane_half_width (the keeper's contract).
             Closed ahead (ahead_m < PIVOT_AHEAD_M) with an exit at a side of the view turns in
             place toward it (keep right when both sides are open, D-384 2): error +-PIVOT_ERROR
             at PIVOT_CONFIDENCE, which CORE's speed scale turns into ~0 linear. Released when
             the way runs ahead again (PIVOT_RELEASE_M). Closed with no exit: no target (HOLD;
             CORE's own back-off and resume apply).
"""

from __future__ import annotations

import math

import numpy as np

LOOKAHEAD_M = 0.25
ROW_BAND_M = 0.03
CORRIDOR_HALF_M = 0.03
#: corridor share of way pixels for a row to count as open straight ahead
CORRIDOR_FILL = 0.8
PIVOT_AHEAD_M = 0.14
PIVOT_RELEASE_M = 0.22
#: a latched turn side is released when the way runs this far straight ahead again
TURN_RELEASE_M = 0.30
PIVOT_ERROR = 0.5
PIVOT_CONFIDENCE = 0.37
BOTH_CONFIDENCE = 0.9
ONE_CONFIDENCE = 0.6
#: a side exit needs this many way rows on the frame border above the near band
SIDE_EXIT_ROWS = 4
EXIT_TIE_M = 0.03
#: a side opening counts as an exit only once its near end is within this of the nearest way row
EXIT_NEAR_M = 0.10
#: without a way this long, the pivot latch and smoothing are forgotten
FORGET_S = 1.5
SMOOTHING = 0.5


def _row_x(rows, ground, x_offset):
    """base_link x of the floor at each image row (inf at or above the horizon)."""
    ray = ground.pitch_rad + np.arctan((np.asarray(rows, float) - ground.principal_y) / ground.focal_px)
    with np.errstate(divide="ignore"):
        return np.where(ray > 0.0, ground.height_m / np.tan(np.maximum(ray, 1e-9)), np.inf) + x_offset


def _col_y(cols, rows, ground):
    """base_link y (left +) of image columns at those rows (GroundPlane.lateral)."""
    denominator = (ground.focal_px * math.sin(ground.pitch_rad)
                   + (np.asarray(rows, float) - ground.principal_y) * math.cos(ground.pitch_rad))
    return (ground.principal_x - np.asarray(cols, float)) * ground.height_m / np.maximum(denominator, 1e-9)


def way_target(way: np.ndarray, ground, x_offset: float, half: float, lookahead: float = LOOKAHEAD_M):
    """dict(target_m=(x, y) or None, ahead_m, exit=left|right|None, both=bool) for one way mask."""
    way = np.asarray(way) > 0
    height, width = way.shape
    rows = np.flatnonzero(way.any(axis=1))
    rows = rows[rows > ground.principal_y - ground.focal_px * math.tan(ground.pitch_rad)]   # below horizon
    out = dict(target_m=None, ahead_m=0.0, exit=None, both=False, exit_point_m={})
    if not rows.size:
        return out
    first = np.argmax(way[rows], axis=1)
    last = width - 1 - np.argmax(way[rows, ::-1], axis=1)
    xs = _row_x(rows, ground, x_offset)
    y_left, y_right = _col_y(first, rows, ground), _col_y(last, rows, ground)
    open_left, open_right = first == 0, last == width - 1
    centre = np.where(open_left & ~open_right, y_right + half,
                      np.where(open_right & ~open_left, y_left - half, (y_left + y_right) / 2.0))
    # ahead: walk up from the nearest row while the corridor columns are on the way
    ahead = 0.0
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        denominator = ground.focal_px * math.sin(ground.pitch_rad) + (row - ground.principal_y) * math.cos(ground.pitch_rad)
        span = CORRIDOR_HALF_M * max(denominator, 1e-9) / ground.height_m
        a = max(0, int(round(ground.principal_x - span)))
        b = min(width, int(round(ground.principal_x + span)) + 1)
        if b <= a or way[row, a:b].mean() < CORRIDOR_FILL:
            break
        if index < len(rows) - 1 and rows[index + 1] - row > 2:   # a gap between way rows ends the corridor
            break
        ahead = float(xs[index])
    out["ahead_m"] = round(ahead, 3)
    # A side exit: the way stays on that frame border for SIDE_EXIT_ROWS rows past the near band.
    # The side whose open border reaches farther wins (a wall corner leaves the floor on the border
    # only near the robot); within EXIT_TIE_M of each other, keep right (D-384 2).
    above = xs > float(xs.min()) + 0.04
    reach, near_ok = {}, {}
    for side, edge in (("left", open_left), ("right", open_right)):
        hit = edge & above
        if int(hit.sum()) >= SIDE_EXIT_ROWS:
            near_ok[side] = float(xs[hit].min()) <= float(xs.min()) + EXIT_NEAR_M
            far = int(np.argmax(np.where(hit, xs, -np.inf)))
            reach[side] = float(xs[far])
            # the point to arc toward: where the way leaves the view on that side, farthest out
            out["exit_point_m"][side] = (round(float(xs[far]), 3),
                                                       round(float((y_left if side == "left" else y_right)[far]), 3))
    if len(reach) == 2:
        out["exit"] = "left" if reach["left"] > reach["right"] + EXIT_TIE_M else "right"
    elif reach:
        out["exit"] = next(iter(reach))
    # The opening must already reach beside the robot: turning toward a mouth still ahead cuts
    # across the boundary before it (9dfk 20261010T002026Z hit the ring's outer line at the SE exit).
    if out["exit"] is not None and not near_ok[out["exit"]]:
        out["exit"] = None
    out["exit_reach_m"] = {k: round(v, 3) for k, v in reach.items()}
    pursuit = min(lookahead, float(xs.max()))
    band = np.abs(xs - pursuit) <= ROW_BAND_M
    if not band.any():
        band = xs >= np.sort(xs)[-3:].min()
    out["target_m"] = (round(float(np.median(xs[band])), 3), round(float(np.median(centre[band])), 3))
    out["both"] = bool(np.mean(~open_left[band] & ~open_right[band]) >= 0.5)
    return out


def _to_current(point, source_pose, current_pose):
    """A base_link point at source_pose seen from current_pose ((x, y, yaw) odometry)."""
    if source_pose is None or current_pose is None:
        return point
    xs, ys, yaws = source_pose
    xc, yc, yawc = current_pose
    wx = xs + math.cos(yaws) * point[0] - math.sin(yaws) * point[1]
    wy = ys + math.sin(yaws) * point[0] + math.cos(yaws) * point[1]
    dx, dy = wx - xc, wy - yc
    return (math.cos(yawc) * dx + math.sin(yawc) * dy, -math.sin(yawc) * dx + math.cos(yawc) * dy)


class DrivableSteer:
    """Keep-mode steering from the newest drivable way; the only memory is the pivot latch,
    the cached per-way target and the smoothed lateral offset."""

    def __init__(self):
        self._key = None
        self._target = None
        self._pivot = None
        self._smoothed = None
        self._side = None
        self._lost_since = None

    def reset(self):
        self._key = self._target = self._pivot = self._smoothed = self._side = None
        self._lost_since = None

    def lost(self, stamp):
        """No fresh way this frame: forget the latch only after FORGET_S without one."""
        if self._lost_since is None:
            self._lost_since = stamp
        elif stamp - self._lost_since > FORGET_S:
            self.reset()

    def update(self, way, way_key, ground, x_offset, half, source_pose=None, current_pose=None):
        """(error, confidence, debug) or (None, None, debug) for no target."""
        self._lost_since = None
        if way_key != self._key:
            self._key, self._target = way_key, way_target(way, ground, x_offset, half)
        info = dict(self._target)
        ahead, side = info["ahead_m"], info["exit"]
        # The side chosen at a closing bend or junction is kept until the way runs ahead again
        # (9dfk 20261010T001349Z weaved right/left at the ring's SE exit when the exit tie flipped).
        if self._side is not None and ahead >= TURN_RELEASE_M:
            self._side = None
        if self._side is None and ahead < LOOKAHEAD_M and side is not None:
            self._side = side
        if self._side is not None and self._side in info["exit_point_m"]:
            side = info["exit"] = self._side
        if self._pivot is not None and (ahead >= PIVOT_RELEASE_M or side is None):
            self._pivot = None
        if self._pivot is None and ahead < PIVOT_AHEAD_M and side is not None:
            self._pivot = side
        if self._pivot is not None:
            self._smoothed = None
            error = -PIVOT_ERROR if self._pivot == "left" else PIVOT_ERROR
            return error, PIVOT_CONFIDENCE, dict(info, strategy=f"drivable_pivot_{self._pivot}")
        if info["target_m"] is None or ahead < PIVOT_AHEAD_M and side is None and ahead < 0.12:
            self._smoothed = None
            return None, None, dict(info, strategy="none", reason="drivable_closed")
        strategy, target = "drivable_centre", info["target_m"]
        if ahead < LOOKAHEAD_M and side is not None:
            # closed before the lookahead with a side exit (a bend, an L-corner): arc toward the exit
            strategy, target = f"drivable_turn_{side}", info["exit_point_m"][side]
        tx, ty = _to_current(target, source_pose, current_pose)
        self._smoothed = ty if self._smoothed is None else SMOOTHING * self._smoothed + (1 - SMOOTHING) * ty
        error = max(-1.0, min(1.0, -self._smoothed / half))
        confidence = BOTH_CONFIDENCE if info["both"] else ONE_CONFIDENCE
        return error, confidence, dict(info, strategy=strategy, target_now_m=(round(tx, 3), round(self._smoothed, 3)))

