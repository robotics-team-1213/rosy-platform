"""D-395 §4.2: returns the map does not explain become objects in base_link."""
import math

import pytest

from control.sensing.loc_candidates import sensor_from_base
from control.sensing.loc_objects import unmapped_objects
from loc_world import MOUNT, field, mirror, scan


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
