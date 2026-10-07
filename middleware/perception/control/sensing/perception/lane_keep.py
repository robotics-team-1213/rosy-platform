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
                clearly on the other side, and no longer than SIDE_FLIP_FRAMES
                frames of sitting on the wrong side of the robot
  pairs         lane_keep_pairs: near-parallel and a lane width apart along
                their common stretch; a close skew couple that is no pair
                drops the weaker line ('pair_conflict')
  target        midpoint of the nearest pair; one side only: that boundary
                moved a half-width inward; none: no output (HOLD)
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
~0.05 m/s this loop is overdamped (poles ~ -0.24 and -1.9 1/s). One-sided and
paired targets steer with the same gain; one side costs speed, since
confidence is CORE's speed scale ((c - 0.35) / 0.65: BOTH_CONFIDENCE 0.9 ->
0.85, ONE_CONFIDENCE 0.6 -> 0.38). `last` holds a debug bundle for the pilot
overlay and the replay bench. Short temporal smoothing uses previous targets only (no pose).
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from .lane import LaneObservation
from .crosswalk_stripes import crosswalk_extent
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
    clean_learned_mask,
    denoise_white_mask,
    extract_lines,
    floor_white_mask,
)
from .lane_keep_pairs import (  # noqa: F401 — re-exported; patch constants on lane_keep_pairs
    CONFLICT_MAX_HEADING_RAD,
    CONFLICT_MIN_ANGLE_RAD,
    PAIR_MAX_ANGLE_RAD,
    PAIR_MAX_FRACTION,
    PAIR_MIN_FRACTION,
    _lateral_at,
    is_pair,
    pair_conflicts,
)
from .lane_keep_junction import (  # noqa: F401 — re-exported; patch constants on lane_keep_junction
    DIVERGE_MIN_RAD,
    FORK_MIN_ANGLE_RAD,
    FORK_MIN_LENGTH_M,
    JUNCTION_AHEAD_M,
    _across_path,
    _junction,
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
#: mouth, a crosswalk edge) when its paint is outside the lane or meets the path.
#: Paint spanning both lane edges is a crossing even without that far offset.
#: Real 124745Z frames projected transverse marks at 60-64 deg.
STEEP_MIN_ANGLE_RAD = math.radians(45.0)
STEEP_MAX_LATERAL_FRACTION = 1.0
STEEP_PAINT_MARGIN_M = 0.03
#: ... or reach within this of the robot's path line (y = 0) from both sides.
STEEP_PATH_M = 0.02
#: A lone boundary further than this fraction of the lane width is not ours.
ONE_MAX_DISTANCE_FRACTION = 1.5
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
#: ... and for at most this many frames while its lateral offset sits on the
#: other side of the robot beyond AMBIGUOUS_LATERAL_M. A line crossing under
#: the camera is through in a frame or two at the 8 fps camera, but session
#: 20261005T134540Z (9dfk, frames 329-367) held a boundary at y -0.05..-0.07
#: on its stale 'left' side while the robot drove along it: the one-sided
#: target landed a half-width past the right tape and the error pinned at
#: +1.0 toward the next lane for 20+ frames. Past this many contradicting
#: frames the fresh ground side wins.
SIDE_FLIP_FRAMES = 4
#: Junctions fail closed (HOLD) when corner turning is on; the rules and their
#: constants live in lane_keep_junction (patch them there). Steering of at
#: least FLIP_MIN_ERROR that reverses FLIP_MAX_REVERSALS times within
#: FLIP_WINDOW_FRAMES frames holds too. A corner's open side must have no
#: boundary running past the corner line (less CORNER_PAST_MARGIN_M).
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
               paint_mask: np.ndarray | None = None, **_ignored) -> LaneObservation | None:
        """paint_mask (D-408): an HxW 0/1 paint mask from another source (learned model,
        OpenCV glare filter) used in place of floor_white_mask; rows above the horizon
        margin are dropped from it."""
        _validate_positive("lane_half_width_m", lane_half_width_m)
        if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
            raise ValueError("camera frame must be a non-empty grayscale or BGR array")
        self.last = {"strategy": "none", "boundaries": [], "transverse": [], "candidates": [], "blobs": 0,
                     "lookahead_m": self._lookahead, "target_m": None, "target_px": None,
                     "lane_width_m": 2.0 * lane_half_width_m}
        if ground is None:
            self.last["reason"] = "no_ground"
            self._forget()
            return None
        half = float(lane_half_width_m)
        height, width = bgr.shape[:2]
        if paint_mask is None:
            mask = floor_white_mask(bgr, ground.horizon_row)
        else:
            if not isinstance(paint_mask, np.ndarray) or paint_mask.shape != bgr.shape[:2]:
                raise ValueError("paint_mask must be an array of the frame's height x width")
            mask = (paint_mask > 0).astype(np.uint8)
            mask[:max(0, min(height, int(math.ceil(ground.horizon_row)) + HORIZON_MARGIN_PX))] = 0
        view = self._birds_eye(ground, width, height)
        grid = view.sample(mask)
        observable = int(view.observable.sum())
        lit = int(grid.sum())
        if observable == 0 or lit > WASHED_FRACTION * observable:
            self.last["reason"] = "washed"
            self._forget()
            return None
        self.last["crosswalk"] = crosswalk_extent(grid, view.x[:, 0], view.y[0, :])  # D-491 §4
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
            paint_spans_lane = low < -half and high > half
            far_lateral = abs(lateral) > STEEP_MAX_LATERAL_FRACTION * 2.0 * half
            if (abs(heading) > STEEP_MIN_ANGLE_RAD and self._corner_side is None
                    and (paint_spans_lane or ((paint_crosses or paint_outside) and far_lateral))):
                self.last["candidates"].append(dict(record, y_at_side_x_m=round(lateral, 3), rejected=True,
                                                    reason="steep_crossing" if paint_crosses else "steep_far"))
                continue
            reference = 0.0
            if abs(lateral) < AMBIGUOUS_LATERAL_M and previous is not None:
                reference = previous[1]
            side = "left" if lateral > reference else "right"
            # The same boundary as last frame keeps its side while it stays
            # near the robot: a line drifting across under the camera is still
            # the boundary it was, not the next lane's. Kept only while the
            # contradiction is momentary (SIDE_FLIP_FRAMES): a boundary that
            # sits on the other side of the robot frame after frame has a
            # stale side, and its one-sided target would land outside the
            # lane (20261005T134540Z, frames 329-367).
            tracked = self._track(lateral, heading)
            wrong_side = 0
            if tracked is not None:
                tracked_side, carried = tracked
                beyond = ((lateral > AMBIGUOUS_LATERAL_M and tracked_side == "right")
                          or (lateral < -AMBIGUOUS_LATERAL_M and tracked_side == "left"))
                wrong_side = carried + 1 if beyond else 0
                if abs(lateral) < SIDE_FLIP_M and wrong_side < SIDE_FLIP_FRAMES:
                    side = tracked_side
            inward = (np.array([direction[1], -direction[0]]) if side == "left"
                      else np.array([-direction[1], direction[0]]))
            point, along = _pursuit_point(centre + inward * half, direction, self._lookahead)
            if not (line["along"][0] - MAX_EXTRAPOLATION_M <= along
                    <= line["along"][1] + MAX_EXTRAPOLATION_M):
                self.last["candidates"].append(dict(record, side=side, y_at_side_x_m=round(lateral, 3),
                                                    rejected=True, reason="extrapolation"))
                continue
            record.update(side=side, y_at_side_x_m=round(lateral, 3),
                          tracked=tracked is not None and tracked[0] == side,
                          _wrong_side=wrong_side,
                          pursuit_m=[round(float(point[0]), 3), round(float(point[1]), 3)],
                          centre=centre, direction=direction)
            (left if side == "left" else right).append(record)
        # A dropped chord leaves only pairing and target: it keeps its tracked
        # side (not re-sided afresh) and the corner and junction rules see it.
        conflicts = pair_conflicts(left, right, half, SIDE_X_M)
        for record in conflicts:
            (left if record["side"] == "left" else right).remove(record)
            self.last["candidates"].append(
                dict({k: v for k, v in record.items()
                      if k not in ("centre", "direction", "_wrong_side")},
                     rejected=True, reason="pair_conflict"))
        target, strategy = self._choose(left, right, half)
        # A lane seen on both sides is followed; a corner is only looked for
        # when it is not (a line across between two lane lines is a stop
        # line, a crosswalk or a junction mouth, not an L-corner).
        corner = None
        if self._corner_turning and strategy != "both":
            corner = self._corner(transverse, half, left + right + conflicts)
        if corner is not None and (target is None or corner[1] != "corner_ahead"):
            target, strategy = corner
        seen_left, seen_right = ([b for b in left + right + conflicts if b["side"] == s] for s in ("left", "right"))
        junction = (None if corner is not None
                    else _junction(strategy, transverse, seen_left, seen_right, half,
                                   self._corner_turning,
                                   ONE_MAX_DISTANCE_FRACTION * 2.0 * half))
        if junction is not None:
            target = None
        self._tracked = [(r["y_at_side_x_m"], math.radians(r["heading_deg"]), r["side"],
                          r.get("_wrong_side", 0))
                         for r in left + right + conflicts]
        for record in left + right:
            if target is None or strategy.startswith('corner'):
                record['selected'] = False
            record.pop("direction")
            record.pop("centre")
            record.pop("_wrong_side", None)
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
            for record in self.last['boundaries'] + self.last['candidates']:
                record['selected'] = False
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
        """(side, wrong-side frames) of the last boundary this line continues,
        or None. The count is this line's carried streak of consecutive
        frames on the far side of its own tracked side."""
        best = None
        for previous_lateral, previous_heading, side, wrong_side in self._tracked:
            gap = abs(lateral - previous_lateral)
            if (gap <= TRACK_LATERAL_M and abs(heading - previous_heading) <= TRACK_HEADING_RAD
                    and (best is None or gap < best[0])):
                best = (gap, side, wrong_side)
        return None if best is None else best[1:]

    def _choose(self, left, right, half):
        """Target (x, y) and strategy from the side-classified boundaries."""
        for record in left + right:
            record['selected'] = False
        lane = 2.0 * half
        pairs = []
        for l in left:
            for r in right:
                if is_pair(l, r, lane, SIDE_X_M):
                    pairs.append((l["y_at_side_x_m"] - r["y_at_side_x_m"], l, r))
        if pairs:
            # The nearest pair: the robot is inside it (adjacent lanes lie beyond).
            # Pursue the centre line: midway at SIDE_X_M, along the mean heading
            # (on a NOMINAL floor the two lines rarely come out exactly parallel).
            _, l, r = min(pairs, key=lambda p: p[0])
            l['selected'] = r['selected'] = True
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
        record['selected'] = True
        return np.asarray(record["pursuit_m"], float), f"{record['side']}_only"


def _runs_past(boundaries, open_left, ahead):
    """True when a boundary on the open side runs on past the corner line."""
    for record in boundaries:
        if (record["side"] == "left") != open_left:
            continue
        far = max(float(p[0]) for p in record["ends_m"])
        if far >= ahead - CORNER_PAST_MARGIN_M:
            return True
    return False


def _pursuit_point(origin, direction, radius):
    """Point of the line origin + t*direction at `radius` from base_link, ahead
    (the larger root); the closest point when the line passes further away.
    Returns (point, t)."""
    b = float(np.dot(origin, direction))
    disc = b * b - float(np.dot(origin, origin)) + radius * radius
    t = -b + math.sqrt(disc) if disc > 0.0 else -b
    return origin + direction * t, t
