"""tools/sim/formation_lane.py: the swarm/truth disagreement analysis answers the run-8 open question.

Run 8 (2026-11-09) ended with the follower 0.70 m off the leader's trail and `trail_lost`, with no
recording of which frame lied — the leader's relayed map pose or the follower's own. `analyze_swarm`
compares the follower's own view (`leader_s - progress`) with Gazebo truth and flags the leader
stream's jumps; these tests pin both directions on synthetic straight-lane data.
"""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/sim/formation_lane.py'


def _module():
    spec = importlib.util.spec_from_file_location('formation_lane', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Truth:
    def __init__(self, rows):
        self.rows = rows


def _straight(n=100, dt=0.1):
    """Leader drives +x at 0.2 m/s from (0, 0); the follower holds 0.8 m behind the whole way.

    Rows are the Truth shape: (monotonic t, sim t, x, y, yaw) on a common clock starting at t=100.
    """
    rows = {'rosy_01': [(100.0 + i * dt, i * dt, 0.2 * i * dt, 0.0, 0.0) for i in range(n)],
            'rosy_02': [(100.0 + i * dt, i * dt, 0.2 * i * dt - 0.8, 0.0, 0.0) for i in range(n)]}
    return _Truth(rows)


def _swarm_row(i, own_progress, hold_reason=None, dt=0.1):
    lead_s = round(0.2 * i * dt, 4)
    return {'t': 100.0 + i * dt, 'kind': 'swarm', 'robot': 'rosy_02', 'holding': hold_reason is not None,
            'stream_age_s': 0.12, 'trail': {'leader_s': lead_s, 'progress': round(own_progress, 4),
                                            'hold_reason': hold_reason, 'anchor': 'fleet'}}


def test_frames_that_agree_report_zero_disagreement():
    m = _module()
    rows = [_swarm_row(i, 0.2 * i * 0.1 - 0.8) for i in range(45, 95)]
    out = m.analyze_swarm(rows, _straight(), 'rosy_01', ['rosy_02'], 0.8)
    f = out['followers']['rosy_02']
    assert f['samples'] == 50
    assert f['frame_disagree_max_abs_m'] <= 0.01 and f['own_gap_p95_abs_m'] <= 0.01
    assert f['hold_reasons'] == {} and f['stream_age_max_s'] == 0.12


def test_a_follower_frame_that_lies_by_half_a_metre_is_named():
    """The run-8 shape: the follower's own trail view says the gap is 0.5 m larger than truth does."""
    m = _module()
    rows = [_swarm_row(i, 0.2 * i * 0.1 - 1.3, hold_reason='trail_rejoin' if i % 7 == 0 else None)
            for i in range(45, 95)]
    out = m.analyze_swarm(rows, _straight(), 'rosy_01', ['rosy_02'], 0.8)
    f = out['followers']['rosy_02']
    assert 0.4 <= f['frame_disagree_p95_abs_m'] <= 0.6
    assert 0.45 <= f['own_gap_max_abs_m'] <= 0.55
    assert f['hold_reasons'] == {'trail_rejoin': 7} and f['holding_samples'] == 7


def test_a_leader_stream_jump_over_the_bridge_bound_is_flagged():
    m = _module()
    rows = [{'t': 100.0 + i * 0.1, 'kind': 'leader_pose', 'x': 0.2 * i * 0.1 + (0.4 if i == 60 else 0.0),
             'y': 0.0, 'yaw': 0.0, 'frame': 'map'} for i in range(100)]
    out = m.analyze_swarm(rows, _straight(), 'rosy_01', ['rosy_02'], 0.8)
    lead = out['leader_pose']
    assert lead['samples'] == 100
    assert lead['jump_excess_max_m'] > 0.35 and lead['jump_excess_over_0p3'] >= 1
