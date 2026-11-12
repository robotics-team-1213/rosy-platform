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


def test_drivable_run_refuses_a_missing_model_before_start(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    m = _module()
    monkeypatch.setattr(m, 'run', lambda _args: pytest.fail('simulation started without a model'))
    pointer = tmp_path / 'paint-pointer.txt'
    for content in (None, str(tmp_path / 'removed-model')):
        if content is not None:
            pointer.write_text(content, encoding='utf-8')
        with pytest.raises(SystemExit) as error:
            m.main(['--out', str(tmp_path / 'run'), '--learned-lane-pointer', str(pointer),
                    '--learned-paint-target', 'drivable', '--record'])
        assert error.value.code == 2
    assert 'no model manifest' in capsys.readouterr().err


def test_drivable_evidence_requires_the_model_during_motion(tmp_path):
    import json
    m = _module()
    trace = tmp_path / 'observations.jsonl'
    assert not m.drivable_evidence(trace, 'rev', ['rosy_01'])['pass']
    rows = [dict(wall=1.0, topic='/rosy_01/cmd_vel', message=dict(linear=dict(x=0.1), angular=dict(z=0))),
            *(dict(wall=1.1 + i / 10, topic='/rosy_01/line/keep_debug',
                   message=dict(paint_source_used='learned_drivable', paint_model_revision='rev')) for i in range(10)),
            dict(wall=2.1, topic='/rosy_01/cmd_vel', message=dict(linear=dict(x=0.1), angular=dict(z=0)))]
    trace.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    assert m.drivable_evidence(trace, 'rev', ['rosy_01'])['pass']
    assert not m.drivable_evidence(trace, 'rev', ['rosy_01', 'rosy_02'])['pass']
    rows[5]['message']['paint_source_used'] = 'denoise_fallback'
    trace.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    assert not m.drivable_evidence(trace, 'rev', ['rosy_01'])['pass']


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


def test_nav_run_turns_the_site_map_off_the_world_map_and_frees_every_edge(tmp_path):
    """D-1003 --nav: the native pose binding and the site map share one turned frame; robots keep the world map."""
    import json
    from types import SimpleNamespace
    m = _module()
    reservations = SimpleNamespace(api_ports=(18081, 18082), hub_url='http://127.0.0.1:18083', ros_domain_id=97)
    m.write_run(tmp_path, 'nav-test', 'nav-test', reservations, nav=True)
    tx, ty, turn = json.loads((tmp_path / 'binding.json').read_text())['map_from_world']
    assert (tx, ty, turn) == m.NAV_SITE_FROM_WORLD and math.hypot(tx, ty) > 3.0  # far off: a raw goal would miss
    x, y, yaw = m.to_site((1.0, 0.0, 0.0))
    assert (round(x, 9), round(y, 9), round(yaw, 9)) == (2.0, 4.0, round(math.pi / 2, 9))
    assert m.to_site((1.0, 2.0, 0.5), nav=False) == (1.0, 2.0, 0.5)
    base = {'places': [{'id': 'A', 'x': 1.0, 'y': 0.0, 'yaw': None, 'exit_yaw': 0.0}],
            'edges': [{'id': 'e', 'drive_mode': 'lane', 'polyline': [[0.0, 0.0], [1.0, 0.0]]}], 'crosswalks': [{}]}
    site = m.nav_site_map(base)
    assert [round(v, 9) for v in (site['places'][0]['x'], site['places'][0]['y'])] == [2.0, 4.0]
    assert site['places'][0]['yaw'] is None and round(site['places'][0]['exit_yaw'], 9) == round(math.pi / 2, 9)
    assert site['edges'][0]['drive_mode'] == 'free' and site['crosswalks'] == []
    assert [[round(v, 9) for v in q] for q in site['edges'][0]['polyline']] == [[2.0, 3.0], [2.0, 4.0]]
    m.write_run(tmp_path, 'nav-test', 'nav-test', reservations)
    assert json.loads((tmp_path / 'binding.json').read_text())['map_from_world'] == [0.0, 0.0, 0.0]


def test_the_two_camera_launch_takes_nav_mode_for_gz_multi():
    source = (Path(__file__).resolve().parents[1]
              / 'integrations/simulation/gazebo/launch/map_v2_fleet_multi_real.launch.py').read_text()
    assert "mode=LaunchConfiguration('nav_mode', default='none')" in source and "choices=['none', 'nav']" in source


def test_nav_run_raises_the_cyclone_participant_limit_only_for_nav(tmp_path):
    m = _module()
    assert m.cyclone_profile(tmp_path).name == 'cyclonedds_localhost.xml'
    nav = m.cyclone_profile(tmp_path, nav=True).read_text(encoding='utf-8')
    assert '<MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>' in nav and '<NetworkInterface name="lo"/>' in nav
