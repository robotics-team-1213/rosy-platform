"""Subject: lane-keep junction HOLD policy, split from lane_keep (D-364 §2).

Junctions fail closed (HOLD): with corner turning on, a lone boundary whose
side bends out of the lane while a transverse line crosses the path ahead is
a junction mouth (which lane goes on is unknown), and two boundaries on the
followed side that split wide are a fork -- unless one starts where the other
ends: that is one painted line bent in two straight fits (D-507 B9). Pure functions over the keeper's
per-frame boundary records; the caller (LaneKeeper.update) owns all state.
ROS-free, same contract onboard and in fixtures."""

from __future__ import annotations

import itertools
import math

from .lane_keep_lines import MAX_GAP_M


#: A transverse line across the path this close ahead of a lone, diverging
#: boundary is a junction mouth.
JUNCTION_AHEAD_M = 0.45
#: Two boundaries on the followed side split by more than this are a fork.
FORK_MIN_ANGLE_RAD = math.radians(30.0)
#: A boundary bending away out of the lane by more than this opens a mouth.
DIVERGE_MIN_RAD = math.radians(15.0)
#: Both branches of a fork are real paint, not a far fragment.
FORK_MIN_LENGTH_M = 0.12
#: A piece whose near end lies within the extractor's own piece gap of another
#: piece's far end continues it (B8: spoke edge into the roundabout arc, ends
#: 0.035-0.044 m apart p10-p90): one line, not two fork branches.
CONTINUITY_M = MAX_GAP_M


def _continues(first, then):
    """True when boundary record `then` starts where `first` ends (near and far
    by distance from base_link)."""
    far = max(first["ends_m"], key=lambda p: math.hypot(p[0], p[1]))
    near = min(then["ends_m"], key=lambda p: math.hypot(p[0], p[1]))
    return math.dist(far, near) <= CONTINUITY_M


def _across_path(ends, half):
    """Ahead distance where a (transverse) line crosses the path, or None."""
    ys = sorted(float(p[1]) for p in ends)
    if ys[0] > half or ys[1] < -half:
        return None
    (x0, y0), (x1, y1) = ((float(p[0]), float(p[1])) for p in ends)
    ahead = x0 if y1 == y0 else x0 + (x1 - x0) * (0.0 - y0) / (y1 - y0)
    return ahead if 0.0 < ahead <= JUNCTION_AHEAD_M else None


def _junction(strategy, transverse, left, right, half, corner_turning, max_lateral_m, continuity=False):
    """(reason, ahead_m) to HOLD at a junction, (None, None) otherwise. ahead_m is
    base_footprint x of the transverse line, or of the diverging branch's near
    end (D-507 §5). base_footprint and base_link share x on the reference robot:
    base_link_fixed_joint is `origin xyz="0 0 0.028"` (z only, rosy.urdf.xacro).
    Only with corner turning: there
    the corner reading can pull the robot out of the lane at a junction mouth.
    Without it (the device default until D-495) both rules held 5-10 % more of the real
    replay frames (pilot none 0.32 -> 0.36-0.43), so the plain keeper goes on
    along its lone boundary as the bench measures. Fork branches count only
    within `max_lateral_m` of the robot, the same plausibility bound the
    one-sided selection uses."""
    if not corner_turning or strategy not in ("left_only", "right_only"):
        return None, None
    side = left if strategy == "left_only" else right
    # The lone boundary bends away out of the lane (a mouth opening on its
    # side) while a line crosses the path ahead: which lane goes on is unknown.
    outward = 1.0 if strategy == "left_only" else -1.0
    diverging = any(outward * math.radians(r["heading_deg"]) > DIVERGE_MIN_RAD for r in side)
    crossing = [a for _, _, ends, steep in transverse
                if not steep and (a := _across_path(ends, half)) is not None]
    if diverging and crossing:
        return "junction_transverse", min(crossing)
    branches = [r for r in side if abs(r["y_at_side_x_m"]) <= max_lateral_m
                and r["length_m"] >= FORK_MIN_LENGTH_M]
    split = [r for a, b in itertools.combinations(branches, 2)
             if abs(math.radians(a["heading_deg"] - b["heading_deg"])) > FORK_MIN_ANGLE_RAD
             and not (continuity and (_continues(a, b) or _continues(b, a))) for r in (a, b)]
    if split:
        branch = max(split, key=lambda r: outward * r["heading_deg"])
        return "junction_fork", min(p[0] for p in branch["ends_m"])
    return None, None
