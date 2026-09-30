"""LaneKeeper pairing (D-364): which sided boundaries bound one lane (split from lane_keep, D-362)."""

from __future__ import annotations

import math

import numpy as np

#: One lane's two boundaries run within this angle and are PAIR_MIN..PAIR_MAX_FRACTION
#: of the lane width apart at SIDE_X_M and at both ends of their common seen stretch
#: (real 124745Z frames 800-1017 paired a -17..-20 deg chord across crosswalk bars,
#: 0.12 m off the lane line at SIDE_X_M but 0.50 lane at its near end).
PAIR_MAX_ANGLE_RAD = math.radians(30.0)
PAIR_MIN_FRACTION = 0.6
PAIR_MAX_FRACTION = 1.6
#: A left/right couple within PAIR_MAX_FRACTION at SIDE_X_M, more than
#: CONFLICT_MIN_ANGLE_RAD apart, both within CONFLICT_MAX_HEADING_RAD of the heading
#: and no pair cannot both bound the lane: the one with less paint along the heading
#: (length x cos^2 heading; on a tie the one further out) is dropped as
#: 'pair_conflict' unless it pairs with a line not dropped (124745Z chords across
#: crosswalk bars and junction corners, frames 58-252 and 800-1017). Parallel lines
#: too close to pair, and steep junction crossings, are left to the other rules.
CONFLICT_MIN_ANGLE_RAD = math.radians(10.0)
CONFLICT_MAX_HEADING_RAD = math.radians(45.0)


def _lateral_at(centre, direction, x) -> float:
    return float(centre[1] + (x - centre[0]) * direction[1] / direction[0])


def is_pair(left, right, lane, side_x):
    """True when boundary `left` and boundary `right` can bound one lane."""
    if float(np.dot(left["direction"], right["direction"])) < math.cos(PAIR_MAX_ANGLE_RAD):
        return False
    lo = max(min(p[0] for p in left["ends_m"]), min(p[0] for p in right["ends_m"]))
    hi = min(max(p[0] for p in left["ends_m"]), max(p[0] for p in right["ends_m"]))
    return all(PAIR_MIN_FRACTION * lane <= _lateral_at(left["centre"], left["direction"], x)
               - _lateral_at(right["centre"], right["direction"], x) <= PAIR_MAX_FRACTION * lane
               for x in ((side_x, lo, hi) if lo < hi else (side_x,)))


def _loser(left, right, lane, side_x, live_left, live_right):
    """The line of a conflicting couple to drop, or None."""
    if (left["y_at_side_x_m"] - right["y_at_side_x_m"] > PAIR_MAX_FRACTION * lane
            or float(np.dot(left["direction"], right["direction"])) > math.cos(CONFLICT_MIN_ANGLE_RAD)
            or max(abs(left["heading_deg"]), abs(right["heading_deg"]))
            > math.degrees(CONFLICT_MAX_HEADING_RAD) or is_pair(left, right, lane, side_x)):
        return None
    loser = min((left, right), key=lambda r: (
        round(r["length_m"] * math.cos(math.radians(r["heading_deg"])) ** 2, 3), -abs(r["y_at_side_x_m"])))
    if loser is left:
        return None if any(is_pair(left, o, lane, side_x) for o in live_right) else left
    return None if any(is_pair(o, right, lane, side_x) for o in live_left) else right


def pair_conflicts(left, right, half, side_x):
    """Boundaries to drop as 'pair_conflict', re-judged after every drop (a
    partner that is dropped itself saves no line)."""
    dropped = []
    while True:
        live_left = [r for r in left if not any(r is d for d in dropped)]
        live_right = [r for r in right if not any(r is d for d in dropped)]
        loser = next((x for lf in live_left for rt in live_right
                      if (x := _loser(lf, rt, 2.0 * half, side_x, live_left, live_right)) is not None), None)
        if loser is None:
            return dropped
        dropped.append(loser)
