"""tools/sim/fleet_trips.py: the two lane trips are straight, on their road and clear of crosswalks."""
import importlib.util
import math
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/sim/fleet_trips.py'


def _module():
    spec = importlib.util.spec_from_file_location('fleet_trips', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_trip_is_a_straight_stretch_of_its_own_road_without_a_crosswalk():
    m = _module()
    graph = yaml.safe_load(m.GRAPH.read_text(encoding='utf-8'))
    trips = m.plan_trips(graph)
    assert set(trips) == set(m.ROBOTS) and len({m.TRIPS[ns][0] for ns in m.ROBOTS}) == len(m.ROBOTS)
    for ns, (spawn, end) in trips.items():
        segment, way, start = m.TRIPS[ns]
        assert math.dist(spawn[:2], end[:2]) > 0.99 * m.TRIP_M
        # Straight: every pose from spawn to end heads the same way (a corner turns ~90 deg).
        for k in range(31):
            x, y, yaw = m.lane_pose(graph, segment, way, start + m.TRIP_M * k / 30)
            assert abs(math.remainder(yaw - spawn[2], math.tau)) < math.radians(5), (ns, k)
            for crosswalk in graph['crosswalks']:
                xs, ys = zip(*crosswalk['polygon'])
                assert not (min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys)), (ns, k, crosswalk)


def test_remote_sim_runs_the_bench_and_installs_the_fleet_and_learned_inputs():
    import sys
    sys.path.insert(0, str(SCRIPT.parents[1] / 'remote'))
    import remote_sim as rs
    assert 'tools/sim/fleet_trips.py' in rs.BENCHES['fleet_trips']
    assert 'requirements-fleet.txt' in rs.SIM and 'learned-perception-requirements.txt' in rs.SIM
    assert 'ROSY_LEARNED_SITE="$PYDEPS/learned"' in rs.INNER
