"""Subject: lane keeping ('keep' mode) on a real, near-horizontal camera (D-364 §2).

A lane keeper, not a line tracer: the target is the middle of the lane the
robot is in, never the tape. Per frame, no odometry:

  floor mask    white = bright relative to the carpet of the same image row
                (a low percentile of the row, so tape covering half a row does
                not raise its own threshold) and low saturation (blue wall
                tape, the pilot overlay and yellow/black signs drop out); only
                below the horizon and below the base of the white walls. A
                wall is a bright run that starts above the horizon; per image
                column its base is where that run ends (turns dark, or drops a
                step: tape laid along the base is bright but darker than the
                wall), median-filtered across columns so a far tape line
                touching the wall is not eaten. Its brightness bound comes from
                the darkest floor too, so a wall filling most rows is found.
  bird's-eye    the mask sampled on the lane_bev robot-frame floor grid
                (base_link, x ahead, y LEFT positive, REP 103), so width and
                heading are metres and radians, not pixels
  boundaries    straight ground lines found by RANSAC on the lit cells. A line
                whose flanks are lit too is a blob (a wall wedge, glare), not
                tape, and is dropped; so is one crossing the path at more than
                TRANSVERSE_MIN_ANGLE_RAD (stop lines, crosswalks: those belong
                to the traffic policy, D-151)
  side          each boundary's lateral offset at the lookahead decides left
                (y > 0) or right (y < 0) -- ground geometry, not image row
                position; a line almost under the robot takes its side from the
                previous target, and a line continuing one seen last frame
                (close in offset and heading) keeps that side until it lies
                clearly on the other side
  target        midpoint of the nearest left and right boundary that are a
                lane width apart; one side only: that boundary moved a
                half-width inward; none: no output (HOLD)
  corner        an L-corner shows a transverse line ahead that runs past the
                lane on one side only (the open side) -- the outer boundary of
                the lane after the turn. Its centre line is that line moved a
                half-width toward the robot; the robot pursues the corner path
                (straight on, then along that centre line toward the open side)
                at CORNER_LOOKAHEAD_M, and goes straight while the corner is
                further. Near the corner the open side is out of view, so the
                side is latched (frame count, no pose) while a transverse line
                stays ahead. Opt-in (corner_turning; the node's
                lane_corner_turning, off on the device).

Output keeps the lane contract: error > 0 means steer right (CORE:
angular = -gain * error); error = -target_y / lane_half_width, clipped to
[-1, 1] -- the target's lateral offset at the lookahead, which also carries
the heading error (lookahead x heading), like `detect_lane_centre`. Not the
pure-pursuit curvature law of the odometry modes: at CORE's gain 0.8 and
~0.05 m/s this loop is overdamped (poles ~ -0.24 and -1.9 1/s), while the
pursuit law is underdamped and five times softer on a one-sided target. `last` holds a debug bundle for the pilot overlay and the replay
bench. Short temporal smoothing uses previous targets only (no pose).
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from .lane import LaneObservation
from .lane_bev import BirdsEye
from .lane_keep_lines import (  # noqa: F401 — re-exported for callers and tests
    CORE_HALF_M,
    FLANK_INNER_M,
    FLANK_OUTER_M,
    MAX_FLANK_RATIO,
    MAX_ONE_FLANK_RATIO,
    MIN_LINE_LENGTH_M,
    MIN_LINE_CELLS,
    MAX_GAP_M,
    RANSAC_HYPOTHESES,
    MAX_LINES,
    HORIZON_MARGIN_PX,
    CARPET_PERCENTILE,
    CARPET_ROW_WINDOW,
    CARPET_ROW_EXCESS,
    MIN_CONTRAST,
    CONTRAST_HEADROOM,
    MAX_SATURATION,
    WALL_START_ABOVE_HORIZON_PX,
    WALL_MEDIAN_COLUMNS,
    WALL_BASE_MARGIN_PX,
    WALL_TAPE_STEP,
    WALL_CARPET_PERCENTILE,
    WALL_STEP_ROWS,
    _validate_positive,
    extract_lines,
    floor_white_mask,
)

#: Lookahead from base_link where the lane centre is read.
LOOKAHEAD_M = 0.25
#: Boundaries are sided and paired by their lateral offset this far ahead of
#: base_link: inside the camera's floor view, where NOMINAL geometry errs least.
SIDE_X_M = 0.22
#: A boundary line may be extrapolated this far past its seen paint.
MAX_EXTRAPOLATION_M = 0.15
#: Lines are fitted on the bird's-eye grid thinned to this cell (2 lane_bev cells).
FIT_STRIDE = 2
#: A line this far off the robot's heading is a transverse mark.
TRANSVERSE_MIN_ANGLE_RAD = math.radians(65.0)
#: A line steeper than this whose extrapolated offset at SIDE_X_M lies beyond
#: STEEP_MAX_LATERAL_FRACTION of the lane width is a diagonal mark (a junction
#: mouth, a crosswalk edge) read far outside the lane, not a boundary. Real
#: 124745Z frames sided 60-64 deg lines at y -0.30..-0.42 m. Both ends of the
#: seen paint must also lie beyond the lane half width plus STEEP_PAINT_MARGIN_M.
STEEP_MIN_ANGLE_RAD = math.radians(45.0)
STEEP_MAX_LATERAL_FRACTION = 1.0
STEEP_PAINT_MARGIN_M = 0.03
#: ... or reach within this of the robot's path line (y = 0) from both sides.
STEEP_PATH_M = 0.02
#: Two boundaries of one lane run within this angle of each other, and are
#: PAIR_MIN..PAIR_MAX_FRACTION of the lane width apart at SIDE_X_M and at both
#: ends of their common seen stretch (a pair closing to a narrow gap is not a
#: lane: real 124745Z frames 800-1017 paired a chord across crosswalk bars,
#: 0.50 lane wide at its near end and 18-20 deg off the lane line).
PAIR_MAX_ANGLE_RAD = math.radians(20.0)
#: Two boundaries on opposite sides that are not a pair, lie within
#: PAIR_MAX_FRACTION of the lane width of each other at SIDE_X_M and run more
#: than CONFLICT_MIN_ANGLE_RAD apart cannot both bound the lane: of two such
#: lines, both within CONFLICT_MAX_HEADING_RAD of the robot's heading, the one
#: with less paint along that heading is dropped (reason 'pair_conflict')
#: unless it pairs with another line. Real 124745Z frames sided such chords
#: across crosswalk bars and across the corner tape of a junction mouth
#: (frames 58-252, 800-1017). Parallel lines too close to pair stay (one is
#: chosen as a lone boundary); steeper lines (junction crossings) are left to
#: the steep and junction rules.
CONFLICT_MIN_ANGLE_RAD = math.radians(10.0)
CONFLICT_MAX_HEADING_RAD = math.radians(45.0)
#: A lone boundary further than this fraction of the lane width is not ours.
ONE_MAX_DISTANCE_FRACTION = 1.5
#: A boundary pair must be this fraction of the lane width apart.
PAIR_MIN_FRACTION = 0.6
PAIR_MAX_FRACTION = 1.6
#: A boundary nearer the robot than this takes its side from the last target.
AMBIGUOUS_LATERAL_M = 0.03
#: Temporal consistency (no odometry): a boundary within TRACK_LATERAL_M and
#: TRACK_HEADING_RAD of one seen last frame is the same boundary and keeps its
#: side until it lies more than SIDE_FLIP_M on the other side. (A per-frame
#: rate limit on the target was tried: it drags the target across the tape
#: when the side does flip, raising on_paint on the replay bench.)
TRACK_LATERAL_M = 0.06
TRACK_HEADING_RAD = math.radians(20.0)
SIDE_FLIP_M = 0.08
#: Junctions fail closed (HOLD): a lone boundary with a line across the path
#: within JUNCTION_AHEAD_M that is not a latched corner, or two boundaries on
#: the followed side splitting by more than FORK_MIN_ANGLE_RAD. Steering of at
#: least FLIP_MIN_ERROR that reverses FLIP_MAX_REVERSALS times within
#: FLIP_WINDOW_FRAMES frames holds too. A corner's open side must have no
#: boundary running past the corner line (less CORNER_PAST_MARGIN_M).
JUNCTION_AHEAD_M = 0.45
FORK_MIN_ANGLE_RAD = math.radians(30.0)
DIVERGE_MIN_RAD = math.radians(15.0)
#: Both branches of a fork are real paint, not a far fragment.
FORK_MIN_LENGTH_M = 0.12
FLIP_MIN_ERROR = 0.5
FLIP_MAX_REVERSALS = 2
FLIP_WINDOW_FRAMES = 16
CORNER_PAST_MARGIN_M = 0.03
#: Confidence: both boundaries / one boundary (CORE drives slower on one).
BOTH_CONFIDENCE = 0.9
ONE_CONFIDENCE = 0.6
MAX_POINTS = 6000
#: Lit fraction of the floor above which the frame is washed out.
WASHED_FRACTION = 0.5
#: Corners: the lookahead on the corner path (shorter than LOOKAHEAD_M, or the
#: robot cuts the inner corner), how far ahead a corner line may be, how far
#: past the lane (beyond the half-width) and how much further than the other
#: end its open end must run, and for how many frames without a line across
#: the path a seen side stays latched (it holds while such a line stays ahead).
CORNER_LOOKAHEAD_M = 0.12
CORNER_MAX_AHEAD_M = 0.45
CORNER_OPEN_M = 0.02
CORNER_ASYMMETRY_M = 0.02
#: The closed end sits on the outer lane line: within this of the half-width.
CORNER_CLOSED_TOLERANCE_M = 0.03
CORNER_LATCH_FRAMES = 12
#: A corner line within this of square to the heading means the turn has not
#: started (go straight until the corner); past it the robot is mid-turn and
#: pursues the new centre line at no less than its distance + CORNER_REACH_M.
CORNER_SQUARE_RAD = math.radians(10.0)
CORNER_REACH_M = 0.04
#: While a corner is latched, a line this steep to the heading is still the
#: corner line (the next lane's outer boundary seen mid-turn).
CORNER_MIN_HEADING_RAD = math.radians(35.0)
#: |error| cap while turning a corner (CORE angular = 0.8 * error).
CORNER_MAX_ERROR = 0.6


class LaneKeeper:
    """Keep the middle of the lane on a real camera ('keep' mode). No odometry;
    the only memory is the last frame's target and boundaries."""

    def __init__(self, *, camera_x_offset_m: float = 0.0,
                 lookahead_m: float = LOOKAHEAD_M,
                 smoothing: float = 0.5, seed: int = 0,
                 corner_turning: bool = False) -> None:
        if (isinstance(camera_x_offset_m, bool)
                or not isinstance(camera_x_offset_m, (int, float))
                or not math.isfinite(camera_x_offset_m)):
            raise ValueError("camera_x_offset_m must be a finite number")
        _validate_positive("lookahead_m", lookahead_m)
        if (isinstance(smoothing, bool) or not isinstance(smoothing, (int, float))
                or not 0.0 <= smoothing < 1.0):
            raise ValueError("smoothing must be in [0, 1)")
        self._x_offset = float(camera_x_offset_m)
        self._lookahead = float(lookahead_m)
        self._smoothing = float(smoothing)
        self._seed = int(seed)
        self._corner_turning = bool(corner_turning)
        self._view = None
        self._view_key = None
        self._previous_target = None
        self._tracked = []
        self._steer_history = deque(maxlen=FLIP_WINDOW_FRAMES)
        self._flip_hold = False
        self._corner_side = None
        self._corner_frames = 0
        self._corner_engaged = False
        self.last: dict = {}

    def _forget(self) -> None:
        """No usable view: the next frame is judged afresh (no inherited
        target, sides or steering history); a latched corner keeps counting."""
        self._previous_target = None
        self._tracked = []
        self._steer_history.clear()

    def reset(self) -> None:
        self._previous_target = None
        self._tracked = []
        self._steer_history.clear()
        self._flip_hold = False
        self._corner_side = None
        self._corner_frames = 0
        self._corner_engaged = False
        self.last = {}

    def _birds_eye(self, ground, width: int, height: int) -> BirdsEye:
        key = (id(ground), ground.height_m, ground.pitch_rad, ground.focal_px,
               ground.principal_x, ground.principal_y, width, height)
        if key != self._view_key:
            self._view = BirdsEye(ground, width, height, self._x_offset)
            self._view_key = key
        return self._view

    def to_pixel(self, ground, x: float, y: float):
        """(column, row) of a base_link floor point, or None behind the camera."""
        forward = x - self._x_offset
        if forward <= 0.0:
            return None
        ray = math.atan2(ground.height_m, forward) - ground.pitch_rad
        row = ground.principal_y + ground.focal_px * math.tan(ray)
        denominator = (ground.focal_px * math.sin(ground.pitch_rad)
                       + (row - ground.principal_y) * math.cos(ground.pitch_rad))
        column = ground.principal_x - y * denominator / ground.height_m
        return (round(column, 1), round(row, 1))

    def update(self, bgr: np.ndarray, ground, *, lane_half_width_m: float = 0.0925,
               **_ignored) -> LaneObservation | None:
        _validate_positive("lane_half_width_m", lane_half_width_m)
        if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
            raise ValueError("camera frame must be a non-empty grayscale or BGR array")
        self.last = {"strategy": "none", "boundaries": [], "transverse": [], "candidates": [], "blobs": 0,
                     "lookahead_m": self._lookahead, "target_m": None, "target_px": None}
        if ground is None:
            self.last["reason"] = "no_ground"
            self._forget()
            return None
        half = float(lane_half_width_m)
        height, width = bgr.shape[:2]
        mask = floor_white_mask(bgr, ground.horizon_row)
        view = self._birds_eye(ground, width, height)
        grid = view.sample(mask)
        observable = int(view.observable.sum())
        lit = int(grid.sum())
        if observable == 0 or lit > WASHED_FRACTION * observable:
            self.last["reason"] = "washed"
            self._forget()
            return None
        coarse = grid[::FIT_STRIDE, ::FIT_STRIDE]
        cells = np.flatnonzero(coarse.ravel())
        points = np.stack([view.x[::FIT_STRIDE, ::FIT_STRIDE].ravel()[cells],
                           view.y[::FIT_STRIDE, ::FIT_STRIDE].ravel()[cells]], axis=1)
        rng = np.random.default_rng(self._seed)
        if len(points) > MAX_POINTS:
            points = points[rng.choice(len(points), MAX_POINTS, replace=False)]
        lines, blobs = extract_lines(points, rng) if len(points) else ([], [])
        self.last["blobs"] = len(blobs)
        previous = self._previous_target
        left, right, transverse = [], [], []
        for line in lines:
            centre, direction = line["centre"], line["direction"]
            heading = math.atan2(direction[1], direction[0])
            ends = [centre + direction * line["along"][0], centre + direction * line["along"][1]]
            record = {"heading_deg": round(math.degrees(heading), 1),
                      "length_m": round(line["along"][1] - line["along"][0], 3),
                      "ends_m": [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in ends],
                      "ends_px": [self.to_pixel(ground, float(p[0]), float(p[1])) for p in ends]}
            if abs(heading) > TRANSVERSE_MIN_ANGLE_RAD:
                self.last["transverse"].append(record)
                self.last["candidates"].append(dict(record, rejected=True, reason="transverse"))
                transverse.append((centre, direction, ends, False))
                continue
            if (self._corner_side is not None and abs(heading) > CORNER_MIN_HEADING_RAD
                    and (heading > 0.0) == (self._corner_side == "left")):
                # Mid-turn the next lane's outer line swings below the
                # transverse angle, leaning toward the open side (the old
                # lane's line leans the other way); while a corner is latched
                # it stays the corner line (it cannot pick the side).
                transverse.append((centre, direction, ends, True))
            # Side by ground geometry: the line's lateral offset (base_link y,
            # left +) where the lane is read. Almost under the robot, the last
            # target decides instead.
            lateral = _lateral_at(centre, direction, SIDE_X_M)
            # The seen paint itself must lie outside the lane on one side, or
            # reach across the robot's path (a diagonal junction mouth or
            # crossing mark ahead; real 124745Z frames 94/754/758). A short
            # steep boundary segment far ahead on a curve extrapolates far at
            # SIDE_X_M too, but its paint starts at the lane edge: it is kept.
            low, high = sorted(float(p[1]) for p in ends)
            paint_outside = low > half + STEEP_PAINT_MARGIN_M or high < -(half + STEEP_PAINT_MARGIN_M)
            paint_crosses = low <= STEEP_PATH_M and high >= -STEEP_PATH_M
            if (abs(heading) > STEEP_MIN_ANGLE_RAD and self._corner_side is None
                    and (paint_outside or paint_crosses)
                    and abs(lateral) > STEEP_MAX_LATERAL_FRACTION * 2.0 * half):
                self.last["candidates"].append(dict(record, y_at_side_x_m=round(lateral, 3), rejected=True,
                                                    reason="steep_crossing" if paint_crosses else "steep_far"))
                continue
            reference = 0.0
            if abs(lateral) < AMBIGUOUS_LATERAL_M and previous is not None:
                reference = previous[1]
            side = "left" if lateral > reference else "right"
            # The same boundary as last frame keeps its side while it stays
            # near the robot: a line drifting across under the camera is still
            # the boundary it was, not the next lane's.
            tracked = self._track(lateral, heading)
            if tracked is not None and abs(lateral) < SIDE_FLIP_M:
                side = tracked
            inward = (np.array([direction[1], -direction[0]]) if side == "left"
                      else np.array([-direction[1], direction[0]]))
            point, along = _pursuit_point(centre + inward * half, direction, self._lookahead)
            if not (line["along"][0] - MAX_EXTRAPOLATION_M <= along
                    <= line["along"][1] + MAX_EXTRAPOLATION_M):
                self.last["candidates"].append(dict(record, side=side, y_at_side_x_m=round(lateral, 3),
                                                    rejected=True, reason="extrapolation"))
                continue
            record.update(side=side, y_at_side_x_m=round(lateral, 3), tracked=tracked == side,
                          pursuit_m=[round(float(point[0]), 3), round(float(point[1]), 3)],
                          centre=centre, direction=direction)
            (left if side == "left" else right).append(record)
        # A dropped chord is still remembered with its side (self._tracked):
        # dropping it must not re-side it afresh when the conflict ends.
        conflicts = _pair_conflicts(left, right, half)
        for record in conflicts:
            (left if record["side"] == "left" else right).remove(record)
            self.last["candidates"].append(
                dict({k: v for k, v in record.items() if k not in ("centre", "direction")},
                     rejected=True, reason="pair_conflict"))
        target, strategy = self._choose(left, right, half)
        # A lane seen on both sides is followed; a corner is only looked for
        # when it is not (a line across between two lane lines is a stop
        # line, a crosswalk or a junction mouth, not an L-corner).
        corner = None
        if self._corner_turning and strategy != "both":
            corner = self._corner(transverse, half, left + right)
        if corner is not None and (target is None or corner[1] != "corner_ahead"):
            target, strategy = corner
        junction = (None if corner is not None
                    else _junction(strategy, transverse, left, right, half, self._corner_turning))
        if junction is not None:
            target = None
        self._tracked = [(r["y_at_side_x_m"], math.radians(r["heading_deg"]), r["side"])
                         for r in left + right + conflicts]
        for record in left + right:
            record.pop("direction")
            record.pop("centre")
            self.last["boundaries"].append(record)
            self.last["candidates"].append(dict(record, rejected=False, reason=None))
        if target is None:
            self.last["reason"] = junction or "no_boundary"
            # Nothing is pursued: the next frame sides its lines afresh (a
            # held robot sees the same frame again, and a side inherited
            # into a hold would otherwise hold it forever).
            self._previous_target = None
            self._tracked = []
            self._steer_history.append(0)
            return None
        if previous is not None and self._smoothing > 0.0 and not strategy.startswith("corner"):
            target = self._smoothing * np.asarray(previous) + (1.0 - self._smoothing) * target
        tx, ty = float(target[0]), float(target[1])
        self._previous_target = (tx, ty)
        confidence = BOTH_CONFIDENCE if strategy == "both" else ONE_CONFIDENCE
        if strategy == "both":
            self._corner_side, self._corner_frames, self._corner_engaged = None, 0, False
        error = max(-1.0, min(1.0, -ty / half))
        if strategy.startswith("corner_") and strategy != "corner_ahead":
            # CORE saturates at |error| ~ 0.9 (0.7 rad/s): a full-scale corner
            # command spins the robot on the inner corner. Capped, it arcs.
            error = max(-CORNER_MAX_ERROR, min(CORNER_MAX_ERROR, error))
        # With corner turning, hard steering that keeps reversing is two
        # readings fighting (a junction taken for a corner, a bend whose side
        # keeps flipping): hold instead of weaving out of the lane. Without it
        # (device default) the rule held 5-8 % more real replay frames
        # (teleop none 0.08 -> 0.13), so it stays off there.
        self._steer_history.append(0 if abs(error) < FLIP_MIN_ERROR else (1 if error > 0 else -1))
        signs = [v for v in self._steer_history if v]
        if (self._corner_turning
                and sum(1 for a, b in zip(signs, signs[1:]) if a != b) >= FLIP_MAX_REVERSALS):
            # Sticky: resuming after the window only weaves again. Only a
            # lane seen on both sides releases it.
            self._flip_hold = True
        if strategy == "both":
            self._flip_hold = False
        if self._flip_hold:
            self.last.update(strategy="none", reason="flipping")
            self._previous_target = None
            return None
        self.last.update(strategy=strategy, target_m=[round(tx, 3), round(ty, 3)],
                         target_px=self.to_pixel(ground, tx, ty),
                         error=round(error, 3), confidence=confidence)
        return LaneObservation(error=error, confidence=confidence)

    def _corner(self, transverse, half, boundaries=()):
        """(target, strategy) from the nearest L-corner line ahead, or None.
        Updates the latched corner side."""
        best = None
        for centre, direction, ends, steep in transverse:
            ys = sorted(float(p[1]) for p in ends)
            if ys[0] > half or ys[1] < -half:
                continue  # beside the path, not across it
            ahead = float(centre[0] - centre[1] * direction[0] / direction[1])
            if not 0.0 < ahead <= CORNER_MAX_AHEAD_M:
                continue
            if best is None or ahead < best[0]:
                best = (ahead, centre, direction, ys, steep)
        if best is None:
            if self._corner_frames > 0:
                self._corner_frames -= 1
            if self._corner_frames == 0:
                self._corner_side, self._corner_engaged = None, False
            return None
        ahead, centre, direction, ys, steep = best
        left_reach, right_reach = ys[1], -ys[0]
        side = None
        # A latched side is kept: mid-turn the corner line's ends swing and can
        # mimic the opposite corner.
        if (self._corner_side is None and not steep
                and max(left_reach, right_reach) > half + CORNER_OPEN_M
                and not _runs_past(boundaries, left_reach > right_reach, ahead)):
            # The closed end is where the corner line meets the outer lane line.
            if (left_reach - right_reach > CORNER_ASYMMETRY_M
                    and abs(right_reach - half) <= CORNER_CLOSED_TOLERANCE_M):
                side = "left"
            elif (right_reach - left_reach > CORNER_ASYMMETRY_M
                    and abs(left_reach - half) <= CORNER_CLOSED_TOLERANCE_M):
                side = "right"
        if side is not None:
            self._corner_side = side
        if self._corner_side is not None:
            if not steep:
                self._corner_frames = CORNER_LATCH_FRAMES
            else:
                # Steep lines only carry a turn already under way; a later
                # bend must not keep an old corner alive.
                self._corner_frames -= 1
                if self._corner_frames <= 0:
                    self._corner_side, self._corner_engaged = None, False
                    return None
        side = self._corner_side
        if side is None:
            return None  # a stop line or a T: not a corner
        # The new lane's centre line: the corner line moved half a lane toward
        # the robot, pursued toward the open side (left = +y).
        normal = np.array([-direction[1], direction[0]])
        if float(np.dot(normal, centre)) > 0.0:
            normal = -normal
        origin = centre + normal * half
        along = direction if (direction[1] > 0.0) == (side == "left") else -direction
        meet = float(origin[0] - origin[1] * along[0] / along[1])
        square = abs(math.atan2(direction[1], direction[0])) >= math.pi / 2 - CORNER_SQUARE_RAD
        if square and meet > CORNER_LOOKAHEAD_M and not self._corner_engaged:
            return np.array([CORNER_LOOKAHEAD_M, 0.0]), "corner_ahead"
        # Mid-turn the robot is already rotated toward the open side, so the
        # meeting point runs away along its heading: keep pursuing the new
        # centre line, never further than just past it.
        reach = abs(float(np.dot(normal, origin))) + CORNER_REACH_M
        point, _ = _pursuit_point(origin, along, max(CORNER_LOOKAHEAD_M, reach))
        # Once turning, never back to straight-on for this corner.
        self._corner_engaged = True
        return point, f"corner_{side}"

    def _track(self, lateral, heading):
        """Side of the last frame's boundary this line continues, or None."""
        best = None
        for previous_lateral, previous_heading, side in self._tracked:
            gap = abs(lateral - previous_lateral)
            if (gap <= TRACK_LATERAL_M and abs(heading - previous_heading) <= TRACK_HEADING_RAD
                    and (best is None or gap < best[0])):
                best = (gap, side)
        return None if best is None else best[1]

    def _choose(self, left, right, half):
        """Target (x, y) and strategy from the side-classified boundaries."""
        lane = 2.0 * half
        pairs = []
        for l in left:
            for r in right:
                if _pairs(l, r, lane):
                    pairs.append((l["y_at_side_x_m"] - r["y_at_side_x_m"], l, r))
        if pairs:
            # The nearest pair: the robot is inside it (adjacent lanes lie beyond).
            # Pursue the centre line: midway at SIDE_X_M, along the mean heading
            # (on a NOMINAL floor the two lines rarely come out exactly parallel).
            _, l, r = min(pairs, key=lambda p: p[0])
            middle = np.array([SIDE_X_M, (l["y_at_side_x_m"] + r["y_at_side_x_m"]) / 2.0])
            heading = l["direction"] + r["direction"]
            point, _ = _pursuit_point(middle, heading / np.linalg.norm(heading), self._lookahead)
            return point, "both"
        candidates = [r for r in left + right
                      if abs(r["y_at_side_x_m"]) <= ONE_MAX_DISTANCE_FRACTION * lane]
        if not candidates:
            return None, "none"
        # The boundary continuous with last frame's first, then the nearest.
        record = min(candidates, key=lambda r: (not r["tracked"], round(abs(r["y_at_side_x_m"]), 2),
                                                -r["length_m"]))
        return np.asarray(record["pursuit_m"], float), f"{record['side']}_only"


