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
from core_common.robot_body import NOMINAL_BODY

from ..lane_keep_lines import PAINT_HALF_WIDTH_M

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
EXIT_TIE_M = 0.10
#: a side whose LiDAR shows a wall nearer than this (lateral, within 0.35 m ahead) is no exit
SIDE_WALL_M = 0.20
#: the way's nearest row may start at most this far beyond the frame's bottom row
NEAR_GAP_M = 0.04
#: a wall ahead counts as the way's end this much before it (the body front is 0.042 m)
WALL_STANDOFF_M = 0.08
#: an opening seen this far back (odometry travel) still names the side to turn at a closed way
EXIT_MEMORY_M = 0.5
PAINT_HALF_M = PAINT_HALF_WIDTH_M
#: the boundary memory: seen way edges in odometry, newest last
EDGE_MEMORY_POINTS = 1200
#: only edges this near are remembered (the ground projection error grows with range)
EDGE_MEMORY_MAX_X_M = 0.25
#: URDF body (D-424), base_footprint
BODY_HALF_M = NOMINAL_BODY.half_width_m
#: a remembered boundary point this close to the path robot->target blocks that target
CROSS_TOL_M = 0.015
#: boundary points nearer than this along the arc are not judged (projection and odometry noise)
CROSS_MIN_ALONG_M = 0.06
#: an in-place turn stops after this much rotation (no U-turn without a route; p8 crosswalk)
PIVOT_MAX_RAD = 1.75
#: a route prior within this of straight ahead means "keep going" (no exit turn)
GUIDE_STRAIGHT_DEG = 25.0
#: beyond this the robot faces against the lane: reorient in place first
GUIDE_REVERSE_DEG = 100.0
#: after a crosswalk zone is seen, no pivot or exit turn for this much travel
CROSSWALK_HOLD_M = 0.35
#: the way's near centre is the median centre of its rows within this of its nearest row
NEAR_BAND_M = 0.06
#: a side opening counts as an exit only once its near end is within this of the nearest way row
EXIT_NEAR_M = 0.05
#: the bottom rows and centre half-width (px) that tell a line under the body
STRADDLE_ROWS = 12
STRADDLE_HALF_PX = 12
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
    out = dict(target_m=None, ahead_m=0.0, exit=None, seen_exit=None, straddle=None, both=False, exit_point_m={},
               exit_reach_m={}, near_centre_m=None, edges_m=[])
    if not rows.size:
        return out
    # The way must start under the robot: floor that begins only beyond a gap is past a line
    # (9dfk 20261010T002541Z pivoted on the ring's island line, then drove into the island).
    if float(_row_x([rows.max()], ground, x_offset)[0]) > float(_row_x([height - 1], ground, x_offset)[0]) + NEAR_GAP_M:
        out["reason"] = "way_beyond_line"
        return out
    # A line under the robot: the bottom rows' middle is not way but one side is (the body straddles
    # a line; 9dfk sat on the ring's island line, IR lane_departure, 20261010T032022Z_rosy_41).
    bottom = way[height - STRADDLE_ROWS:]
    mid = int(round(ground.principal_x))
    if bottom.any() and not bottom[:, mid - STRADDLE_HALF_PX:mid + STRADDLE_HALF_PX].any():
        left, right = bottom[:, :mid].sum(), bottom[:, mid:].sum()
        out["straddle"] = "left" if left > right else "right"
    first = np.argmax(way[rows], axis=1)
    last = width - 1 - np.argmax(way[rows, ::-1], axis=1)
    xs = _row_x(rows, ground, x_offset)
    y_left, y_right = _col_y(first, rows, ground), _col_y(last, rows, ground)
    open_left, open_right = first == 0, last == width - 1
    # the seen boundary (closed edges) for the boundary memory, every 3rd row
    out["edges_m"] = [(float(xs[i]), float(y)) for i in range(0, len(rows), 3) if xs[i] <= EDGE_MEMORY_MAX_X_M
                      for y, closed in ((y_left[i], not open_left[i]), (y_right[i], not open_right[i])) if closed]
    # one edge seen: the drivable edge is the tape's inner edge, so the lane centre is half a lane
    # minus half a tape inside it
    inner = half - PAINT_HALF_M
    centre = np.where(open_left & ~open_right, y_right + inner,
                      np.where(open_right & ~open_left, y_left - inner, (y_left + y_right) / 2.0))
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
            # aim at the middle of the opening, not its far end: the far end cut the inside corner
            # (9dfk 20261010T030423Z_rosy_41 left the lane twice at the NE spoke turning right)
            idx = np.flatnonzero(hit)
            far = int(idx[np.argsort(xs[idx])[len(idx) // 2]])
            reach[side] = float(xs[hit].max())
            out["exit_point_m"][side] = (round(float(xs[far]), 3),
                                                       round(float((y_left if side == "left" else y_right)[far]), 3))
    if len(reach) == 2:
        out["exit"] = "left" if reach["left"] > reach["right"] + EXIT_TIE_M else "right"
    elif reach:
        out["exit"] = next(iter(reach))
    # The opening must already reach beside the robot: turning toward a mouth still ahead cuts
    # across the boundary before it (9dfk 20261010T002026Z hit the ring's outer line at the SE exit).
    out["seen_exit"] = out["exit"]
    if out["exit"] is not None and not near_ok[out["exit"]]:
        out["exit"] = None
    out["exit_reach_m"] = {k: round(v, 3) for k, v in reach.items()}
    near = xs <= float(xs.min()) + NEAR_BAND_M
    out["near_centre_m"] = (round(float(np.median(xs[near])), 3), round(float(np.median(centre[near])), 3))
    pursuit = min(lookahead, float(xs.max()))
    band = np.abs(xs - pursuit) <= ROW_BAND_M
    if not band.any():
        band = xs >= np.sort(xs)[-3:].min()
    out["target_m"] = (round(float(np.median(xs[band])), 3), round(float(np.median(centre[band])), 3))
    out["both"] = bool(np.mean(~open_left[band] & ~open_right[band]) >= 0.5)
    return out


def _crosses(points, tx, ty):
    """Lateral offset of the nearest remembered boundary point within CROSS_TOL_M of the arc the
    robot drives to (tx, ty) (tangent to its heading, as a pure-pursuit arc), or None. The chord
    would cut the inside of every bend."""
    d2 = tx * tx + ty * ty
    if d2 < 1e-6 or not points:
        return None
    k = 2.0 * ty / d2                                    # signed curvature, left +
    pts = np.asarray(points, float)
    if abs(k) < 1e-6:
        along, across = pts[:, 0], np.abs(pts[:, 1])
        length = tx
    else:
        r = 1.0 / k                                       # circle centre (0, r)
        dist = np.hypot(pts[:, 0], pts[:, 1] - r)
        across = np.abs(dist - abs(r))
        ang = np.arctan2(pts[:, 0], np.sign(r) * (r - pts[:, 1]))   # angle travelled along the arc
        along = ang * abs(r)
        length = math.atan2(tx, math.copysign(1.0, r) * (r - ty)) * abs(r)
    hit = (along > CROSS_MIN_ALONG_M) & (along < length) & (across < CROSS_TOL_M)
    if not hit.any():
        return None
    first = int(np.argmin(np.where(hit, along, np.inf)))
    return float(pts[first, 1])


#: CORE line-follow law the error is shaped for (rosy_default.yaml line_follow; robot overlays):
#: angular = -STEERING_GAIN * error, linear = CRUISE * scale(confidence) * max(0.2, 1 - CURVE * |error|).
CORE_STEERING_GAIN, CORE_MIN_CONFIDENCE, CORE_CURVE_SLOWDOWN, CORE_CRUISE_MPS = 0.8, 0.35, 0.65, 0.04


def pursuit_error(tx, ty, confidence):
    """The keep error whose CORE command drives the pure-pursuit arc to (tx, ty): curvature
    k = 2y/(x^2+y^2) and w/v = k under CORE's law (CORE keeps the curvature when it caps w).
    error = -y/half made CORE turn 5-30x tighter than the road (independent review: actual radius
    0.025 m vs road 0.25 m in turns), cutting corners onto lines (user 2026-10-10)."""
    d2 = tx * tx + ty * ty
    if d2 < 1e-6:
        return 0.0
    k = 2.0 * ty / d2
    speed = CORE_CRUISE_MPS * max(0.0, (confidence - CORE_MIN_CONFIDENCE) / (1.0 - CORE_MIN_CONFIDENCE))
    kc = abs(k) * speed
    error = kc / (CORE_STEERING_GAIN + CORE_CURVE_SLOWDOWN * kc) if speed > 0 else 1.0
    return float(-math.copysign(min(1.0, error), k))


def _to_world(point, pose):
    x, y, yaw = pose
    return (x + math.cos(yaw) * point[0] - math.sin(yaw) * point[1], y + math.sin(yaw) * point[0] + math.cos(yaw) * point[1])


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
    """Keep-mode steering from the newest drivable way. Memory: the pivot and turn-side latches, the
    last opening seen, the smoothed lateral offset, and the boundary memory (way edges seen, in
    odometry) that keeps the body off lines the camera no longer sees."""

    def __init__(self):
        self._key = None
        self._target = None
        self._pivot = None
        self._smoothed = None
        self._side = None
        self._memory = None
        self._edges = []
        self._pivot_yaw = None
        self._crosswalk_pose = None
        self._lost_since = None

    def reset(self):
        self._key = self._target = self._pivot = self._smoothed = self._side = self._memory = None
        self._pivot_yaw = None
        self._crosswalk_pose = None
        self._edges = []
        self._lost_since = None

    def lost(self, stamp):
        """No fresh way this frame: forget the latch only after FORGET_S without one."""
        if self._lost_since is None:
            self._lost_since = stamp
        elif stamp - self._lost_since > FORGET_S:
            self.reset()

    def crosswalk(self, pose):
        """A crosswalk zone was seen this frame (D-491 extent): hold the heading through it."""
        self._crosswalk_pose = pose

    def _in_crosswalk(self, pose):
        if self._crosswalk_pose is None or pose is None:
            return False
        if math.hypot(pose[0] - self._crosswalk_pose[0], pose[1] - self._crosswalk_pose[1]) > CROSSWALK_HOLD_M:
            self._crosswalk_pose = None
            return False
        return True

    def update(self, way, way_key, ground, x_offset, half, source_pose=None, current_pose=None,
               wall_ahead_m=None, side_clear_m=None, guide_deg=None):
        """(error, confidence, debug) or (None, None, debug) for no target. wall_ahead_m: base_link x
        of the nearest LiDAR return in the body's straight strip (None: unknown or nothing); the
        model sees floor only out to ~0.37 m, so a wall beyond its view still closes the way."""
        self._lost_since = None
        if way_key != self._key:
            self._key, self._target = way_key, way_target(way, ground, x_offset, half)
            if source_pose is not None:
                self._edges.extend(_to_world(p, source_pose) for p in self._target["edges_m"])
                del self._edges[:-EDGE_MEMORY_POINTS]
        info = {k: v for k, v in self._target.items() if k != "edges_m"}
        seen = [_to_current(p, (0.0, 0.0, 0.0), current_pose) for p in self._edges] if current_pose is not None else []
        if wall_ahead_m is not None and info["target_m"] is not None:
            info["wall_ahead_m"] = round(wall_ahead_m, 3)
            info["ahead_m"] = min(info["ahead_m"], round(wall_ahead_m - WALL_STANDOFF_M, 3))
        if side_clear_m:
            # A wall beside the robot is no road (the floor between a wall corner and the tape reads as
            # an opening); keep right only between real openings (D-384 2).
            open_sides = [k for k in info["exit_reach_m"] if side_clear_m.get(k) is None or side_clear_m[k] >= SIDE_WALL_M]
            for key in ("exit", "seen_exit"):
                if info.get(key) is not None and info[key] not in open_sides:
                    info[key] = open_sides[0] if len(open_sides) == 1 and key == "seen_exit" else None
            info["side_clear_m"] = {k: (None if v is None else round(v, 3)) for k, v in side_clear_m.items()}
        ahead, side = info["ahead_m"], info["exit"]
        if guide_deg is not None:
            # Route prior (Fleet guidance, D-511 rev 2: the lane direction ahead minus the heading):
            # the map knows which way the road goes where the camera sees two openings or none.
            info["guide_deg"] = round(guide_deg, 1)
            if abs(guide_deg) > GUIDE_REVERSE_DEG:
                # facing against the lane: turn in place toward its direction (user 2026-10-10: when
                # the direction is wrong, set it right; 9dfk 20261010T042913Z_rosy_41 U-turned at the
                # S-curve top and drove the loop backwards)
                self._smoothed = self._pivot = self._side = None
                error = -PIVOT_ERROR if guide_deg > 0 else PIVOT_ERROR
                return error, PIVOT_CONFIDENCE, dict(info, strategy="drivable_reorient_" + ("left" if guide_deg > 0 else "right"))
            want = None if abs(guide_deg) < GUIDE_STRAIGHT_DEG else ("left" if guide_deg > 0 else "right")
            if want is None:
                side = info["exit"] = None if ahead >= PIVOT_AHEAD_M else side
            elif want in info["exit_reach_m"]:
                side = info["exit"] = want
            elif ahead < LOOKAHEAD_M:
                # no opening seen on the route's side and the way closes: turn in place toward it, never
                # an arc that rolls forward onto the line ahead (9dfk 20261010T043756Z_rosy_41 crossed one)
                self._smoothed = None
                error = -PIVOT_ERROR if want == "left" else PIVOT_ERROR
                return error, PIVOT_CONFIDENCE, dict(info, strategy="drivable_pivot_" + want, guided=True)
            elif side is not None and side != want:
                side = info["exit"] = None      # an opening against the route is not taken
            self._side = side if side is not None else self._side
        if side is not None and current_pose is not None and _crosses(
                seen, *_to_current(info["exit_point_m"][side], source_pose, current_pose)) is not None:
            # an "opening" beyond a boundary seen earlier is a strip past a line, not a road
            # (p8: exit right at y -0.17 m by the crosswalk, beyond the lane's boundary line)
            side = info["exit"] = None
            info["exit_behind_line"] = True
        # Exit memory: an opening seen on the way in leaves the view near the corner (the camera
        # sees ~+-30 deg and ~0.37 m), so a closed way pivots toward the last opening seen within
        # EXIT_MEMORY_M of travel (8kcn at the SE spoke's foot, 9dfk at the top-left corner).
        if info.get("seen_exit") is not None:
            self._memory = (info["seen_exit"], current_pose)
        elif self._memory is not None and current_pose is not None and self._memory[1] is not None and math.hypot(
                current_pose[0] - self._memory[1][0], current_pose[1] - self._memory[1][1]) > EXIT_MEMORY_M:
            self._memory = None
        if side is None and ahead < PIVOT_AHEAD_M and self._memory is not None:
            side = info["exit"] = self._memory[0]
            info["exit_from_memory"] = True
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
        if info.get("straddle") is not None and not self._in_crosswalk(current_pose):
            # off the line first: turn toward the way (CORE creeps back while its IR sees the line,
            # D-344 §12 amendment 3), then the normal rules
            self._smoothed = self._pivot = None
            error = -PIVOT_ERROR if info["straddle"] == "left" else PIVOT_ERROR
            return error, PIVOT_CONFIDENCE, dict(info, strategy=f"drivable_off_line_{info['straddle']}")
        if self._in_crosswalk(current_pose):
            # Crosswalk bars, a speed bump or a cable cut the way short there; the lane goes straight
            # across. No pivot or exit turn: centre steering only, and CORE's D-573 gate stops, looks
            # and crosses (p8/p10: pivots at the bottom-road crosswalk became U-turns).
            side, self._pivot, self._side = None, None, None
            info["crosswalk_hold"] = True
            if ahead < LOOKAHEAD_M:
                self._smoothed = 0.0 if self._smoothed is None else self._smoothed
                return 0.0, ONE_CONFIDENCE, dict(info, strategy="drivable_crosswalk_straight")
        if self._pivot is None and ahead < PIVOT_AHEAD_M and side is not None:
            self._pivot = side
            self._pivot_yaw = None if current_pose is None else current_pose[2]
        if self._pivot is None:
            self._pivot_yaw = None
        elif self._pivot_yaw is not None and current_pose is not None and abs(
                math.atan2(math.sin(current_pose[2] - self._pivot_yaw), math.cos(current_pose[2] - self._pivot_yaw))) > PIVOT_MAX_RAD:
            # Budget spent: drop the turn and its memories and carry on with what is in front (a
            # sticky stop here held 9dfk LOST for good, 20261010T040459Z_rosy_41).
            self._pivot = self._side = self._memory = self._pivot_yaw = None
            side = info["exit"] = None
            info["pivot_limit"] = True
        if self._pivot is not None:
            self._smoothed = None
            error = -PIVOT_ERROR if self._pivot == "left" else PIVOT_ERROR
            return error, PIVOT_CONFIDENCE, dict(info, strategy=f"drivable_pivot_{self._pivot}")
        if info["target_m"] is None or ahead < PIVOT_AHEAD_M and side is None and ahead < 0.12:
            self._smoothed = None
            return None, None, dict(info, strategy="none", reason=info.get("reason") or "drivable_closed")
        strategy, target = "drivable_centre", info["target_m"]
        if ahead < LOOKAHEAD_M and side is not None:
            # closed before the lookahead with a side exit (a bend, an L-corner): arc toward the exit
            strategy, target = f"drivable_turn_{side}", info["exit_point_m"][side]
        tx, ty = _to_current(target, source_pose, current_pose)
        # The boundary memory only rejects exits (above). Clamping the target with it made most pivots:
        # independent replay, p8 17 of 19 pivot episodes followed a clamp, wobble 4.3 -> 0.3 /min without.
        self._smoothed = ty if self._smoothed is None else SMOOTHING * self._smoothed + (1 - SMOOTHING) * ty
        confidence = BOTH_CONFIDENCE if info["both"] else ONE_CONFIDENCE
        error = pursuit_error(tx, self._smoothed, confidence)
        return error, confidence, dict(info, strategy=strategy, target_now_m=(round(tx, 3), round(self._smoothed, 3)))

