"""Explicit native SIM pose provenance and fail-closed lifetime, never Vision."""
import asyncio
import importlib.util
import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'tools/sim/native_gazebo_map_pose.py'


def module():
    assert SCRIPT.is_file(), 'The explicit SIM native MapPose port is missing'
    spec = importlib.util.spec_from_file_location('native_gazebo_map_pose', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _setup(transform=(0., 0., 0.)):
    m = module()
    clocks = dict(wall=1000., mono=10.)
    binding = m.NativeGazeboBinding(
        run_id='owned-run-1', epoch=1, world='map_v2_fleet', map_id='map_v2_fleet',
        map_revision=1, source_revision='a' * 40, world_sha256='b' * 64,
        graph_sha256='c' * 64, urdf_sha256='d' * 64, domain_id=89,
        partition='owned-partition-1', map_from_world=transform,
        robots=(m.NativeRobotBinding('rosy_02', 'rosy_02', 'rosy_02/odom'),))
    core = {'robot_id': 'rosy_02', 'odom_pose': dict(x=1., y=2., yaw=.3, stamp=1000.)}

    async def gather(robot_id):
        assert robot_id == 'rosy_02'
        return core

    port = m.NativeGazeboMapPosePort(binding, gather_core=gather,
        wall=lambda: clocks['wall'], monotonic=lambda: clocks['mono'])
    sample = m.NativeGazeboSample(binding, 'rosy_02', 'rosy_02', 'rosy_02/odom',
                                 stamp_ns=2_000_000_000, pose=(1., 2., .3))
    return m, port, sample, clocks, core


def feed(port, sample, clock_ns=2_010_000_000):
    port.observe_clock(clock_ns)
    return port.observe(sample, clock_stamp_ns=clock_ns)


@pytest.mark.parametrize('delay', [.03, .2])
def test_buffered_join_preserves_receipt_without_counting_delay_twice(delay):
    _, port, sample, clocks, _ = _setup()
    clocks['wall'] += delay
    clocks['mono'] += delay
    assert port.observe_clock(2_000_000_000 + round(delay * 1e9))
    assert port.observe(sample, received_wall=1000., received_monotonic=10.)
    asyncio.run(port.refresh('rosy_02'))
    diag = port.diagnostics('rosy_02')
    assert diag['receipt_age_s'] == pytest.approx(delay)
    assert diag['native_age_s'] == pytest.approx(delay)
    assert diag['received_wall'] == 1000.
    assert diag['received_monotonic'] == 10.
    assert port.arbitrated_pose('rosy_02').age_s == pytest.approx(delay)
    assert port._history['rosy_02'][0][0] == 10.
    clocks['wall'] += .01
    clocks['mono'] += .01
    assert port.arbitrated_pose('rosy_02').age_s == pytest.approx(delay + .01)


@pytest.mark.parametrize('wall,mono', [
    (True, 10.), (1000., True), (float('nan'), 10.),
    (1000., float('inf')), (1000.01, 10.), (1000., 10.01),
    (999.74, 10.), (1000., 9.74),
])
def test_original_receipt_malformed_future_or_stale_latches_unknown(wall, mono):
    _, port, sample, _, _ = _setup()
    assert port.observe_clock(2_010_000_000)
    assert not port.observe(sample, received_wall=wall, received_monotonic=mono)
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_original_receipt_cannot_reverse_previous_receipt():
    _, port, sample, clocks, _ = _setup()
    assert feed(port, sample)
    clocks['wall'] += .05
    clocks['mono'] += .05
    assert port.observe_clock(2_060_000_000)
    assert not port.observe(replace(sample, stamp_ns=2_050_000_000),
                            received_wall=999.99, received_monotonic=9.99)


def test_buffered_receipt_does_not_refresh_independent_clock_age():
    _, port, sample, clocks, _ = _setup()
    assert port.observe_clock(2_010_000_000)
    clocks['wall'] += .26
    clocks['mono'] += .26
    assert not port.observe(sample, received_wall=1000.25, received_monotonic=10.25)


def test_native_pose_preserves_real_core_utc_stamp_and_declares_sim_source():
    _, port, sample, _, _ = _setup()
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02', force_rest=True))
    pose = port.arbitrated_pose('rosy_02')
    assert (pose.x, pose.y, pose.yaw, pose.state) == (1., 2., .3, 'LOCALIZED')
    assert pose.source == pose.anchor_source == 'native_gazebo_sim'
    assert pose.odom_stamp == 1000. and pose.odom_stamp != 2.
    assert pose.map_id == 'map_v2_fleet' and pose.dead_reckon_m == 0.
    assert port.diagnostics('rosy_02')['native_stamp_ns'] == 2_000_000_000


def test_declared_world_to_map_transform_is_applied():
    _, port, sample, _, _ = _setup((10., -2., math.pi / 2))
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02'))
    pose = port.arbitrated_pose('rosy_02')
    assert (pose.x, pose.y) == pytest.approx((8., -1.))
    assert pose.yaw == pytest.approx(.3 + math.pi / 2)


@pytest.mark.parametrize('field,value', [
    ('run_id', 'foreign'), ('epoch', 2), ('world', 'foreign'), ('map_id', 'other'),
    ('map_revision', 2), ('source_revision', 'e' * 40), ('world_sha256', 'e' * 64),
    ('graph_sha256', 'e' * 64), ('urdf_sha256', 'e' * 64), ('domain_id', 90),
    ('partition', 'foreign'), ('map_from_world', (1., 0., 0.)),
])
def test_foreign_binding_latches_unknown(field, value):
    _, port, sample, _, _ = _setup()
    foreign = replace(sample, binding=replace(sample.binding, **{field: value}))
    assert not feed(port, foreign)
    assert not feed(port, sample)
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


@pytest.mark.parametrize('changes,clock', [
    ({'model': 'foreign'}, 2_010_000_000),
    ({'frame_id': 'map'}, 2_010_000_000),
    ({'stamp_ns': True}, 2_010_000_000),
    ({'stamp_ns': -1}, 2_010_000_000),
    ({'pose': (float('nan'), 2., .3)}, 2_010_000_000),
    ({'pose': (1., float('inf'), .3)}, 2_010_000_000),
    ({}, 1_999_000_000), ({}, 3_000_000_000),
])
def test_invalid_or_future_or_stale_native_sample_never_localizes(changes, clock):
    _, port, sample, _, _ = _setup()
    assert not feed(port, replace(sample, **changes), clock)
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_replayed_sample_and_clock_reset_do_not_automatically_recover():
    _, port, sample, _, _ = _setup()
    assert feed(port, sample)
    assert not feed(port, sample)
    assert not feed(port, replace(sample, stamp_ns=2_020_000_000), 2_030_000_000)
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    _, fresh, sample, _, _ = _setup()
    assert feed(fresh, sample)
    assert not feed(fresh, replace(sample, stamp_ns=1_000_000_000), 1_010_000_000)
    assert fresh.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_receipt_staleness_and_wall_rollback_fail_closed():
    _, port, sample, clocks, _ = _setup()
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02'))
    clocks['mono'] += 1.
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    _, port, sample, clocks, _ = _setup()
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02'))
    clocks['wall'] -= 1.
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_core_stamp_is_validated_not_synthesized_or_replaced_by_native_time():
    _, port, sample, clocks, core = _setup()
    assert feed(port, sample)
    core['odom_pose']['stamp'] = 2.
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    core['odom_pose']['stamp'] = clocks['wall']
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_unknown_robot_and_motion_deadband_do_not_invent_poses():
    _, port, sample, _, _ = _setup()
    assert port.arbitrated_pose('unknown') is None
    assert not port.knows('unknown') and port.knows('rosy_02')
    assert not port.moved('rosy_02', .005, 1.)
    assert feed(port, sample)
    assert feed(port, replace(sample, stamp_ns=2_033_000_000, pose=(1.02, 2., .3)), 2_040_000_000)
    asyncio.run(port.refresh('rosy_02'))
    assert port.moved('rosy_02', .005, 1.)


@pytest.mark.parametrize('changes', [
    {'source_revision': 'main'}, {'world_sha256': 'b'}, {'domain_id': 40},
    {'epoch': 0}, {'map_revision': 0}, {'map_from_world': (0., 0., float('nan'))},
])
def test_binding_rejects_unscoped_or_physical_identity(changes):
    m, _, sample, _, _ = _setup()
    with pytest.raises(ValueError):
        m.NativeGazeboMapPosePort(replace(sample.binding, **changes), gather_core=lambda _: None)


def test_sample_cannot_refresh_a_stopped_clock_or_hide_delayed_receipt():
    _, port, sample, clocks, _ = _setup()
    assert feed(port, sample)
    clocks['mono'] += .3
    clocks['wall'] += .3
    newer = replace(sample, stamp_ns=2_011_000_000)
    assert not port.observe(newer, clock_stamp_ns=2_010_000_000)
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_core_pose_contradiction_and_native_reset_never_recover_in_same_run():
    _, port, sample, _, core = _setup()
    assert feed(port, sample)
    core['odom_pose']['x'] = 2.
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    core['odom_pose']['x'] = 1.
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_runner_manifest_must_match_provider_binding():
    from dataclasses import asdict
    _, port, sample, _, _ = _setup()
    port.validate_simulation_binding(asdict(sample.binding))
    with pytest.raises(ValueError):
        port.validate_simulation_binding({**asdict(sample.binding), 'epoch': 2})


def app_with_port(tmp_path, port, *, profile='simulation', expected=None):
    import inspect
    from dataclasses import asdict
    from fastapi.testclient import TestClient
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.site_map_store import SiteMapStore
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.site_map import from_lane_graph
    from fleet.swarm.robots import RobotEndpoint
    root = SCRIPT.parents[2]
    sys.path.insert(0, str(root / 'operations/fleet/test'))
    from fakes import FakeRobot
    assert 'simulation_pose_binding' in inspect.signature(create_app).parameters, 'Explicit SIM binding DI is missing'
    robot = FakeRobot('rosy_02', state={'robot_id': 'rosy_02'})
    console = FleetConsole([RobotEndpoint('rosy_02', 'http://127.0.0.1:8080', 'robot-rest')], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / 'fleet.sqlite'), robot_ids={'rosy_02'})
    maps = SiteMapStore(tmp_path / 'fleet.sqlite')
    maps.import_if_empty(from_lane_graph(root / 'middleware/perception/map/map_v2_fleet/training-curved/lane_graph.yaml',
                                         map_id='map_v2_fleet'), source='test-native-source')
    app = create_app(console, task_service=tasks, console_token='console-secret',
        start_task_dispatcher=False, site_maps=maps, map_pose_port=port,
        deployment_profile=profile, simulation_pose_binding=expected or asdict(port.binding))
    return app, TestClient(app)


