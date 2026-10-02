"""D-395: the robot lists every pose hypothesis, mirror included, instead of refusing."""
import math
from pathlib import Path

import numpy as np
import pytest

from control.sensing.loc_candidates import (
    Mount, PoseCandidate, ReferenceSquare, base_from_sensor, distinct, global_candidates, merge,
    reference_squares, sensor_from_base, slot_candidates)
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
    assert reference_squares({"reference_squares": None}) == []


@pytest.mark.parametrize("missing", ["centre", "heading_axis_deg"])
def test_a_reference_square_missing_a_field_is_rejected_by_id(missing):
    square = {"id": "Q7", "centre": [0., 0.], "heading_axis_deg": 90.}
    del square[missing]
    with pytest.raises(ValueError, match="Q7"):
        reference_squares({"reference_squares": [square]})


@pytest.mark.parametrize("rules", [[1, 2], "reference_squares", {"reference_squares": ["Q7"]}])
def test_malformed_lane_rules_raise_a_clear_value_error(rules):
    with pytest.raises(ValueError, match="reference"):
        reference_squares(rules)


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


def test_slot_search_checks_only_the_slot_boxes_not_the_whole_map(monkeypatch):
    """Production cost bound: the slot path must not build the full-map clear mask."""
    f = field()
    calls = []
    monkeypatch.setattr(f, "clear_poses", lambda radius: calls.append(radius))
    truth = (.86, -.52, 0.)
    ranges, angles = scan(truth)
    found = slot_candidates(f, SQUARES, ranges, angles, RADIUS, MOUNT)
    assert calls == []
    assert len(found) == 1 and near(found[0], truth)


def test_a_precomputed_clear_mask_is_reused_by_both_searches(monkeypatch):
    d = np.load(Path(__file__).parent / "fixtures/gazebo_localization_corner.npz")
    m = MapAgreement(d["grid"], float(d["resolution"]), d["origin"])
    clear = m.clear_poses(RADIUS)
    monkeypatch.setattr(m, "clear_poses", lambda radius: pytest.fail("clear mask recomputed"))
    found = global_candidates(m, d["ranges"], d["angles"], RADIUS, Mount(0., 0., 0.), clear=clear)
    assert found and math.dist((found[0].x, found[0].y), d["truth"][:2]) < .02
    square = ReferenceSquare("T", float(d["truth"][0]), float(d["truth"][1]), float(d["truth"][2]))
    slot = slot_candidates(m, [square], d["ranges"], d["angles"], RADIUS, Mount(0., 0., 0.), clear=clear)
    assert slot and math.dist((slot[0].x, slot[0].y), d["truth"][:2]) < .02


class _FixedRefinement:
    """A field whose refinement is scripted: (combined, agreement, sensor pose)."""

    def __init__(self, refined):
        self.refined = refined

    def refine(self, seeds, ranges, angles, clear, offsets=None):
        return self.refined


def test_slot_keeps_the_best_qualifying_refinement_not_the_best_combined_one():
    good = np.array([1., 2., 0.])
    field_ = _FixedRefinement([(.95, .85, np.array([0., 0., 0.])), (.93, .92, good)])
    ranges, angles = np.full(40, 1.), np.linspace(-1., 1., 40)
    square = ReferenceSquare("S", 0., 0., 0.)
    found = slot_candidates(field_, [square], ranges, angles, RADIUS, Mount(0., 0., 0.), clear=np.ones((1, 1), bool))
    assert len(found) == 2 and all((c.x, c.y, c.scan_fit) == (1., 2., .92) for c in found)
    field_.refined = [(.95, .85, np.array([0., 0., 0.]))]
    assert slot_candidates(field_, [square], ranges, angles, RADIUS, Mount(0., 0., 0.), clear=np.ones((1, 1), bool)) == []


def test_distinct_stops_at_the_first_result_outside_the_keep_window():
    results = [(.98, .97, (0., 0., 0.)), (.90, .95, (1., 0., 0.)), (.97, .96, (2., 0., 0.))]
    assert [p for p, _ in distinct(results)] == [(0., 0., 0.)]


def test_too_few_beams_yield_no_candidates():
    ranges = np.full(20, 1.)
    angles = np.linspace(-1, 1, 20)
    assert global_candidates(field(), ranges, angles, RADIUS, MOUNT) == []
    assert slot_candidates(field(), SQUARES, ranges, angles, RADIUS, MOUNT) == []


def test_merge_keeps_slot_candidates_first_and_drops_global_duplicates():
    slot = [PoseCandidate(-1.26, .49, -1.57, .99, "slot:A")]
    global_ = [PoseCandidate(-1.25, .48, -1.55, .98, "global"), PoseCandidate(1.26, -.49, 1.57, .98, "global")]
    assert merge(slot, global_) == [slot[0], global_[1]]


