"""D-395 §7 cues: bounded values, absent input is 0, never a guess."""

from __future__ import annotations

import math

import pytest

from fleet.localization import cues

A = (-1.26, 0.49)
B = (0.86, -0.52)
SLOTS = [cues.Slot(*A, math.pi / 2), cues.Slot(*B, 0.0)]
ON_A = (-1.26, 0.49, -math.pi / 2)
MIRROR_A = (1.26, -0.49, math.pi / 2)


def test_to_map_places_a_forward_point_along_the_heading():
    assert cues.to_map((1.0, 2.0, math.pi / 2), (0.5, 0.0)) == pytest.approx((1.0, 2.5))
    assert cues.to_map((0.0, 0.0, 0.0), (0.0, 0.3)) == pytest.approx((0.0, 0.3))


@pytest.mark.parametrize("pose, objects, peers, expected", [
    ((0.0, 0.0, 0.0), [(1.0, 0.0)], [(1.0, 0.05)], 1.0),                 # object lands on the peer
    # S1 finding 3: a peer in view but not seen is no evidence (0), never -1.
    ((0.0, 0.0, math.pi), [(1.0, 0.0)], [(1.0, 0.05)], 0.0),             # mirror heading: lands at (-1, 0)
    ((0.0, 0.0, 0.0), [], [(1.0, 0.0)], 0.0),                            # peer in view, nothing seen
    ((0.0, 0.0, 0.0), [(1.0, 0.0)], [(1.0, 0.0), (0.0, 1.0)], 0.5),      # one seen, one missing
    ((0.0, 0.0, 0.0), [(1.0, 0.0), (0.0, 1.0)], [(1.0, 0.0), (0.0, 1.0)], 1.0),  # both seen
    ((0.0, 0.0, 0.0), [(1.0, 0.0)], [(3.0, 0.0)], 0.0),                  # peer out of view
    ((0.0, 0.0, 0.0), [(1.0, 0.0)], [], 0.0),                            # no peers
])
def test_peers_cue(pose, objects, peers, expected):
    assert cues.peers_cue(pose, objects, peers) == pytest.approx(expected)


@pytest.mark.parametrize("pose, expected", [
    (ON_A, 1.0),                                     # axis + 180
    ((-1.26, 0.49, math.pi / 2), 1.0),               # axis
    ((-1.20, 0.55, math.radians(105)), 1.0),         # inside 10 cm / 20 deg
    ((-1.26, 0.49, 0.0), 0.0),                       # across the axis
    ((-1.10, 0.49, math.pi / 2), 0.0),               # 16 cm off
    (MIRROR_A, 0.0),                                 # the mirror of A is no slot
    ((0.86, -0.52, math.pi), 1.0),
])
def test_slot_cue(pose, expected):
    assert cues.slot_cue(pose, SLOTS) == expected


def test_last_good_cue_is_off_after_a_pickup_or_without_history():
    assert cues.last_good_cue(ON_A, ON_A[:2] + (0.0,), pickup=False) == pytest.approx(1.0)
    assert cues.last_good_cue(MIRROR_A, ON_A, pickup=False) < 0.01
    assert cues.last_good_cue(ON_A, ON_A, pickup=True) == 0.0
    assert cues.last_good_cue(ON_A, None, pickup=False) == 0.0


@pytest.mark.parametrize("age, expected_positive", [(0.0, True), (0.3, True), (0.31, False), (-0.1, False)])
def test_overhead_cue_needs_a_sighting_fresher_than_300_ms(age, expected_positive):
    sighting = cues.Sighting(-1.25, 0.5, 0.0, captured_at=100.0)
    value = cues.overhead_cue(ON_A, sighting, now=100.0 + age)
    assert (value > 0.9) is expected_positive
    assert cues.overhead_cue(ON_A, None, 100.0) == 0.0


@pytest.mark.parametrize("pose, sightings, expected", [
    ((-1.26, 0.19, math.pi / 2), [(0.0, 0.30)], 1.0),       # 30 cm short of A, square dead ahead
    # D-395 rev. 11: an unranged sighting is never evidence, either way (all 20 real false
    # detections in the 2026-10-02 audit were unranged).
    ((-1.26, 0.19, math.pi / 2), [(0.0, None)], -1.0),      # unranged on the bearing: A still unseen
    ((1.26, -0.19, -math.pi / 2), [(0.0, None)], 0.0),      # unranged, nothing mapped in view
    ((-1.26, 0.19, math.pi / 2), [(0.0, None), (0.0, 0.30)], 1.0),  # the ranged one decides
    ((-1.26, 0.19, math.pi / 2), [], -1.0),                 # A should be in view and is not
    ((1.26, -0.19, -math.pi / 2), [(0.0, 0.30)], -1.0),     # mirror: sees a square where none is mapped
    ((0.0, 0.0, 0.0), [], 0.0),                             # no square in view, none seen
])
def test_square_cue(pose, sightings, expected):
    assert cues.square_cue(pose, [A, B], sightings) == expected