def test_sim_execution_consumers_share_provider_while_teach_and_ingest_keep_original(tmp_path):
    _, port, sample, _, _ = _setup()
    assert feed(port, sample)
    app, client = app_with_port(tmp_path, port)
    result = client.get('/api/fleet/robots/rosy_02/map-pose', headers={'Authorization': 'Bearer console-secret'})
    assert result.status_code == 200, result.text
    assert result.json()['source'] == 'native_gazebo_sim'
    assert result.json()['state'] == 'LOCALIZED'
    assert app.state.execution_map_pose is port
    assert app.state.trip_runner._poses is port
    assert app.state.lane_compliance._poses is port
    assert app.state.map_pose is not port
    assert app.state.teach._poses is app.state.map_pose


def test_sim_provider_is_refused_in_production_or_with_foreign_runner_manifest(tmp_path):
    from dataclasses import asdict
    _, port, _, _, _ = _setup()
    with pytest.raises(ValueError, match='simulation deployment'):
        app_with_port(tmp_path, port, profile='production')
    with pytest.raises(ValueError, match='explicit runner binding'):
        app_with_port(tmp_path, port, expected={**asdict(port.binding), 'partition': 'foreign'})


def test_changed_active_map_revokes_provider_without_recovery():
    _, port, sample, _, _ = _setup()
    revision = ['map_v2_fleet', 1]
    port.bind_active_map(lambda: tuple(revision))
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'LOCALIZED'
    revision[1] = 2
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    revision[1] = 1
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_motion_deadband_uses_recent_window_and_expires_after_stillness():
    _, port, sample, clocks, core = _setup()
    assert feed(port, sample)
    stamp = sample.stamp_ns
    for i in range(1, 6):
        clocks['wall'] += .05; clocks['mono'] += .05; stamp += 50_000_000
        assert feed(port, replace(sample, stamp_ns=stamp, pose=(1. + i*.004, 2., .3)), stamp + 10_000_000)
    asyncio.run(port.refresh('rosy_02'))
    assert port.moved('rosy_02', .01, 1.)
    for _ in range(32):
        clocks['wall'] += .1; clocks['mono'] += .1; stamp += 100_000_000
        assert feed(port, replace(sample, stamp_ns=stamp, pose=(1.02, 2., .3)), stamp + 10_000_000)
        core['odom_pose'].update(x=1.02, stamp=clocks['wall'])
        asyncio.run(port.refresh('rosy_02'))
    assert not port.moved('rosy_02', .01, 1.)