def _pairs(l, r, lane):
    """True when left boundary l and right boundary r can bound one lane."""
    if float(np.dot(l["direction"], r["direction"])) < math.cos(PAIR_MAX_ANGLE_RAD):
        return False
    lo = max(min(p[0] for p in l["ends_m"]), min(p[0] for p in r["ends_m"]))
    hi = min(max(p[0] for p in l["ends_m"]), max(p[0] for p in r["ends_m"]))
    xs = (SIDE_X_M, lo, hi) if lo < hi else (SIDE_X_M,)
    return all(PAIR_MIN_FRACTION * lane
               <= _lateral_at(l["centre"], l["direction"], x) - _lateral_at(r["centre"], r["direction"], x)
               <= PAIR_MAX_FRACTION * lane for x in xs)


def _pair_conflicts(left, right, half):
    """Boundaries dropped as 'pair_conflict' (see CONFLICT_MAX_HEADING_RAD):
    of each couple, the one with less paint along the robot's heading (length
    x cos^2 heading) -- a chord runs across the heading, a lane line along it."""
    lane = 2.0 * half

    def along(record):
        return record["length_m"] * math.cos(math.radians(record["heading_deg"])) ** 2

    dropped = []
    for l in left:
        for r in right:
            if (l["y_at_side_x_m"] - r["y_at_side_x_m"] > PAIR_MAX_FRACTION * lane or _pairs(l, r, lane)
                    or float(np.dot(l["direction"], r["direction"])) > math.cos(CONFLICT_MIN_ANGLE_RAD)
                    or max(abs(l["heading_deg"]), abs(r["heading_deg"]))
                    > math.degrees(CONFLICT_MAX_HEADING_RAD)):
                continue
            loser = min(l, r, key=along)
            partner = (any(_pairs(loser, o, lane) for o in right) if loser is l
                       else any(_pairs(o, loser, lane) for o in left))
            if not partner and not any(d is loser for d in dropped):
                dropped.append(loser)
    return dropped


