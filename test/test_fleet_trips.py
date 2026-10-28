"""tools/sim/fleet_trips.py: the two lane trips are straight, on their road and clear of crosswalks."""
import importlib.util
import math
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/sim/fleet_trips.py'


def _module():
    spec = importlib.util.spec_from_file_location('fleet_trips', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('enabled', [False, True])
def test_run_overlay_explicitly_configures_route_guide(tmp_path, enabled):
    from types import SimpleNamespace
    m = _module()
    reservations = SimpleNamespace(api_ports=(18081, 18082), hub_url='http://127.0.0.1:18083', ros_domain_id=97)
    m.write_run(tmp_path, 'route-test', 'route-test', reservations, route_guide=enabled)
    for robot in m.ROBOTS:
        config = yaml.safe_load((tmp_path / f'core_{robot}.yaml').read_text())
        assert config['line_follow']['route_guide_enabled'] is enabled



def test_a_skipped_check_is_switched_off_only_in_the_run_overlay(tmp_path):
    from types import SimpleNamespace
    m = _module()
    reservations = SimpleNamespace(api_ports=(18081, 18082), hub_url='http://127.0.0.1:18083', ros_domain_id=97)
    m.write_run(tmp_path, 'skip-test', 'skip-test', reservations, skip=['crosswalk', 'lane_return'])
    line = yaml.safe_load((tmp_path / f'core_{m.ROBOTS[0]}.yaml').read_text())['line_follow']
    assert line['crosswalk_gate_enabled'] is False and line['recovery_local_enabled'] is False
    m.write_run(tmp_path, 'skip-test', 'skip-test', reservations)
    line = yaml.safe_load((tmp_path / f'core_{m.ROBOTS[0]}.yaml').read_text())['line_follow']
    assert 'crosswalk_gate_enabled' not in line and 'recovery_local_enabled' not in line

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


def test_lap_starts_and_ends_at_one_place_via_the_other_road_with_the_parked_robot_off_every_lane():
    m = _module()
    graph = yaml.safe_load(m.GRAPH.read_text(encoding='utf-8'))
    spawns, places, requests = m.layout(graph, lap=True)
    assert set(spawns) == set(m.ROBOTS) and list(requests) == ['rosy_01']
    body = requests['rosy_01']
    assert body['to'] == body['start_at'] and places[body['to']] == spawns['rosy_01'] and body['via'] == ['lap_via']
    lanes = [p for seg in graph['segments'].values() for p in seg['points']]
    assert min(math.dist(spawns['rosy_02'][:2], p) for p in lanes) > 0.2   # the lap never brushes it
    assert m.layout(graph)[2] == {ns: {'to': m.place_id(ns), 'speed_cap': m.SPEED_CAP} for ns in m.ROBOTS}


def test_remote_sim_runs_the_bench_and_installs_the_fleet_and_learned_inputs():
    import sys
    sys.path.insert(0, str(SCRIPT.parents[1] / 'remote'))
    import remote_sim as rs
    assert 'tools/sim/fleet_trips.py' in rs.BENCHES['fleet_trips']
    assert 'requirements-fleet.txt' in rs.SIM and 'learned-perception-requirements.txt' in rs.SIM
    assert 'ROSY_LEARNED_SITE="$PYDEPS/learned"' in rs.INNER


def test_every_lap_scenario_starts_and_ends_on_the_lap_route():
    import math
    import sys
    m = _module()
    sys.path.insert(0, str(m.REPO / 'tools/sim'))
    from lap_scenarios import SCENARIOS
    graph = yaml.safe_load(m.GRAPH.read_text(encoding='utf-8'))
    for name, (start, end, _) in SCENARIOS.items():
        spawns, places, requests = m.layout(graph, name)
        assert set(places) == {'scenario_end'} and requests['rosy_01']['to'] == 'scenario_end'
        assert spawns['rosy_02'] == tuple(graph['parking']['spot'])
        assert 0.5 < end - start <= 1.5 and math.dist(spawns['rosy_01'][:2], places['scenario_end'][:2]) > 0.2, name
