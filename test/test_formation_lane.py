"""D-1002 formation SIM scorer: path gaps, closest centres and lane-fit floor agree with Fleet, no Gazebo here."""
import importlib.util
import math
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


def _line(name_t0, speed, n, offset=0.0, dt=0.1):
    """(t, sim_t, x, y, yaw) rows along +x at `speed`, starting `offset` m behind the origin."""
    return [(name_t0 + i * dt, i * dt, -offset + speed * i * dt, 0.0, 0.0) for i in range(n)]


def test_project_returns_arc_length_and_offpath_distance():
    m = _module()
    path = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    assert m._project(path, 0.5, 0.2) == (0.5, 0.2)
    s, d = m._project(path, 1.3, 0.5)
    assert s == 1.5 and math.isclose(d, 0.3)


def test_score_reads_the_gap_behind_the_leader_and_the_closest_centres():
    m = _module()
    leader = _line(100.0, 0.2, 200)                   # 20 s at 0.2 m/s
    follower = _line(100.0, 0.2, 200, offset=0.8)     # exactly one spacing behind on the same line
    late = _line(100.0, 0.2, 200, offset=0.95)        # 0.15 m too far back
    truth = _Truth({'rosy_01': leader, 'rosy_02': follower, 'rosy_03': late})
    out = m.score(truth, 'rosy_01', ['rosy_02'], 0.8, marks=[])
    assert out['followers']['rosy_02']['max_abs_m'] <= 0.001
    # the first 4 s the follower is behind the leader's first recorded point: not judged (spawned behind it)
    assert 100 < out['followers']['rosy_02']['samples'] < 165
    assert math.isclose(out['min_centre_m'], 0.8, abs_tol=1e-6)
    out = m.score(truth, 'rosy_01', ['rosy_03'], 0.8, marks=[])
    assert math.isclose(out['followers']['rosy_03']['p95_abs_m'], 0.15, abs_tol=0.01)


def test_score_ignores_samples_while_the_leader_stands_and_after_the_follower_was_lost():
    m = _module()
    leader = _line(100.0, 0.0, 60)                    # a stopped leader: no gap sample is judged
    follower = _line(100.0, 0.0, 60, offset=0.8)
    truth = _Truth({'rosy_01': leader, 'rosy_02': follower})
    out = m.score(truth, 'rosy_01', ['rosy_02'], 0.8, marks=[])
    assert out['followers']['rosy_02']['samples'] == 0
    moving = _Truth({'rosy_01': _line(100.0, 0.2, 60), 'rosy_02': _line(100.0, 0.2, 60, offset=0.8)})
    cut = [{'t': 103.0, 'kind': 'inject', 'value': 'follower_lost'}]
    assert m.score(moving, 'rosy_01', ['rosy_02'], 0.8, marks=cut)['followers']['rosy_02']['samples'] < 32


def test_default_spacing_clears_the_fleet_lane_floor_for_the_default_follower_cap():
    """The scenario must be admissible as a Fleet formation mission (D-1002 lane_fit) at its own defaults."""
    import sys
    repo = SCRIPT.parents[2]
    sys.path[:0] = [str(repo / 'operations/fleet'), str(repo / 'contracts/foundation')]
    from fleet.server.formation_mission import min_lane_spacing
    assert 0.8 >= min_lane_spacing(0.26) > 0.6  # the script's --spacing/--max-speed defaults
