"""D-395: the robot lists every pose hypothesis, mirror included, instead of refusing."""
import math
from pathlib import Path

import numpy as np
import pytest

from control.sensing.loc_candidates import (
    Mount, PoseCandidate, base_from_sensor, global_candidates, merge, reference_squares,
    sensor_from_base, slot_candidates)
from control.sensing.localization import MapAgreement
from loc_world import MOUNT, SQUARES, field, mirror, scan

RADIUS = .105


def near(candidate, pose, xy=.03, yaw=math.radians(4)):
    d = math.atan2(math.sin(candidate.yaw - pose[2]), math.cos(candidate.yaw - pose[2]))
    return math.dist((candidate.x, candidate.y), pose[:2]) <= xy and abs(d) <= yaw


def test_sensor_and_base_poses_round_trip_through_the_rotated_mount():
    base = (.3, -.2, 1.0)
    sensor = sensor_from_base(base, MOUNT)
    assert sensor[2] == pytest.approx(1.0 + math.pi - 2 * math.pi)
    assert base_from_sensor(sensor, MOUNT) == pytest.approx(base)
    assert sensor_from_base(base, Mount(0., 0., 0.)) == pytest.approx(base)


def test_reference_squares_come_from_lane_rules_with_the_axis_in_radians():
    assert [(s.id, s.x, s.y) for s in SQUARES] == [("A", -1.26, .49), ("B", .86, -.52)]
    assert [s.axis_rad for s in SQUARES] == pytest.approx([math.pi / 2, 0.])
    assert reference_squares({}) == [] and reference_squares(None) == []


def test_global_search_returns_the_pose_and_its_mirror_on_the_symmetric_track():
    truth = (0., -.51, 0.)
    ranges, angles = scan(truth)
    found = global_candidates(field(), ranges, angles, RADIUS, MOUNT)
    assert 2 <= len(found) <= 4
    assert any(near(c, truth) for c in found)
    assert any(near(c, mirror(truth)) for c in found)
    assert all(c.origin == "global" and c.scan_fit >= .9 for c in found)


@pytest.mark.parametrize("truth, square", [((-1.26, .49, -math.pi / 2), "A"),
                                           ((.86, -.52, 0.), "B")])
def test_a_robot_on_a_square_gets_one_slot_candidate_and_the_scan_picks_the_heading(truth, square):
    ranges, angles = scan(truth)
    found = slot_candidates(field(), SQUARES, ranges, angles, RADIUS, MOUNT)
    assert len(found) == 1
    assert found[0].origin == "slot:" + square and near(found[0], truth)


def test_an_off_slot_robot_gets_no_slot_candidate():
    ranges, angles = scan((0., -.51, 0.))
    assert slot_candidates(field(), SQUARES, ranges, angles, RADIUS, MOUNT) == []


def test_too_few_beams_yield_no_candidates():
    ranges = np.full(20, 1.)
    angles = np.linspace(-1, 1, 20)
    assert global_candidates(field(), ranges, angles, RADIUS, MOUNT) == []
    assert slot_candidates(field(), SQUARES, ranges, angles, RADIUS, MOUNT) == []


def test_merge_keeps_slot_candidates_first_and_drops_global_duplicates():
    slot = [PoseCandidate(-1.26, .49, -1.57, .99, "slot:A")]
    global_ = [PoseCandidate(-1.25, .48, -1.55, .98, "global"), PoseCandidate(1.26, -.49, 1.57, .98, "global")]
    assert merge(slot, global_) == [slot[0], global_[1]]


def test_a_recorded_gazebo_scan_on_an_asymmetric_map_keeps_its_true_pose():
    """Independent of loc_world's ray caster: a real Gazebo scan and map (fixture)."""
    d = np.load(Path(__file__).parent / "fixtures/gazebo_localization_corner.npz")
    m = MapAgreement(d["grid"], float(d["resolution"]), d["origin"])
    found = global_candidates(m, d["ranges"], d["angles"], RADIUS, Mount(0., 0., 0.))
    assert found and math.dist((found[0].x, found[0].y), d["truth"][:2]) < .02