def test_same_core_stamp_cannot_describe_a_different_pose():
    _, port, sample, _, core = _setup()
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02'))
    core['odom_pose']['x'] = 1.01
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_a_late_clock_reads_unknown_until_fresh_and_a_clock_regression_latches():
    """D-725 rev 1 (v2 lap r32, model PC load 24): a /clock tick late under load is not a reset. The old
    sample is stale, so the pose reads UNKNOWN; a fresh sample with a fresh CORE snapshot localizes again.
    A clock that goes backwards still revokes the run."""
    _, port, sample, clocks, core = _setup()
    assert feed(port, sample)
    clocks['mono'] += .3; clocks['wall'] += .3
    assert port.observe_clock(2_310_000_000)
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    assert port.observe(replace(sample, stamp_ns=2_300_000_000), clock_stamp_ns=2_310_000_000)
    core['odom_pose']['stamp'] = clocks['wall']
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'LOCALIZED'
    assert not port.observe_clock(2_000_000_000)
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    clocks['mono'] += .05; clocks['wall'] += .05
    assert port.observe_clock(2_400_000_000)
    assert not port.observe(replace(sample, stamp_ns=2_390_000_000))  # the robot stays revoked for the run
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_a_native_gap_is_spanned_by_stamp_but_a_jump_across_it_latches():
    _, port, sample, clocks, core = _setup()
    assert feed(port, sample)
    for i in range(1, 7):
        clocks['mono'] += .05; clocks['wall'] += .05
        assert port.observe_clock(2_010_000_000 + i*50_000_000)
    assert port.observe(replace(sample, stamp_ns=2_300_000_000))     # 0.3 s gap, no motion: admitted
    core['odom_pose']['stamp'] = clocks['wall']
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'LOCALIZED'
    clocks['mono'] += .05; clocks['wall'] += .05
    assert port.observe_clock(2_360_000_000)
    jumped = replace(sample, stamp_ns=2_350_000_000, pose=(sample.pose[0] + 1.0, *sample.pose[1:]))
    assert not port.observe(jumped)                                   # faster than the robot moves
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    assert not port.observe(replace(sample, stamp_ns=2_350_000_000))  # latched


