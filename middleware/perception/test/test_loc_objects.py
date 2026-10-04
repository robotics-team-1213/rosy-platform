"""D-395 §4.2: returns the map does not explain become objects in base_link."""
import math

import numpy as np
import pytest

from control.loc_assist import localized_objects
from control.sensing.body import URDF_RADIUS
from control.sensing.loc_candidates import sensor_from_base
from control.sensing.loc_objects import SELF_MARGIN_M, unmapped_objects
from loc_world import MOUNT, PEER_RADIUS, field, mirror, scan


def to_base(pose, point):
    c, s = math.cos(pose[2]), math.sin(pose[2])
    dx, dy = point[0] - pose[0], point[1] - pose[1]
    return (c * dx + s * dy, -s * dx + c * dy)


def test_an_empty_track_has_no_unmapped_objects():
    pose = (-.9, -.509, 0.)
    ranges, angles = scan(pose)
    assert unmapped_objects(field(), sensor_from_base(pose, MOUNT), ranges, angles, MOUNT) == []


def test_another_robot_is_one_object_near_its_true_offset():
    pose, peer = (-.9, -.509, 0.), (-1.26, .49)
    ranges, angles = scan(pose, peers=[peer])
    found = unmapped_objects(field(), sensor_from_base(pose, MOUNT), ranges, angles, MOUNT)
    assert len(found) == 1
    assert math.dist(found[0], to_base(pose, peer)) < .08


def test_a_robot_dead_ahead_is_not_split_at_the_scan_seam():
    """The mount is rotated by pi, so scan angle +-pi is base_link forward: a peer
    straight ahead straddles the seam and must still be one object."""
    pose, peer = (-.9, -.509, 0.), (-.55, -.509)
    ranges, angles = scan(pose, peers=[peer])
    found = unmapped_objects(field(), sensor_from_base(pose, MOUNT), ranges, angles, MOUNT)
    assert len(found) == 1
    assert math.dist(found[0], to_base(pose, peer)) < .08


def test_the_mirror_hypothesis_sees_the_same_objects():
    pose, peer = (-.9, -.509, 0.), (-1.26, .49)
    ranges, angles = scan(pose, peers=[peer])
    true = unmapped_objects(field(), sensor_from_base(pose, MOUNT), ranges, angles, MOUNT)
    mirrored = unmapped_objects(field(), sensor_from_base(mirror(pose), MOUNT), ranges, angles, MOUNT)
    assert mirrored == pytest.approx(true, abs=1e-6)


# --- 2026-10-02 post-processing audit: self beams, peer centre, merged peers -------------------

POSE = (-.9, -.509, 0.)


def _beside(rr, bearing, gap):
    """Two peers side by side across the line of sight, `gap` metres edge to edge."""
    c, s = math.cos(POSE[2] + bearing), math.sin(POSE[2] + bearing)
    mid, off = (POSE[0] + c * rr, POSE[1] + s * rr), PEER_RADIUS + gap / 2
    return (mid[0] - s * off, mid[1] + c * off), (mid[0] + s * off, mid[1] - c * off)


def test_chassis_returns_chained_to_a_stray_return_are_no_phantom():
    """S2 q1 (rosy_02, LOCALIZED): 1 of 4 objects sat 0.158 m from base_link, rear left
    (bearing ~123 deg), with no robot there. The S2 scan was not recorded, so this
    rebuilds the mechanism: self returns inside the body chained to one stray return
    put the centroid outside the radius, where the old centroid filter let it through."""
    ranges, angles = scan(POSE, beams=640)
    ranges = ranges.copy()
    rear_left = math.radians(123.) - MOUNT.yaw                 # base bearing -> scan angle
    near = (angles > rear_left - math.radians(5)) & (angles < rear_left + math.radians(5))
    ranges[near] = .10                                          # chassis / cable, inside r + 3 cm
    ranges[np.flatnonzero(near)[-1] + 1] = .155                 # one stray return 5.5 cm further
    sensor = sensor_from_base(POSE, MOUNT)
    legacy = unmapped_objects(field(), sensor, ranges, angles, MOUNT)
    assert len(legacy) == 1 and math.hypot(*legacy[0]) > URDF_RADIUS    # what the old filter kept
    assert localized_objects(field(), sensor, ranges, angles, MOUNT, URDF_RADIUS) == []
    assert SELF_MARGIN_M == .03


@pytest.mark.parametrize("rr, bearing_deg", [(.8, 45.), (.8, 60.), (.8, 90.), (1.5, 45.)])
def test_two_robots_five_cm_apart_are_two_objects(rr, bearing_deg):
    """Audit: two peers with an edge gap under 6 cm merged in 12 of 12 cases. These four
    placements merged before the fix (one object); bearings where a wall hides a peer are
    left out, that is occlusion, not merging."""
    peers = _beside(rr, math.radians(bearing_deg), .05)
    ranges, angles = scan(POSE, peers=peers, beams=640)
    sensor = sensor_from_base(POSE, MOUNT)
    assert len(unmapped_objects(field(), sensor, ranges, angles, MOUNT)) == 1     # merged before
    found = localized_objects(field(), sensor, ranges, angles, MOUNT, PEER_RADIUS)
    assert len(found) == 2
    for peer in peers:
        assert min(math.dist(o, to_base(POSE, peer)) for o in found) < .04


@pytest.mark.parametrize("rr", [.3, .8, 1.8])
def test_the_peer_centre_is_pushed_back_along_the_ray(rr):
    """Audit: the 3 real peers in S2 q1 matched with a 3.7-7 cm bias toward the observer."""
    peer = (POSE[0] + rr, POSE[1])
    ranges, angles = scan(POSE, peers=[peer], beams=640)
    sensor = sensor_from_base(POSE, MOUNT)
    raw = unmapped_objects(field(), sensor, ranges, angles, MOUNT)
    fixed = localized_objects(field(), sensor, ranges, angles, MOUNT, PEER_RADIUS)
    truth = to_base(POSE, peer)
    assert math.dist(raw[0], truth) > .035
    assert len(fixed) == 1 and math.dist(fixed[0], truth) < .015


@pytest.mark.parametrize("rr, bearing_deg", [(.3, 0.), (1., 0.), (2., 0.), (2., 30.), (1.5, 30.)])
def test_one_peer_is_never_split(rr, bearing_deg):
    h = math.radians(bearing_deg)
    peer = (POSE[0] + rr * math.cos(h), POSE[1] + rr * math.sin(h))
    ranges, angles = scan(POSE, peers=[peer], beams=640)
    assert len(localized_objects(field(), sensor_from_base(POSE, MOUNT), ranges, angles, MOUNT,
                                 URDF_RADIUS)) == 1
