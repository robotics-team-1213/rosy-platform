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
             point is the centre at arc length LOOKAHEAD_M, on the commanded curvature. ahead_m
             is how far the robot's corridor (|y| <= CORRIDOR_HALF_M) stays on the way.
DrivableSteer per camera frame: the newest way's target moved into the current pose by odometry (not re-warped);
             the error holds that curvature at cruise_speed. Closed ahead (ahead_m < PIVOT_AHEAD_M) with an exit
             at a side turns in place toward it (keep right when both are open, D-384 2): +-PIVOT_ERROR at the
             law's min_confidence (CORE: 0 linear), released when the way runs ahead again (PIVOT_RELEASE_M).
             Closed with no exit: no target (HOLD; CORE's own back-off and resume apply).
"""

from __future__ import annotations

import collections
from functools import partial
import math
import time

import numpy as np
from core_common.robot_body import NOMINAL_BODY

from .target import CROSS_MIN_ALONG_M, CROSS_TOL_M, MAX_TARGET_CURVATURE, ROW_BAND_M, _centre_target, _col_y, _crosses, _exit_rows, _local_floor, _observed_target, _row_x, _to_current, _to_world, one_edge_centre  # noqa: F401 (re-exported)
from .route_guard import observed_route_candidate, route_exit_point
from ..lane_keep_lines import PAINT_HALF_WIDTH_M

LOOKAHEAD_M = 0.25
CORRIDOR_HALF_M = 0.03
#: corridor share of way pixels for a row to count as open straight ahead
CORRIDOR_FILL = 0.8
PIVOT_AHEAD_M = 0.14
PIVOT_GUIDE_DEG = 45.0   # a milder map bend ahead is arced, not turned in place (v2 lap r28: 14 cm early)
RECENTRE_M = 0.04   # way centre this far toward the other side: recentre, no pivot (v2 lap r45a)
#: a way whose centre target lies at least this far ahead bends on past a short straight corridor (v2 lap 2026-10-18)
BEND_ON_X_M = 0.18
#: closed ahead with no opening: a way target at least this far off the heading is the side to turn to
TARGET_SIDE_DEG = 20.0
#: a way closed nearer than this is closed at the body: only a turn in place remains
PIVOT_AT_BODY_M = 0.05
#: CORE's front stop distance (safety profile `stop`, LiDAR range, nominal body; v2 lap r20)
FRONT_STOP_M = 0.149
PIVOT_RELEASE_M = 0.22
#: a latched turn side is released when the way runs this far straight ahead again
TURN_RELEASE_M = 0.30
PIVOT_ERROR = 0.5
#: a turn in place is sent at the law's min_confidence (this is the default law's): CORE's speed scale
#: makes that exactly 0 linear. 0.37 left ~2 mm/s, which put a wall inside CORE's front stop distance
#: on the turn too and held it (v2 lap r9-r16 at the NE corner exit, wall 0.13 m off the front sector).
PIVOT_CONFIDENCE = 0.35
BOTH_CONFIDENCE = 0.9
ONE_CONFIDENCE = 0.6
#: a side exit needs this many way rows on the frame border above the near band
SIDE_EXIT_ROWS = 4
EXIT_TIE_M = 0.10
#: base_link lateral distance: body half width plus the operator's 5 cm outside-body margin
SIDE_WALL_M = NOMINAL_BODY.half_width_m + 0.05
#: the way's nearest row may start at most this far beyond the frame's bottom row
NEAR_GAP_M = 0.04
#: a wall ahead counts as the way's end this much before it (the body front is 0.042 m)
WALL_STANDOFF_M = NOMINAL_BODY.front_x_m + 0.02
#: an opening seen this far back (odometry travel) still names the side to turn at a closed way
EXIT_MEMORY_M = 0.5
PAINT_HALF_M = PAINT_HALF_WIDTH_M
#: the boundary memory: seen way edges in odometry, newest last
EDGE_MEMORY_POINTS = 1200
#: only edges this near are remembered (the ground projection error grows with range)
EDGE_MEMORY_MAX_X_M = 0.25
#: CORE's corridor edges come from way rows this far beyond the nearest way row (~0.15-0.27 m ahead)
CORRIDOR_NEAR_M = 0.12
#: URDF body (D-424), base_footprint
BODY_HALF_M = NOMINAL_BODY.half_width_m
#: an in-place turn stops after this much rotation (no U-turn without a route; p8 crosswalk)
PIVOT_MAX_RAD = 1.75
#: a route prior within this of straight ahead means "keep going" (no exit turn)
GUIDE_STRAIGHT_DEG = 25.0
#: Driving context (architect 2026-10-10, X:/DevTemp/steer-review/context): an exit is taken only where
#: the map bends that way >= EXIT_BEND_DEG within 0.25 m (g1: 34 opposite + 14 fake exits of 750 turn frames)
EXIT_BEND_DEG = 15.0
#: the chosen target off the map heading by > |bend| + REALIGN_DEG for REALIGN_S: HOLD and request realign
#: (g6/g7 NE spoke: 378/384 and 645/647 frames misaligned)
REALIGN_DEG, REALIGN_S = 30.0, 2.0
#: beyond this the robot faces against the lane: reorient in place first
GUIDE_REVERSE_DEG = 90.0
#: after a crosswalk zone is seen, no pivot or exit turn for this much travel
CROSSWALK_HOLD_M = 0.35
#: the way's near centre is the median centre of its rows within this of its nearest row
NEAR_BAND_M = 0.06
#: a side opening counts as an exit only once its near end is within this of the nearest way row
EXIT_NEAR_M = 0.05
#: the bottom rows and centre half-width (px) that tell a line under the body
STRADDLE_ROWS = 12
STRADDLE_HALF_PX = 12
FORGET_S = 1.5   # without a way this long, the pivot latch and smoothing are forgotten
SMOOTHING = 0.5


def way_target(way: np.ndarray, ground, x_offset: float, half: float, lookahead: float = LOOKAHEAD_M):
    """dict(target_m=(x, y) or None, ahead_m, exit=left|right|None, both=bool) for one way mask."""
    way = np.asarray(way) > 0
    height, width = way.shape
    rows = np.flatnonzero(way.any(axis=1))
    rows = rows[rows > ground.principal_y - ground.focal_px * math.tan(ground.pitch_rad)]   # below horizon
    out = dict(target_m=None, ahead_m=0.0, exit=None, seen_exit=None, straddle=None, both=False, exit_point_m={},
               exit_reach_m={}, near_centre_m=None, centre_path_m=[], edges_m=[], near_edges_m={})
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
    # CORE's lane corridor (D-468) from the way's own edges, near the robot only: a far bend's edge
    # fitted straight and extrapolated back to the body read as a departure (v2 lap, 2026-10-18).
    # A side whose near rows run off the frame is unseen, not a boundary.
    near_rows = xs <= float(xs.min()) + CORRIDOR_NEAR_M
    out["near_edges_m"] = {side: [(float(x), float(y)) for x, y, o in zip(xs[near_rows], ys[near_rows], opened[near_rows])
                                  if not o]
                           for side, ys, opened in (("left", y_left, open_left), ("right", y_right, open_right))}
    # one edge seen: the drivable edge is the tape's inner edge, so the lane centre is half a lane
    # minus half a tape inside it
    inner = half - PAINT_HALF_M
    centre = np.where(open_left & ~open_right, y_right + inner,
                      np.where(open_right & ~open_left, y_left - inner, (y_left + y_right) / 2.0))
    out['local_floor_m'] = _local_floor(way, rows, xs, centre, ground, BEND_ON_X_M)
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
    reach, near_ok = {}, {}
    for side, edge in (("left", open_left), ("right", open_right)):
        idx, close = _exit_rows(xs, rows, edge, SIDE_EXIT_ROWS, EXIT_NEAR_M)
        if len(idx):
            near_ok[side] = close
            # aim at the middle of the opening, not its far end: the far end cut the inside corner
            # (9dfk 20261010T030423Z_rosy_41 left the lane twice at the NE spoke turning right)
            far = int(idx[np.argsort(xs[idx])[len(idx) // 2]])
            reach[side] = float(xs[idx].max())
            out["exit_point_m"][side] = (round(float(xs[far]), 3),
                                                       round(float((y_left if side == "left" else y_right)[far]), 3))
    if len(reach) == 2:
        out["exit"] = "left" if reach["left"] > reach["right"] + EXIT_TIE_M else "right"
    elif reach:
        out["exit"] = next(iter(reach))
    # The opening must already reach beside the robot: turning toward a mouth still ahead cuts
    # across the boundary before it (9dfk 20261010T002026Z hit the ring's outer line at the SE exit).
    out.update(seen_exit=out["exit"], exit_near=near_ok)
    if out["exit"] is not None and not near_ok[out["exit"]]:
        out["exit"] = None
    out["exit_reach_m"] = {k: round(v, 3) for k, v in reach.items()}
    near = xs <= float(xs.min()) + NEAR_BAND_M
    out["near_centre_m"] = (round(float(np.median(xs[near])), 3), round(float(np.median(centre[near])), 3))
    # Keep only the connected near observation; a row gap is not a road segment.
    connected = [len(rows) - 1]
    for index in range(len(rows) - 2, -1, -1):
        if rows[index + 1] - rows[index] > 2 or not math.isfinite(xs[index]) or xs[index] <= 0:
            break
        connected.append(index)
        if xs[index] - xs[connected[0]] >= LOOKAHEAD_M:
            break
    if len(connected) >= 2:
        cx, cy = xs[connected], centre[connected]
        stations = np.linspace(cx[0], cx[-1], min(32, len(connected)))
        out['centre_path_m'] = [(float(x), float(y)) for x, y in zip(stations, np.interp(stations, cx, cy))]
    # The target's centre with one edge seen lies `inner` from that edge along its normal, not across the
    # row: on a tight bend the edge runs sideways and the across-row offset put the centre inside the
    # corner, so the robot cut it (v2 lap r7, 2026-10-18). An edge along the travel gives the same point.
    target_x, target_y = xs.copy(), centre.copy()
    for one, edge, sign, seen in ((open_left & ~open_right, y_right, 1.0, ~open_right),
                                  (open_right & ~open_left, y_left, -1.0, ~open_left)):
        if one.any() and len(xs) > 1:
            cx, cy = one_edge_centre(xs, edge, sign * inner, seen)
            target_x, target_y = np.where(one, cx, target_x), np.where(one, cy, target_y)
    point, curvature, band = _centre_target(target_x[::-1], target_y[::-1], lookahead)
    point, curvature, band = _observed_target((point, curvature, band), target_x[::-1], target_y[::-1], lookahead, way, ground, x_offset)
    if point is not None:
        out["target_m"] = (round(point[0], 3), round(point[1], 3))
        out["curvature_1pm"] = round(curvature, 3)
        out["both"] = bool(np.mean(~open_left[band[::-1]] & ~open_right[band[::-1]]) >= 0.5)
    return out


# Legacy defaults; runtime instances use the effective CORE law.
CORE_STEERING_GAIN, CORE_MIN_CONFIDENCE, CORE_CURVE_SLOWDOWN, CORE_CRUISE_MPS = 0.8, 0.35, 0.65, 0.08
MAX_CRUISE_MPS = 0.10


def error_for_k(curvature, confidence, *, cruise_speed=CORE_CRUISE_MPS,
                steering_gain=CORE_STEERING_GAIN, min_confidence=CORE_MIN_CONFIDENCE):
    """Invert the loaded CORE law, preserving geometric curvature (1/m, left +)."""
    span = 1.0 - min_confidence
    scale = 1.0 if span == 0.0 else max(0.0, min(1.0, (confidence - min_confidence) / span))
    speed = cruise_speed * scale
    kc = abs(curvature) * speed
    error = kc / (steering_gain + CORE_CURVE_SLOWDOWN * kc) if speed > 0.0 else 1.0
    return float(-math.copysign(min(1.0, error), curvature))


def pursuit_error(tx, ty, confidence, **law):
    """Invert CORE's law for the arc k=2y/(x*x+y*y), preserving curvature under angular caps."""
    d2 = tx * tx + ty * ty
    if d2 < 1e-6:
        return 0.0
    return error_for_k(2.0 * ty / d2, confidence, **law)


class DrivableSteer:
    """Keep-mode steering from the newest drivable way. Memory: the pivot and turn-side latches, the
    last opening seen, the smoothed commanded curvature, and the boundary memory (way edges seen, in
    odometry) that keeps the body off lines the camera no longer sees."""

    @classmethod
    def from_config(cls, raw):
        return cls(cruise_speed=min(float(raw.get('cruise_speed', CORE_CRUISE_MPS)),
                                    float(raw.get('max_linear', MAX_CRUISE_MPS))),
                   steering_gain=float(raw.get('steering_gain', CORE_STEERING_GAIN)),
                   min_confidence=float(raw.get('min_confidence', CORE_MIN_CONFIDENCE)))

    def __init__(self, *, cruise_speed=CORE_CRUISE_MPS, steering_gain=CORE_STEERING_GAIN,
                 min_confidence=CORE_MIN_CONFIDENCE):
        if (not all(math.isfinite(v) for v in (cruise_speed, steering_gain, min_confidence))
                or not 0. < cruise_speed <= MAX_CRUISE_MPS or steering_gain <= 0.
                or not 0. < min_confidence <= 1.):
            raise ValueError('invalid CORE steering law')
        self.steering_law = dict(cruise_speed=cruise_speed, steering_gain=steering_gain,
                                min_confidence=min_confidence)
        self._error_for_k = partial(error_for_k, **self.steering_law)
        self.pursuit_error = partial(pursuit_error, **self.steering_law)
        self._pivot_confidence = min_confidence   # exactly 0 linear under CORE's speed scale (PIVOT_CONFIDENCE)
        self._key = None
        self._target = None
        self._pivot = None
        self._smoothed = None
        self._side = self._route_exit = None
        self._memory = None
        self._edges = []
        self._pivot_yaw = None
        self._crosswalk_pose = None
        self._lost_since = None
        self._ctx = {}
        self._misaligned_since = None
        self.decisions = collections.deque(maxlen=16)       # (t, s, strategy, outcome)
        self._last_out = self._pending = None

    def _forget_latches(self):
        if '_route_bridge' in self.__dict__:
            self._route_bridge.invalidate_alignment()
        self._key = self._target = self._pivot = self._smoothed = self._side = self._memory = self._route_exit = None
        self._pivot_yaw = None
        self._crosswalk_pose = None
        self._edges = []
        self._lost_since = None

    def reset(self):
        """Drop latches and any expected-path coast. An exception in the node calls this."""
        self._forget_latches()
        self._expected_path = None
        self._last_out = self._pending = None

    def lost(self, stamp):
        """No fresh way this frame: forget the latch only after FORGET_S without one.

        The expected-path coast is not a latch. Forgetting the pivot must not end it at
        1.5 s while its own budget still runs to 2.5 s.
        """
        if self._lost_since is None:
            self._lost_since = stamp
        elif stamp - self._lost_since > FORGET_S:
            self._forget_latches()

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

    def update(self, *args, guide_s=None, guide_fresh=True, observed_only=False, current_stamp=None, **kw):
        """_update with the driving context: the realign rule, a strategy switch only after two
        consecutive frames (a HOLD applies at once), and the decision history."""
        here = kw.get("guide_here_deg", kw.get("guide_deg"))
        self._ctx = dict(s=guide_s, fresh=guide_fresh, here=here or 0.0, guide=kw.get("guide_deg") is not None,
                         ahead=kw.get("guide_deg"), stamp=current_stamp)
        error, confidence, info = self._update(*args, **kw)
        error, confidence, info = observed_route_candidate(error, confidence, info, observed_only=observed_only, owner=self,
            pose=args[6] if len(args) > 6 else kw.get('current_pose'),
            source_pose=args[5] if len(args) > 5 else kw.get('source_pose'), current_stamp=current_stamp,
            observation_stamp=args[1] if len(args) > 1 else kw.get('way_key'))
        guide = kw.get("guide_deg")
        target = info.get("target_now_m")
        if error is not None and guide is not None and guide_fresh and target:
            bend = abs(guide - (guide if here is None else here))
            off = abs(math.degrees(math.atan2(target[1], target[0])) - guide)
            if off <= bend + REALIGN_DEG:
                self._misaligned_since = None
            elif self._misaligned_since is None:
                self._misaligned_since = time.monotonic()
            elif time.monotonic() - self._misaligned_since >= REALIGN_S:
                error = confidence = None
                info = dict(info, strategy="none", reason="realign", misaligned_deg=round(off, 1))
        strategy = info["strategy"]
        # entering or leaving a closed-way turn acts at once; the hysteresis is for flips between driving targets
        urgent = any(k in st for st in (strategy, (self._last_out or (0, 0, {"strategy": ""}))[2]["strategy"])
                     for k in ("pivot", "reorient", "off_line", "route_bridge", "route_look"))   # D-769 rev 1: no replay past the creep
        if error is not None and not urgent and self._last_out is not None and strategy != self._last_out[2]["strategy"]                 and self._last_out[0] is not None and self._pending != strategy:
            self._pending = strategy
            error, confidence, info = self._last_out[0], self._last_out[1], dict(info, strategy=self._last_out[2]["strategy"],
                                                                               switch_pending=strategy)
        else:
            self._pending = None
        self._last_out = (error, confidence, info)
        if not self.decisions or self.decisions[-1][2] != info["strategy"]:
            self.decisions.append((round(time.monotonic(), 1), guide_s, info["strategy"], info.get("reason")))
        info["context"] = dict(s=guide_s, fresh=guide_fresh, here_deg=here, ahead_deg=guide,
                               last=list(self.decisions)[-3:])
        return error, confidence, info

    def _update(self, way, way_key, ground, x_offset, half, source_pose=None, current_pose=None,
                wall_ahead_m=None, side_clear_m=None, guide_deg=None, guide_pivot_ok=True, guide_here_deg=None,
                front_sector_m=None):
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
            # CORE owns speed-dependent stopping; a distant wall must not invent a corner.
            if wall_ahead_m <= WALL_STANDOFF_M:
                info["ahead_m"] = min(info["ahead_m"], round(wall_ahead_m - WALL_STANDOFF_M, 3))
        if side_clear_m:
            # A wall beside the robot is no road (the floor between a wall corner and the tape reads as
            # an opening); keep right only between real openings (D-384 2).
            open_sides = [k for k in info["exit_reach_m"] if side_clear_m.get(k) is None or side_clear_m[k] >= SIDE_WALL_M]
            for key in ("exit", "seen_exit"):
                if info.get(key) is not None and info[key] not in open_sides:
                    info[key] = open_sides[0] if len(open_sides) == 1 and key == "seen_exit" else None
            info["side_clear_m"] = {k: (None if v is None else round(v, 3)) for k, v in side_clear_m.items()}
            for remembered in (self._memory[0] if self._memory else None, self._side, self._pivot, self._route_exit[0] if self._route_exit else None):
                if remembered is not None and side_clear_m.get(remembered) is not None and side_clear_m[remembered] < SIDE_WALL_M:
                    self._memory = self._side = self._pivot = self._pivot_yaw = self._route_exit = None
        ahead, side, near = info["ahead_m"], info["exit"], info.get("exit_near", {info["exit"]: info["exit"] is not None})
        bridge, want = False, None
        if guide_deg is not None:
            # Route prior (Fleet guidance, D-511 rev 2: the lane direction ahead minus the heading):
            # the map knows which way the road goes where the camera sees two openings or none.
            info["guide_deg"] = round(guide_deg, 1)
            bridge = abs(guide_deg) < GUIDE_STRAIGHT_DEG
            # wrong way is judged on the lane direction here, not 0.25 m ahead (a hairpin ahead is a turn)
            here = guide_deg if guide_here_deg is None else guide_here_deg
            # ... and agreed 0.25 m ahead: g7-9dfk held 344 frames on a polyline joint (here > 90, ahead 16)
            if abs(guide_deg) <= GUIDE_REVERSE_DEG:
                here = guide_deg
            if abs(here) > GUIDE_REVERSE_DEG and not guide_pivot_ok:
                # facing against the lane where the turn circle does not fit (a 0.16 m lane, not one of
                # the ring-entry turn spots): no U-turn in the lane, HOLD for Fleet (architect 2026-10-10)
                self._smoothed = self._pivot = self._side = self._route_exit = None
                return None, None, dict(info, strategy="none", reason="wrong_way_hold", reorient_deferred=True)
            elif abs(here) > GUIDE_REVERSE_DEG:
                # facing against the lane: turn in place toward its direction (user 2026-10-10: when
                # the direction is wrong, set it right; 9dfk 20261010T042913Z_rosy_41 U-turned at the
                # S-curve top and drove the loop backwards)
                self._smoothed = self._pivot = self._side = self._route_exit = None
                error = -PIVOT_ERROR if here > 0 else PIVOT_ERROR
                return error, self._pivot_confidence, dict(info, strategy="drivable_reorient_" + ("left" if here > 0 else "right"))
            want = None if abs(guide_deg) < EXIT_BEND_DEG or info.get("reorient_deferred") else (
                "left" if guide_deg > 0 else "right")
            if want is None:
                # the map lane goes on: no exit turn or pivot; a way cut short (blue tape, cable)
                # is bridged along the lane below (user 2026-10-10: the map is the route reference)
                side = info["exit"] = None
                self._pivot = self._side = None
            elif want in info["exit_reach_m"] and near.get(want) and (not side_clear_m or want in open_sides):
                side = info["exit"] = want
            elif side is not None and side != want:
                side = info["exit"] = None      # an opening against the route is not taken
            self._side = side if side is not None else self._side
        # ... unless the route turns there: a ring's outer line remembered across its exit (v2 lap r23 NW)
        if side is not None and side != want and current_pose is not None and _crosses(
                seen, *_to_current(info["exit_point_m"][side], source_pose, current_pose)) is not None:
            # an "opening" beyond a boundary seen earlier is a strip past a line, not a road
            # (p8: exit right at y -0.17 m by the crosswalk, beyond the lane's boundary line)
            side = info["exit"] = None
            info["exit_behind_line"] = True
            # The same rejected opening cannot return through the memory or turn latch below.
            info["seen_exit"] = None
            self._memory = self._side = self._pivot = self._pivot_yaw = self._route_exit = None
        # Exit memory: an opening seen on the way in leaves the view near the corner (the camera
        # sees ~+-30 deg and ~0.37 m), so a closed way pivots toward the last opening seen within
        # EXIT_MEMORY_M of travel (8kcn at the SE spoke's foot, 9dfk at the top-left corner).
        if near.get(side or info.get("seen_exit")):
            self._memory = (side or info["seen_exit"], source_pose)
        if self._memory is not None and current_pose is not None and self._memory[1] is not None and math.hypot(
                current_pose[0] - self._memory[1][0], current_pose[1] - self._memory[1][1]) > EXIT_MEMORY_M:
            self._memory = None
        # A way whose target runs on ahead is no corner, whatever closed the short straight corridor: on
        # the camera's near rows a few cm wide, one blob of non-way by a line read ahead 0 (v2 lap r12
        # pivoted from memory 0.1 m before the NE bend and left the lane).
        target = info["target_m"]
        straight_on = (target is not None and target[0] >= BEND_ON_X_M
                       and abs(math.degrees(math.atan2(target[1], target[0]))) < TARGET_SIDE_DEG
                       and (wall_ahead_m is None or wall_ahead_m > target[0]))   # a LiDAR wall short of it closes
        info["straight_on"] = straight_on
        if (side is None and ahead < PIVOT_AHEAD_M and self._memory is not None and not straight_on
                and (want is None or want == self._memory[0])):
            side = info["exit"] = self._memory[0]
            info["exit_from_memory"] = True
        if side is None and ahead < PIVOT_AHEAD_M and info["target_m"] is not None:
            # No border opening or memory: the pursuit target names the side unless beyond a seen line.
            # Closed at the body, pivot only: the arc clipped the inner line at v2 lap r11's tight corner.
            target_now = _to_current(info["target_m"], source_pose, current_pose)
            bearing = math.degrees(math.atan2(target_now[1], target_now[0]))
            target_side = "left" if bearing > 0 else "right"
            beyond = info.get("exit_behind_line") or current_pose is not None and _crosses(
                seen, *_to_current(info["target_m"], source_pose, current_pose)) is not None
            if (abs(bearing) >= TARGET_SIDE_DEG and (not beyond or ahead < PIVOT_AT_BODY_M)
                    and (want is None or want == target_side)):
                side = info["exit"] = target_side
                info["exit_point_m"] = dict(info["exit_point_m"], **{side: tuple(info["target_m"])})
                info["exit_from_target"] = True
        if side is None and want is not None and ahead < PIVOT_AHEAD_M and not straight_on:
            # No observed opening: the route names a look direction; CORE checks rotation clearance.
            side = info["exit"] = want
            info["exit_from_guide"] = True
        # The side chosen at a closing bend or junction is kept until the way runs ahead again (9dfk 20261010T001349Z weaved at the ring's SE exit)
        if self._side is not None and ahead >= TURN_RELEASE_M:
            self._side = None
        if self._side is None and ahead < LOOKAHEAD_M and side is not None:
            self._side = side
        side = route_exit_point(self, info, side, want, source_pose, current_pose, way_key, side_clear_m)
        if straight_on and ahead < PIVOT_AHEAD_M:
            side = info["exit"] = None      # no turn in place while the way runs on ahead (see straight_on)
        # CORE stops forward motion for a return in its +-45 deg front sector inside its stop distance (v2 lap
        # r17, a lane 0.12 m from a wall): turn in place (0 linear, PIVOT_CONFIDENCE) toward the target until clear.
        front_blocked = (front_sector_m is not None and front_sector_m < FRONT_STOP_M
                         and info["target_m"] is not None)
        if front_blocked:
            side = info["exit"] = want or ("left" if info["target_m"][1] >= 0.0 else "right")
            info["front_blocked_m"] = round(front_sector_m, 3)
        # A turn in place runs until the way runs on ahead (or the other side opens), not until one frame names
        # no side (v2 lap r13 arced out wide to the wall that way); PIVOT_MAX_RAD still bounds it.
        if self._pivot is not None and not front_blocked and (
                ahead >= PIVOT_RELEASE_M or straight_on or side not in (None, self._pivot)):
            self._pivot = None
        if info.get("straddle") is not None and not self._in_crosswalk(current_pose):
            # off the line first: turn toward the way (CORE creeps back while its IR sees the line,
            # D-344 §12 amendment 3), then the normal rules
            self._smoothed = self._pivot = None
            error = -PIVOT_ERROR if info["straddle"] == "left" else PIVOT_ERROR
            return error, self._pivot_confidence, dict(info, strategy=f"drivable_off_line_{info['straddle']}")
        if not front_blocked and self._in_crosswalk(current_pose) and (guide_deg is None or abs(guide_deg) < EXIT_BEND_DEG):
            # (only where the map lane goes straight on: g10-9dfk held 822 frames "crosswalk straight"
            # into the wall at the SW 90-degree corner, the corner's transverse line read as bars)
            # Crosswalk bars, a speed bump or a cable cut the way short there; the lane goes straight
            # across. No pivot or exit turn: centre steering only, and CORE's D-573 gate stops, looks
            # and crosses (p8/p10: pivots at the bottom-road crosswalk became U-turns).
            side = self._pivot = self._side = self._route_exit = None
            info["crosswalk_hold"] = True
            if ahead < LOOKAHEAD_M:
                self._smoothed = 0.0 if self._smoothed is None else self._smoothed
                return 0.0, ONE_CONFIDENCE, dict(info, strategy="drivable_crosswalk_straight")
        if self._pivot is None and not front_blocked and (side in info["exit_reach_m"] or info.get("exit_from_route_memory") and ahead
                < PIVOT_AHEAD_M) and (info.get("near_centre_m") or (0, 0))[1] * (1 if side == "left" else -1) <= -RECENTRE_M:
            side = info["exit"] = self._side = None   # arcs too: the south spoke cut its bend 0.2 m early (r50b)
            info["recentre_first"] = True
        turn_target = info['exit_point_m'].get(side, target)
        if self._pivot is None and side is not None and (front_blocked or ahead < PIVOT_AHEAD_M and (
                guide_deg is None or abs(guide_deg) >= PIVOT_GUIDE_DEG
                or any(info.get(f'exit_from_{origin}') for origin in ('guide', 'target', 'memory')) and target is not None
                and _to_current(turn_target, source_pose, current_pose)[1] * (1 if side == 'left' else -1) < 0.0)):
            self._pivot = side
            self._pivot_yaw = None if current_pose is None else current_pose[2]
        if self._pivot is None:
            self._pivot_yaw = None
        elif self._pivot_yaw is not None and current_pose is not None and abs(
                math.atan2(math.sin(current_pose[2] - self._pivot_yaw), math.cos(current_pose[2] - self._pivot_yaw))) > PIVOT_MAX_RAD:
            # Budget spent: drop the turn and its memories and carry on with what is in front (a
            # sticky stop here held 9dfk LOST for good, 20261010T040459Z_rosy_41).
            self._pivot = self._side = self._memory = self._pivot_yaw = self._route_exit = None
            side = info["exit"] = None
            info["pivot_limit"] = True
        if self._pivot is not None:
            self._smoothed = None
            error = -PIVOT_ERROR if self._pivot == "left" else PIVOT_ERROR
            return error, self._pivot_confidence, dict(info, strategy=f"drivable_pivot_{self._pivot}")
        if (guide_deg is not None and bridge and side is None and (info["target_m"] is None or ahead < PIVOT_AHEAD_M)
                and (wall_ahead_m is None or wall_ahead_m - WALL_STANDOFF_M >= PIVOT_AHEAD_M)   # map bridge (route_guard bounds it):
                and _crosses(seen, LOOKAHEAD_M, LOOKAHEAD_M * math.tan(math.radians(guide_deg))) is None):  # no line seen across
            self._smoothed = None
            error = self.pursuit_error(LOOKAHEAD_M, LOOKAHEAD_M * math.tan(math.radians(guide_deg)), ONE_CONFIDENCE)
            return error, ONE_CONFIDENCE, dict(info, strategy="drivable_map_bridge")
        bends_on = info["target_m"] is not None and info["target_m"][0] >= BEND_ON_X_M
        if info["target_m"] is None or ahead < PIVOT_AHEAD_M and side is None and ahead < 0.12 and not bends_on:
            self._smoothed = None
            return None, None, dict(info, strategy="none", reason=info.get("reason") or "drivable_closed")
        strategy, target = "drivable_centre", info["target_m"]
        opening = info["exit_point_m"].get(side)
        route_turn = (side == want and near.get(side) and self._ctx.get("fresh") and opening is not None
                      and source_pose is not None and current_pose is not None
                      and _to_current(opening, source_pose, current_pose)[0] > 0.0)
        if side is not None and (ahead < LOOKAHEAD_M or route_turn):
            # A selected near route branch is taken even when another road runs straight on.
            strategy, target = f"drivable_turn_{side}", info["exit_point_m"].get(side, info["target_m"])   # a remembered side may be out of view
        tx, ty = _to_current(target, source_pose, current_pose)
        # The boundary memory only rejects exits (above). Clamping the target with it made most pivots:
        # independent replay, p8 17 of 19 pivot episodes followed a clamp, wobble 4.3 -> 0.3 /min without.
        d2 = tx * tx + ty * ty
        curvature = 0.0 if d2 < 1e-6 else 2.0 * ty / d2
        self._smoothed = curvature if self._smoothed is None else SMOOTHING * self._smoothed + (1 - SMOOTHING) * curvature
        confidence = BOTH_CONFIDENCE if info["both"] else ONE_CONFIDENCE
        error = self._error_for_k(self._smoothed, confidence)
        length = math.hypot(tx, ty)
        if abs(self._smoothed) < 1e-3:
            shown = (length, ty)
        else:
            shown = (math.sin(self._smoothed * length) / self._smoothed,
                     (1.0 - math.cos(self._smoothed * length)) / self._smoothed)
        return error, confidence, dict(info, strategy=strategy,
                                       target_now_m=(round(shown[0], 3), round(shown[1], 3)),
                                       curvature_1pm=round(self._smoothed, 3))

