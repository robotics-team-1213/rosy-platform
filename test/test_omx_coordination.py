"""Two arms' timing on fixed paths (omx_adapter.coordination); no arm, no ROS."""
import itertools
import math
from pathlib import Path
import random
import sys

import pytest

from omx_adapter.coordination import (Segment, clearance, line_distance, moved, plan, ready, rendezvous, rigid_between,
                                      thinned)

R = 0.01


def stick(x, y):
    return [((x, y, 0.0), (x, y, 0.1), R)]


def move(name, start, end, seconds=1.0, samples=21):
    poses = [stick(start[0] + (end[0] - start[0]) * k / (samples - 1), start[1] + (end[1] - start[1]) * k / (samples - 1))
             for k in range(samples)]
    return Segment(name, seconds, poses)


def test_line_distance_covers_parallel_crossing_and_end_points():
    assert line_distance((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)) == pytest.approx(1.0)
    assert line_distance((0, 0, 0), (1, 0, 0), (0.5, -1, 0), (0.5, 1, 0)) == pytest.approx(0.0)
    assert line_distance((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)) == pytest.approx(1.0)
    assert line_distance((0, 0, 0), (0, 0, 0), (0, 2, 0), (0, 2, 0)) == pytest.approx(2.0)


def test_paths_far_apart_run_together():
    a, b = [move("a", (0, 0), (1, 0))], [move("b", (0, 5), (1, 5))]
    assert plan(a, b, 0.05) == {"steps": [{"a": 0, "b": 0}], "makespan_s": 1.0}


def test_paths_that_cross_are_ordered_so_they_never_meet():
    a = [move("in", (0, 0), (0.9, 0)), move("through", (0.9, 0), (1.5, 0))]
    b = [move("cross", (1, -1), (1, 1))]
    schedule = plan(a, b, 0.05)
    assert schedule is not None
    assert not any(s["a"] == 1 and s["b"] == 0 for s in schedule["steps"])


def test_it_waits_only_where_needed():
    a = [move("far", (0, 3), (1, 3)), move("cross", (1, 3), (1, -3)), move("far2", (1, -3), (2, -3))]
    b = [move("wait", (0.5, 0), (0.4, 0)), move("cross", (0.4, 0), (1.6, 0)), move("leave", (1.6, 0), (1.7, 0))]
    schedule = plan(a, b, 0.05)
    assert schedule["makespan_s"] < 6.0  # one after the other would take six
    assert any(s["a"] is not None and s["b"] is not None for s in schedule["steps"])


def test_no_order_is_refused():
    a, b = [move("a", (0, 0), (1, 0))], [move("b", (1, 1), (1, 0))]  # both end on the same spot
    assert plan(a, b, 0.05) is None


def test_ready_follows_the_schedule_by_progress_not_by_time():
    steps = [{"a": 0, "b": None}, {"a": None, "b": 0}, {"a": 1, "b": 1}]
    assert ready(steps, "a", 0, 0, 0) and not ready(steps, "b", 0, 0, 0)
    assert ready(steps, "b", 0, 1, 0)
    assert not ready(steps, "a", 1, 1, 0) and ready(steps, "a", 1, 1, 1) and ready(steps, "b", 1, 1, 1)
    assert not ready(steps, "a", 9, 2, 2)


def _position(segment, fraction):
    return segment.poses[min(len(segment.poses) - 1, int(fraction * len(segment.poses)))]


@pytest.mark.parametrize("seed", range(30))
def test_any_timing_the_gates_allow_keeps_the_margin_even_when_an_arm_stalls(seed):
    rng = random.Random(seed)
    point = lambda: (rng.uniform(0, 1), rng.uniform(0, 1))  # noqa: E731
    walk = lambda name, count: [move(f"{name}{k}", p, q) for k, (p, q) in  # noqa: E731
                                enumerate(itertools.pairwise([point() for _ in range(count + 1)]))]
    a, b, margin = walk("a", 4), walk("b", 4), 0.03
    schedule = plan(a, b, margin)
    if schedule is None:
        return
    segments = {"a": a, "b": b}
    done, inside, moving = {"a": 0, "b": 0}, {"a": 0.0, "b": 0.0}, {"a": False, "b": False}
    stalled, stall_at = rng.choice(["a", "b", None]), rng.randrange(1, 40)
    for tick in range(4000):
        for arm in "ab":
            if not moving[arm] and done[arm] < len(segments[arm]) and ready(schedule["steps"], arm, done[arm], done["a"], done["b"]):
                moving[arm], inside[arm] = True, 0.0
        order = list("ab")
        rng.shuffle(order)
        for arm in order:
            if moving[arm] and not (arm == stalled and tick > stall_at):
                inside[arm] += rng.uniform(0.0, 0.15)
                if inside[arm] >= 1.0:
                    moving[arm], done[arm] = False, done[arm] + 1
        where = {}
        for arm in "ab":
            path = segments[arm]
            if moving[arm]:
                where[arm] = _position(path[done[arm]], inside[arm])
            else:
                where[arm] = path[done[arm]].poses[0] if done[arm] < len(path) else path[-1].poses[-1]
        assert clearance([where["a"]], [where["b"]]) >= margin - 1e-9


