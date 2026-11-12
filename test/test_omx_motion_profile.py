"""Smooth motion through waypoints: exact where it must be, rounded where it may be, never past the guard."""
import importlib.util
from pathlib import Path

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
spec = importlib.util.spec_from_file_location("motion_profile", OMX / "motion_profile.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

FPS, VMAX = 30, 4.5
RISE_TURN_DESCEND = [[0, -60, 50, 45, 10, 46.6], [0, -27, 18, 46, 10, 46.6],
                     [30, -27, 18, 46, -30, 46.6], [30, -18, 22, 47, -30, 46.6]]


def speeds(frames, start):
    path = [start, *frames]
    return [[(b - a) * FPS for a, b in zip(p, q)] for p, q in zip(path, path[1:])]


def test_a_single_move_starts_and_ends_at_rest_within_the_guard_limits():
    frames = m.smooth(RISE_TURN_DESCEND[:2], FPS, VMAX)
    v = speeds(frames, RISE_TURN_DESCEND[0])
    assert frames[-1] == RISE_TURN_DESCEND[1]
    assert max(abs(x) for row in v for x in row) <= VMAX + 1e-6
    assert max(abs(x) for x in v[0]) < 0.5 and max(abs(x) for x in v[-1]) < 0.5  # no jump at either end
    accel = [max(abs(b - a) * FPS for a, b in zip(p, q)) for p, q in zip(v, v[1:])]
    assert max(accel) <= m.GUARD_ACCEL_UNITS_S2 + 0.5


def test_blended_corners_keep_moving_and_save_time_without_cutting_far():
    exact = m.smooth(RISE_TURN_DESCEND, FPS, VMAX)
    blended = m.smooth(RISE_TURN_DESCEND, FPS, VMAX, blend=[False, True, True, False])
    assert len(blended) < len(exact) and blended[-1] == RISE_TURN_DESCEND[-1]
    v = speeds(blended, RISE_TURN_DESCEND[0])
    assert max(abs(x) for row in v for x in row) <= VMAX + 0.5  # one joint slows as the other speeds up
    accel = [max(abs(b - a) * FPS for a, b in zip(p, q)) for p, q in zip(v, v[1:])]
    assert max(accel) <= 2 * m.GUARD_ACCEL_UNITS_S2 + 0.5
    corner = RISE_TURN_DESCEND[1]
    nearest = min(max(abs(a - b) for a, b in zip(f, corner)) for f in blended)
    assert nearest < 1.0  # the rise-to-turn corner is cut by under a unit
    stopped = [i for i, row in enumerate(v[1:-1]) if max(abs(x) for x in row) < 0.05]
    assert not stopped  # it never comes to rest between the start and the goal


def test_unblended_corners_are_passed_exactly_at_rest():
    frames = m.smooth(RISE_TURN_DESCEND, FPS, VMAX)
    for corner in RISE_TURN_DESCEND[1:]:
        assert min(max(abs(a - b) for a, b in zip(f, corner)) for f in frames) < 0.01  # sampled at rest


@pytest.mark.parametrize("distance", [0.2, 3.0, 40.0])
def test_trapezoid_covers_short_and_long_moves(distance):
    duration, ramp = m.trapezoid(distance, VMAX, 2.5)
    assert m.progress(duration, duration, ramp) == 1.0 and m.progress(duration / 2, duration, ramp) == pytest.approx(0.5)


def test_retime_keeps_the_planned_path_and_eases_in_and_out():
    line = [[0, -30 + k * 0.4, 20 - k * 0.3, 46 + k * 0.1, 10, 46.6] for k in range(1, 26)]  # a planner's line
    start = [0, -30, 20, 46, 10, 46.6]
    frames = m.retime(line, FPS, VMAX, start=start)
    assert frames[-1] == line[-1]
    v = speeds(frames, start)
    assert max(abs(x) for x in v[0]) < 0.5 and max(abs(x) for x in v[-1]) < 0.5  # eases out of and into rest
    assert max(abs(x) for row in v for x in row) <= VMAX + 1e-6
    for f in frames:  # every frame lies on the planned polyline (here a straight joint line)
        k = (f[1] + 30) / 0.4
        assert f[2] == pytest.approx(20 - k * 0.3, abs=1e-6) and f[3] == pytest.approx(46 + k * 0.1, abs=1e-6)
    acc = [[(b - a) * FPS for a, b in zip(p, q)] for p, q in zip(v, v[1:])]
    jerk = max(max(abs(b - a) * FPS for a, b in zip(p[:5], q[:5])) for p, q in zip(acc, acc[1:]))
    assert jerk < 30  # half-cosine acceleration: no 110+ units/s^3 trapezoid jerk kick


def test_blend_chunks_eliminates_dead_stop_between_consecutive_chunks_within_guard_speed():
    first = m.retime([[0, -30 + k * 0.4, 20 - k * 0.3, 46, 10, 46.6] for k in range(1, 26)],
                     FPS, VMAX, start=[0, -30, 20, 46, 10, 46.6])
    second = m.retime([[0, -20 + k * 0.4, 12.5 - k * 0.3, 46, 10, 46.6] for k in range(1, 26)],
                      FPS, VMAX, start=first[-1])
    blended = m.blend_chunks(first, second, FPS, blend_s=0.25, vmax=5.0)
    assert len(blended) < len(first) + len(second) and blended[-1] == second[-1]
    v = speeds(blended, [0, -30, 20, 46, 10, 46.6])
    assert max(abs(x) for row in v for x in row) <= 5.0 + 1e-6
    stopped_mid = [i for i, row in enumerate(v[5:-5]) if max(abs(x) for x in row[:5]) < 0.05]
    assert not stopped_mid


def test_temporal_chunk_ensembler_blends_overlapping_predictions_within_guard_speed():
    ensembler = m.TemporalChunkEnsembler(coeff=0.01, vmax=5.0, fps=FPS)
    start = [0.0, -30.0, 20.0, 46.0, 10.0, 46.6]
    ensembler.reset(start)
    chunk_a = [[0.1 * k, -30.0, 20.0, 46.0, 10.0, 46.6] for k in range(1, 16)]
    chunk_b = [[0.5 + 0.12 * k, -30.0, 20.0, 46.0, 10.0, 52.0] for k in range(1, 16)]
    ensembler.push(chunk_a)
    out = [ensembler.step() for _ in range(5)]
    ensembler.push(chunk_b)
    out.extend(ensembler.step() for _ in range(15))
    v = speeds(out, start)
    assert max(abs(x) for row in v for x in row[:5]) <= 5.0 + 1e-6
    assert out[-1][0] > out[4][0] and out[-1][5] == pytest.approx(52.0)


def test_receding_horizon_splice_transitions_in_flight_without_dead_stop():
    start = [0.0, -30.0, 20.0, 46.0, 10.0, 46.6]
    active = m.retime([[0.0, -30.0 + k * 0.4, 20.0 - k * 0.3, 46.0, 10.0, 46.6] for k in range(1, 26)],
                      FPS, VMAX, start=start)
    current = active[9]
    remaining = active[10:]
    anchor = remaining[min(len(remaining), round(0.25 * FPS)) - 1]
    next_chunk = m.retime([[anchor[0] + k * 0.3, anchor[1] + k * 0.2, anchor[2], 46.0, 10.0, 46.6]
                           for k in range(1, 21)], FPS, VMAX, start=anchor)
    spliced = m.receding_horizon_splice(remaining, current, next_chunk, FPS, blend_s=0.25, vmax=5.0)
    assert spliced[-1] == pytest.approx(next_chunk[-1])
    v = speeds(spliced, current)
    assert max(abs(x) for row in v for x in row[:5]) <= 5.0 + 1e-6
    stopped_mid = [i for i, row in enumerate(v[3:-5]) if max(abs(x) for x in row[:5]) < 0.05]
    assert not stopped_mid


def test_flow_decouples_pure_gripper_segments_and_skips_zero_delta_waypoints():
    wp_body = [[0.0, -30.0, 20.0, 46.0, 10.0, 46.6],
               [10.0, -30.0, 20.0, 46.0, 10.0, 46.6]]
    wp_grip = [[0.0, -30.0, 20.0, 46.0, 10.0, 46.6],
               [0.0, -30.0, 20.0, 46.0, 10.0, 46.6],  # redundant zero-delta waypoint
               [0.0, -30.0, 20.0, 46.0, 10.0, 56.6]]  # pure 10-unit gripper opening
    body_frames = m.flow(wp_body, FPS, VMAX, blend=[False, False], blend_s=0.2)
    grip_frames = m.flow(wp_grip, FPS, VMAX, blend=[False, False, False], blend_s=0.2)
    assert grip_frames[-1][5] == pytest.approx(56.6)
    # With decoupled gripper acceleration (amax >= 25), a 10-unit jaw move takes ~2.5s (~76 frames) vs ~3.6s (~109 frames) for body
    assert len(grip_frames) <= 80 and len(grip_frames) < len(body_frames) - 25
    v = speeds(grip_frames, wp_grip[0])
    assert max(abs(x) for row in v for x in row) <= VMAX + 1e-6


def test_compile_smooth_chunk_crane_corner_respects_guard_and_keeps_moving():
    start = [-27.7, 6.5, -9.9, 53.5, 17.9, 46.5]
    lift = [-27.7, -27.0, 22.0, 48.0, 17.9, 46.5]
    standby = [0.0, -27.0, 18.0, 46.0, -5.0, 46.5]
    frames = m.compile_smooth_chunk([start, {"pose": lift}, {"pose_units": standby}])
    velocity = speeds(frames, start)
    acceleration = [max(abs(b - a) * FPS for a, b in zip(p, q))
                    for p, q in zip(velocity, velocity[1:])]
    assert frames[-1] == standby
    assert len(frames) < 700
    assert max(acceleration) <= m.GUARD_ACCEL_UNITS_S2 + 0.1
    assert max(-v[1] for v in velocity) <= 2.6 + 1e-6
    assert min(max(abs(a - b) for a, b in zip(frame, lift)) for frame in frames) < 1.0
    assert min(max(abs(v) for v in velocity[10:-10])) > 0.05


def test_upgrade_linear_chunk_compresses_and_softens_corners():
    poses = [[0, -27, 18, 46, 0, 50], [30, -27, 18, 46, 0, 50],
             [30, -27, 48, 46, 0, 50], [30, -27, 48, 16, 0, 50]]
    linear = [poses[0]]
    for a, b in zip(poses, poses[1:]):
        count = round(max(abs(y - x) for x, y in zip(a, b)) / 0.030)
        linear.extend([[x + (y - x) * i / count for x, y in zip(a, b)]
                       for i in range(1, count + 1)])
    upgraded = m.upgrade_linear_chunk(linear)
    old_v, new_v = speeds(linear[1:], linear[0]), speeds(upgraded, linear[0])
    old_a = [[(b - a) * FPS for a, b in zip(p, q)] for p, q in zip(old_v, old_v[1:])]
    new_a = [[(b - a) * FPS for a, b in zip(p, q)] for p, q in zip(new_v, new_v[1:])]
    peak = lambda rows: max(abs(x) for row in rows for x in row)
    old_j = [[(b - a) * FPS for a, b in zip(p, q)] for p, q in zip(old_a, old_a[1:])]
    new_j = [[(b - a) * FPS for a, b in zip(p, q)] for p, q in zip(new_a, new_a[1:])]
    assert upgraded[-1] == poses[-1]
    assert len(linear) >= 3.2 * len(upgraded)
    assert peak(new_a) <= 0.25 * peak(old_a)
    assert peak(new_j) <= 0.25 * peak(old_j)


def test_compile_smooth_chunk_deduplicates_and_eases_pure_gripper_motion():
    start = [0, -27, 18, 46, 0, 46]
    end = [0, -27, 18, 46, 0, 56]
    assert m.compile_smooth_chunk([]) == []
    assert m.compile_smooth_chunk([start, start]) == [start]
    frames = m.compile_smooth_chunk([{"pose_units": start}, {"pose_units": start, "gripper": 56}])
    assert frames[-1] == end
    assert max(abs(v[5]) for v in speeds(frames, start)) <= 4.25 + 1e-6