def test_a_candidate_stuck_between_coarse_headings_refines_on_the_full_scan(monkeypatch):
    """S1 re-run R3: a candidate 2.5 deg off failed the 3 s check; the fine stage corrects it."""
    f = field()
    truth = (-.70, .15, math.radians(-177.5))
    ranges, angles = scan(truth, beams=640)
    real = f.global_results
    stuck = np.array(sensor_from_base((truth[0] + .02, truth[1], truth[2] + math.radians(2.5)), MOUNT))

    def coarse(*args, **kwargs):
        results, reason = real(*args, **kwargs)
        return [(c, a, stuck if near(PoseCandidate(*base_from_sensor(p, MOUNT), a, "global"), truth) else p)
                for c, a, p in results], reason

    monkeypatch.setattr(f, "global_results", coarse)
    coarse_only = global_candidates(f, ranges[::4], angles[::4], RADIUS, MOUNT)
    found = global_candidates(f, ranges[::4], angles[::4], RADIUS, MOUNT, fine_scan=(ranges, angles))
    assert len(found) == len(coarse_only) == 2
    assert not any(near(c, truth, yaw=math.radians(2)) for c in coarse_only)
    assert any(near(c, mirror(truth)) for c in found)
    hit = [c for c in found if near(c, truth, yaw=math.radians(4))]
    assert len(hit) == 1
    assert abs(math.degrees(hit[0].yaw - truth[2])) <= .5
    assert math.dist((hit[0].x, hit[0].y), truth[:2]) <= .01
    assert hit[0].scan_fit >= .9


def test_the_fine_stage_keeps_the_distinct_count_and_the_mirror():
    for truth in [(0., -.51, math.radians(2.5)), (-.75, .30, math.radians(2.4)), (-1.26, .49, -math.pi / 2)]:
        ranges, angles = scan(truth, beams=640)
        coarse = global_candidates(field(), ranges[::4], angles[::4], RADIUS, MOUNT)
        fine = global_candidates(field(), ranges[::4], angles[::4], RADIUS, MOUNT, fine_scan=(ranges, angles))
        assert len(fine) == len(coarse)
        assert any(near(c, truth, yaw=math.radians(.75)) for c in fine)
        assert any(near(c, mirror(truth), yaw=math.radians(.75)) for c in fine)


def test_global_match_is_not_changed_by_the_fine_stage():
    """global_match answers before the fine stage existed (872a5cc5)."""
    result = field().global_match(*scan((0., -.51, 0.)), RADIUS)
    assert result["unique"] is False
    assert result["pose"] == pytest.approx([.015, -.51, -math.pi])
    assert result["margin"] == pytest.approx(.02053882221947323)
    d = np.load(Path(__file__).parent / "fixtures/gazebo_localization_corner.npz")
    m = MapAgreement(d["grid"], float(d["resolution"]), d["origin"])
    result = m.global_match(d["ranges"], d["angles"], RADIUS)
    assert result["unique"] is True
    assert result["pose"] == pytest.approx([.45591146128098453, 3.4560854302207504, math.pi / 2])


def test_a_recorded_gazebo_scan_on_an_asymmetric_map_keeps_its_true_pose():
    """Independent of loc_world's ray caster: a real Gazebo scan and map (fixture)."""
    d = np.load(Path(__file__).parent / "fixtures/gazebo_localization_corner.npz")
    m = MapAgreement(d["grid"], float(d["resolution"]), d["origin"])
    found = global_candidates(m, d["ranges"], d["angles"], RADIUS, Mount(0., 0., 0.))
    assert found and math.dist((found[0].x, found[0].y), d["truth"][:2]) < .02


# --- 2026-10-02 post-processing audit: guards only, no algorithm change -------------------------

class _ConvergingField:
    """Global search gives two distinct seeds; the fine stage pulls both onto one pose."""

    def __init__(self, seeds, refined):
        self.seeds, self.refined = seeds, refined

    def clear_poses(self, radius):
        return np.ones((1, 1), bool)

    def global_results(self, ranges, angles, radius, clear=None):
        return [(.99, .97, s) for s in self.seeds], None

    def refine(self, seeds, ranges, angles, clear, offsets=None):
        return [(.99, .98, self.refined)]


def test_a_duplicate_the_fine_stage_converged_is_dropped():
    a, b = np.array([0., 0., 0.]), np.array([.2, 0., 0.])          # apart before refinement
    field_ = _ConvergingField([a, b], np.array([.1, 0., 0.]))
    ranges, angles = np.full(40, 1.), np.linspace(-1., 1., 40)
    found = global_candidates(field_, ranges, angles, RADIUS, Mount(0., 0., 0.), fine_scan=(ranges, angles))
    assert len(found) == 1 and (found[0].x, found[0].y) == (.1, 0.)


@pytest.mark.parametrize("pose", [(0., 0., 0.), (.4, -.3, 1.), (-1.26, .49, -math.pi / 2), (.03, .01, 3.1)])
@pytest.mark.parametrize("twin", ["in_place", "mirror"])
def test_the_180_degree_twin_always_survives_distinct(pose, twin):
    """The yaw half of apart() is an OR: any radius tuning must keep the 180-degree twin,
    in place (same xy) or on the symmetric map's mirror, even with a better third nearby."""
    other = (pose[0], pose[1], pose[2] + math.pi) if twin == "in_place" else mirror(pose)
    nudge = (pose[0] + .05, pose[1], pose[2] + .1)                  # the same hypothesis, blurred
    picked = [p for p, _ in distinct([(.99, .97, pose), (.985, .97, nudge), (.98, .96, other)])]
    assert picked == [pose, other]
