"""D-457 5: overhead detections pair one-to-one with map-frame robot poses inside 0.30 m."""

import itertools
import math
import random

import pytest

from fleet.server.tracking_match import GATE_M, Pose, Seen, Track, assign, better, match


def _seen(x, y=0.0):
    return Seen(x=x, y=y, footprint_m=0.18, score=0.8)


def test_assignment_is_the_exact_minimum():
    assert assign([[4.0, 1.0, 3.0], [2.0, 0.0, 5.0], [3.0, 2.0, 2.0]]) == [1, 0, 2]
    assert assign([]) == []


def test_one_to_one_pairing_beats_greedy_nearest():
    poses = {"a": Pose(0.0, 0.0, True), "b": Pose(0.2, 0.0, True)}
    tracks, unknown = match(("a", "b"), poses, [_seen(0.1), _seen(-0.15)])
    by_id = {track.robot_id: track for track in tracks}
    assert by_id["a"].status == "MATCHED" and by_id["a"].offset_m == pytest.approx(0.15)
    assert by_id["a"].camera == _seen(-0.15)
    assert by_id["b"].status == "MATCHED" and by_id["b"].offset_m == pytest.approx(0.1)
    assert unknown == []


def test_a_detection_outside_the_gate_is_an_unknown_object():
    tracks, unknown = match(("a",), {"a": Pose(0.0, 0.0, True)}, [_seen(GATE_M + 0.01)])
    assert [track.status for track in tracks] == ["NO_DETECTION"]
    assert unknown == [_seen(GATE_M + 0.01)]


def test_two_robots_one_detection_the_nearer_wins():
    poses = {"a": Pose(0.0, 0.0, True), "b": Pose(0.25, 0.0, True)}
    tracks, unknown = match(("a", "b"), poses, [_seen(0.2)])
    assert [(track.robot_id, track.status) for track in tracks] == [("a", "NO_DETECTION"), ("b", "MATCHED")]
    assert unknown == []


def test_robot_without_map_pose_is_no_pose_and_never_claims_a_detection():
    tracks, unknown = match(("a",), {"a": None}, [_seen(0.0)])
    assert tracks == [Track("a", "NO_POSE")]
    assert unknown == [_seen(0.0)]


def test_no_fresh_payload_is_camera_unavailable_for_everyone():
    pose = Pose(1.0, 1.0, False)
    tracks, unknown = match(("a", "b"), {"a": pose, "b": None}, None)
    assert tracks == [Track("a", "CAMERA_UNAVAILABLE", pose=pose), Track("b", "CAMERA_UNAVAILABLE")]
    assert unknown == []


def test_the_more_informative_status_wins_across_sources():
    matched = Track("a", "MATCHED", 0.1, _seen(0.1), Pose(0.0, 0.0, True))
    assert better(Track("a", "CAMERA_UNAVAILABLE"), matched) is matched
    assert better(Track("a", "NO_DETECTION"), Track("a", "NO_POSE")).status == "NO_DETECTION"


def test_duplicate_robot_ids_are_rejected():
    with pytest.raises(ValueError):
        match(("a", "a"), {"a": Pose(0.0, 0.0, True)}, [])


def test_gate_is_inclusive_with_float_tolerance():
    tracks, _ = match(("a",), {"a": Pose(0.1, 0.0, True)}, [_seen(0.4)])
    assert tracks[0].status == "MATCHED"
    tracks, _ = match(("a",), {"a": Pose(0.0, 0.0, True)}, [_seen(GATE_M)])
    assert tracks[0].status == "MATCHED"


def test_extra_detections_are_unknown_objects():
    tracks, unknown = match(("a",), {"a": Pose(0.0, 0.0, True)}, [_seen(0.05), _seen(2.0), _seen(3.0)])
    assert tracks[0].status == "MATCHED"
    assert unknown == [_seen(2.0), _seen(3.0)]


def test_empty_detections_is_no_detection_but_none_is_camera_unavailable():
    poses = {"a": Pose(0.0, 0.0, True)}
    assert match(("a",), poses, [])[0][0].status == "NO_DETECTION"
    assert match(("a",), poses, None)[0][0].status == "CAMERA_UNAVAILABLE"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_values_never_match(bad):
    tracks, unknown = match(("a",), {"a": Pose(bad, 0.0, True)}, [_seen(0.0)])
    assert tracks[0].status == "NO_DETECTION" and unknown == [_seen(0.0)]
    tracks, unknown = match(("a",), {"a": Pose(0.0, 0.0, True)}, [_seen(bad)])
    assert tracks[0].status == "NO_DETECTION" and len(unknown) == 1


def _exhaustive(poses, dets):
    """Best (max matches, then min total distance) over all gated partial matchings."""
    best = (0, 0.0)

    def rec(i, taken, count, total):
        nonlocal best
        if i == len(poses):
            if (-count, total) < (-best[0], best[1]):
                best = (count, total)
            return
        rec(i + 1, taken, count, total)
        for j, d in enumerate(dets):
            if j in taken:
                continue
            dist = math.hypot(d.x - poses[i].x, d.y - poses[i].y)
            if dist <= GATE_M:
                rec(i + 1, taken | {j}, count + 1, total + dist)

    rec(0, frozenset(), 0, 0.0)
    return best


def test_randomized_matches_an_exhaustive_solver():
    rng = random.Random(405)
    for _ in range(300):
        n_robots, n_dets = rng.randint(0, 5), rng.randint(0, 6)
        ids = tuple(f"r{k}" for k in range(n_robots))
        poses = {rid: Pose(rng.uniform(0, 1), rng.uniform(0, 1), True) for rid in ids}
        dets = [_seen(rng.uniform(0, 1), rng.uniform(0, 1)) for _ in range(n_dets)]
        tracks, unknown = match(ids, poses, dets)
        matched = [t for t in tracks if t.status == "MATCHED"]
        count, total = _exhaustive([poses[r] for r in ids], dets)
        assert len(matched) == count
        assert sum(t.offset_m for t in matched) == pytest.approx(total, abs=1e-3)
        assert len(unknown) == n_dets - count