def test_immutable_run_binding_refuses_mutable_robot_collections():
    m, _, sample, _, _ = _setup()
    with pytest.raises(ValueError):
        m.NativeGazeboMapPosePort(replace(sample.binding, robots=list(sample.binding.robots)),
                                 gather_core=lambda _: None)


def test_one_failed_core_read_keeps_the_pose_until_the_snapshot_ages_out():
    _, port, sample, clocks, _ = _setup()
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'LOCALIZED'

    async def broken(robot_id):
        raise OSError('CORE busy')
    port._gather_core = broken
    with pytest.raises(OSError):
        asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'LOCALIZED'
    clocks['wall'] += port.config.max_odom_age_s + 1
    clocks['mono'] += port.config.max_odom_age_s + 1
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_a_core_snapshot_without_odometry_yet_waits_instead_of_latching():
    _, port, sample, _, core = _setup()
    assert feed(port, sample)
    odom = core.pop('odom_pose')
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    core['odom_pose'] = odom
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'LOCALIZED'


def test_a_clock_pause_or_restart_before_any_pose_only_re_anchors():
    _, port, sample, clocks, core = _setup()
    assert port.observe_clock(3_000_000)
    clocks['mono'] += 1.0; clocks['wall'] += 1.0            # Gazebo stalls while it spawns the robots
    assert port.observe_clock(1_000_000)                     # ... and restarts its clock
    assert port.observe_clock(2_010_000_000)
    assert port.observe(sample, clock_stamp_ns=2_010_000_000)
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'LOCALIZED'
