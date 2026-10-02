"""Scoring cues for one pose hypothesis (D-395 §7, rev. 1 §7). Pure numbers.

Each cue returns a bounded value; `arbiter.Weights` turns them into a score, and
the arbiter decides only on a margin between hypotheses held for a while. Only
the scan-asymmetric cues (peers, slot, square, paint) can carry a decision:
`last_good` and `overhead` weigh less than the margin (D-395 rev. 3). A missing
input (no camera, no peers, no slot) contributes 0, never a guess, so every cue
can be absent and the arbiter still works (S4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

Pose = tuple[float, float, float]

#: D-395 §5: the slot prior's box.
SLOT_XY_M = 0.10
SLOT_YAW_RAD = math.radians(20.0)
#: A projected object within this of a peer's reported pose is that peer.
PEER_MATCH_M = 0.15
#: A LOCALIZED peer closer than this should be in the scan (no occlusion model yet).
PEER_VIEW_M = 2.0
#: D-395 §7: an overhead sighting older than this is not a cue.
OVERHEAD_FRESH_S = 0.3
LAST_GOOD_SCALE_M = 0.3
OVERHEAD_SCALE_M = 0.25
#: A seen square must land this close to a mapped square under the hypothesis.
SQUARE_MATCH_M = 0.15
#: Where the front camera can see a square: range and half field of view.
SQUARE_VIEW_M = 0.6
SQUARE_HALF_FOV_RAD = math.radians(30.0)


@dataclass(frozen=True)
class Slot:
    x: float
    y: float
    axis_rad: float


@dataclass(frozen=True)
class Sighting:
    """Overhead camera pose of this robot, site clock seconds."""
    x: float
    y: float
    yaw: float
    captured_at: float


def wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def to_map(pose: Pose, point: tuple[float, float]) -> tuple[float, float]:
    """A base_link (forward, left) point placed on the map from `pose`."""
    c, s = math.cos(pose[2]), math.sin(pose[2])
    return (pose[0] + c * point[0] - s * point[1], pose[1] + s * point[0] + c * point[1])


def peers_cue(pose: Pose, objects: Sequence[tuple[float, float]],
              peers: Sequence[tuple[float, float]]) -> float:
    """(+1 per peer an object lands on) / peers in view.

    A peer in view but not seen counts 0, not -1 (S1 finding 3): detection is marginal,
    and a miss at the truth handed the mirror a 2.0 lead. Only "seen where expected" is
    evidence; the caller passes anchored peers only (D-395 S1 fix)."""
    placed = [to_map(pose, o) for o in objects]
    in_view = [p for p in peers if math.dist(pose[:2], p) <= PEER_VIEW_M]
    if not in_view:
        return 0.0
    seen = sum(1 for p in in_view if any(math.dist(p, q) <= PEER_MATCH_M for q in placed))
    return seen / len(in_view)


def slot_cue(pose: Pose, slots: Sequence[Slot]) -> float:
    """1 when the pose sits on a slot facing along its axis, either way."""
    for slot in slots:
        off = abs(wrap(pose[2] - slot.axis_rad))
        if math.dist(pose[:2], (slot.x, slot.y)) <= SLOT_XY_M and min(off, math.pi - off) <= SLOT_YAW_RAD:
            return 1.0
    return 0.0


def last_good_cue(pose: Pose, last_good: Optional[Pose], pickup: bool) -> float:
    """Closeness to the last LOCALIZED pose; never after a pickup."""
    if pickup or last_good is None:
        return 0.0
    return math.exp(-math.dist(pose[:2], last_good[:2]) / LAST_GOOD_SCALE_M)


def overhead_cue(pose: Pose, sighting: Optional[Sighting], now: float) -> float:
    """Closeness to an overhead sighting fresher than 300 ms."""
    if sighting is None or not 0.0 <= now - sighting.captured_at <= OVERHEAD_FRESH_S:
        return 0.0
    return math.exp(-math.dist(pose[:2], (sighting.x, sighting.y)) / OVERHEAD_SCALE_M)


def square_cue(pose: Pose, squares: Sequence[tuple[float, float]],
               sightings: Sequence[tuple[float, Optional[float]]]) -> float:
    """+1 when a seen square lands on a mapped one; -1 when a seen square lands on none,
    or a mapped one should be in view and is not; 0 when nothing is seen or expected.

    `sightings` are (bearing_rad, range_m) in base_link; an unranged sighting counts
    as seen when a mapped square lies on its bearing within the view.
    """
    c, s = math.cos(pose[2]), math.sin(pose[2])
    expected = []
    for sx, sy in squares:
        dx, dy = sx - pose[0], sy - pose[1]
        forward, left = c * dx + s * dy, -s * dx + c * dy
        bearing, rng = math.atan2(left, forward), math.hypot(forward, left)
        if forward > 0.0 and rng <= SQUARE_VIEW_M and abs(bearing) <= SQUARE_HALF_FOV_RAD:
            expected.append((bearing, rng, (sx, sy)))
    for bearing, rng in sightings:
        for e_bearing, e_range, centre in expected:
            if rng is None:
                if abs(wrap(bearing - e_bearing)) * e_range <= SQUARE_MATCH_M:
                    return 1.0
            elif math.dist(to_map(pose, (rng * math.cos(bearing), rng * math.sin(bearing))),
                           centre) <= SQUARE_MATCH_M:
                return 1.0
    return -1.0 if expected or sightings else 0.0