def test_rigid_between_recovers_a_known_transform_and_moves_capsules():
    yaw, tx, ty = 0.4, 0.3, -0.2
    source = [(0.0, 0.0), (0.1, 0.0), (0.0, 0.2), (0.3, 0.1)]
    target = [(math.cos(yaw) * x - math.sin(yaw) * y + tx, math.sin(yaw) * x + math.cos(yaw) * y + ty) for x, y in source]
    assert rigid_between(source, target) == pytest.approx((yaw, tx, ty))
    (p, _q, _r), = moved([((0.0, 0.0, 0.5), (0.0, 0.0, 0.6), R)], (yaw, tx, ty))
    assert p == pytest.approx((tx, ty, 0.5))
    with pytest.raises(ValueError):
        rigid_between([(0, 0)], [(0, 0)])


def test_thinned_keeps_ends_and_grows_radii_so_a_gap_cannot_hide_a_pass():
    poses = [stick(k * 0.001, 0.0) for k in range(101)]
    kept = thinned(poses, 0.02)
    assert len(kept) < 10 and kept[0][0][0] == poses[0][0][0] and kept[-1][0][0] == poses[-1][0][0]
    assert kept[0][0][2] == pytest.approx(R + 0.01)
    other = stick(0.05, 0.02)
    assert clearance(kept, [other]) <= clearance(poses, [other])


def test_rendezvous_needs_no_meet_when_the_paths_stay_apart():
    a, b = [move("a", (0, 0), (1, 0))], [move("b", (0, 5), (1, 5))]
    assert rendezvous(a, b, 0.05) == {"meets": [], "makespan_s": 1.0}


def test_rendezvous_puts_a_meet_where_the_order_must_change():
    a = [move("in", (0, 0), (0.5, 0)), move("through", (0.5, 0), (1.5, 0)), move("out", (1.5, 0), (2.5, 0))]
    b = [move("wait", (1, -2), (1, -1)), move("through", (1, -1), (1, 1))]
    result = rendezvous(a, b, 0.05)
    assert result["meets"] and result["makespan_s"] <= sum(s.duration_s for s in a + b)


def test_rendezvous_refuses_when_no_order_exists_or_too_few_meets_are_allowed():
    assert rendezvous([move("a", (0, 0), (1, 0))], [move("b", (1, 1), (1, 0))], 0.05) is None
    a = [move("in", (0, 0), (0.5, 0)), move("through", (0.5, 0), (1.5, 0))]
    b = [move("through", (1, -1), (1, 1))]
    assert rendezvous(a, b, 0.05, max_meets=0) is None
    assert rendezvous(a, b, 0.05, max_meets=1) is not None


@pytest.mark.parametrize("seed", range(30))
def test_every_pair_inside_a_rendezvous_block_keeps_the_margin(seed):
    rng = random.Random(seed)
    point = lambda: (rng.uniform(0, 1), rng.uniform(0, 1))  # noqa: E731
    walk = lambda name: [move(f"{name}{k}", p, q) for k, (p, q) in  # noqa: E731
                         enumerate(itertools.pairwise([point() for _ in range(5)]))]
    a, b, margin = walk("a"), walk("b"), 0.03
    result = rendezvous(a, b, margin, max_meets=99)
    if result is None:
        return
    nodes = [(0, 0), *result["meets"], (len(a), len(b))]
    for (i, j), (i2, j2) in itertools.pairwise(nodes):
        poses_a = [p for s in a[i:i2] for p in s.poses] or ([a[i].poses[0]] if i < len(a) else a[-1].poses[-1:])
        poses_b = [p for s in b[j:j2] for p in s.poses] or ([b[j].poses[0]] if j < len(b) else b[-1].poses[-1:])
        assert clearance(poses_a, poses_b) >= margin


def test_the_offline_tool_splits_commands_turns_the_fold_and_keeps_the_time():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
    import cell_coordinate

    home = [0.8, -62.2, 53.1, 51.6, 45.2, 48.8]
    pick = [10.0, -20.0, 20.0, 40.0, 20.0, 60.0]
    chunks = {"home": [home], "above_pick": [pick], "above_place": [pick]}
    for name in ("descend_pick", "grasp_pick", "lift_pick", "descend_place", "release_place", "lift_place"):
        chunks[name] = [pick] * 30
    library = {"chunks": chunks, "gripper_closed": 48.8, "fps": 30, "transit_speed": 0.4,
               "transit": {"shoulder_lift.pos": -27.0, "elbow_flex.pos": 18.0, "wrist_flex.pos": 46.0}}
    kin, _, _ = cell_coordinate.load_kinematics(None)
    still = (0.0, 0.0, 0.0)
    whole = cell_coordinate.segments_of(library, kin, still)
    split = cell_coordinate.segments_of(library, kin, still, piece_s=5.0)
    assert len(whole) == len(cell_coordinate.FOLDED) and len(split) > len(whole)
    assert sum(s.duration_s for s in split) == pytest.approx(sum(s.duration_s for s in whole))
    aside = cell_coordinate.segments_of(library, kin, still, home_pan=60.0)
    assert aside[0].poses[0][0][1] != whole[0].poses[0][0][1]  # the elbow first pose turned with the fold
    assert library["chunks"]["home"] == [home]  # the library it was given is untouched