def _across_path(ends, half):
    """Ahead distance where a (transverse) line crosses the path, or None."""
    ys = sorted(float(p[1]) for p in ends)
    if ys[0] > half or ys[1] < -half:
        return None
    (x0, y0), (x1, y1) = ((float(p[0]), float(p[1])) for p in ends)
    ahead = x0 if y1 == y0 else x0 + (x1 - x0) * (0.0 - y0) / (y1 - y0)
    return ahead if 0.0 < ahead <= JUNCTION_AHEAD_M else None


def _junction(strategy, transverse, left, right, half, corner_turning):
    """Reason to HOLD at a junction, or None. Only with corner turning: there
    the corner reading can pull the robot out of the lane at a junction mouth.
    Without it (the device default) both rules held 5-10 % more of the real
    replay frames (pilot none 0.32 -> 0.36-0.43), so the plain keeper goes on
    along its lone boundary as the bench measures."""
    if not corner_turning or strategy not in ("left_only", "right_only"):
        return None
    side = left if strategy == "left_only" else right
    # The lone boundary bends away out of the lane (a mouth opening on its
    # side) while a line crosses the path ahead: which lane goes on is unknown.
    outward = 1.0 if strategy == "left_only" else -1.0
    diverging = any(outward * math.radians(r["heading_deg"]) > DIVERGE_MIN_RAD for r in side)
    if diverging and any(not steep and _across_path(ends, half) is not None
                         for _, _, ends, steep in transverse):
        return "junction_transverse"
    headings = [math.radians(r["heading_deg"]) for r in side
                if abs(r["y_at_side_x_m"]) <= ONE_MAX_DISTANCE_FRACTION * 2.0 * half
                and r["length_m"] >= FORK_MIN_LENGTH_M]
    if headings and max(headings) - min(headings) > FORK_MIN_ANGLE_RAD:
        return "junction_fork"
    return None


def _runs_past(boundaries, open_left, ahead):
    """True when a boundary on the open side runs on past the corner line."""
    for record in boundaries:
        if (record["side"] == "left") != open_left:
            continue
        far = max(float(p[0]) for p in record["ends_m"])
        if far >= ahead - CORNER_PAST_MARGIN_M:
            return True
    return False


def _lateral_at(centre, direction, x) -> float:
    return float(centre[1] + (x - centre[0]) * direction[1] / direction[0])


def _pursuit_point(origin, direction, radius):
    """Point of the line origin + t*direction at `radius` from base_link, ahead
    (the larger root); the closest point when the line passes further away.
    Returns (point, t)."""
    b = float(np.dot(origin, direction))
    disc = b * b - float(np.dot(origin, origin)) + radius * radius
    t = -b + math.sqrt(disc) if disc > 0.0 else -b
    return origin + direction * t, t
