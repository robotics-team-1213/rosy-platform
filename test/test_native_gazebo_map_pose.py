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


def setup(transform=(0., 0., 0.)):
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
    return port.observe(sample, clock_stamp_ns=clock_ns)


def test_native_pose_preserves_real_core_utc_stamp_and_declares_sim_source():
    _, port, sample, _, _ = setup()
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02', force_rest=True))
    pose = port.arbitrated_pose('rosy_02')
    assert (pose.x, pose.y, pose.yaw, pose.state) == (1., 2., .3, 'LOCALIZED')
    assert pose.source == pose.anchor_source == 'native_gazebo_sim'
    assert pose.odom_stamp == 1000. and pose.odom_stamp != 2.
    assert pose.map_id == 'map_v2_fleet' and pose.dead_reckon_m == 0.
    assert port.diagnostics('rosy_02')['native_stamp_ns'] == 2_000_000_000


def test_declared_world_to_map_transform_is_applied():
    _, port, sample, _, _ = setup((10., -2., math.pi / 2))
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
    _, port, sample, _, _ = setup()
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
    _, port, sample, _, _ = setup()
    assert not feed(port, replace(sample, **changes), clock)
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_replayed_sample_and_clock_reset_do_not_automatically_recover():
    _, port, sample, _, _ = setup()
    assert feed(port, sample)
    assert not feed(port, sample)
    assert not feed(port, replace(sample, stamp_ns=2_020_000_000), 2_030_000_000)
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    _, fresh, sample, _, _ = setup()
    assert feed(fresh, sample)
    assert not feed(fresh, replace(sample, stamp_ns=1_000_000_000), 1_010_000_000)
    assert fresh.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_receipt_staleness_and_wall_rollback_fail_closed():
    _, port, sample, clocks, _ = setup()
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02'))
    clocks['mono'] += 1.
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    _, port, sample, clocks, _ = setup()
    assert feed(port, sample)
    asyncio.run(port.refresh('rosy_02'))
    clocks['wall'] -= 1.
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_core_stamp_is_validated_not_synthesized_or_replaced_by_native_time():
    _, port, sample, clocks, core = setup()
    assert feed(port, sample)
    core['odom_pose']['stamp'] = 2.
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'
    core['odom_pose']['stamp'] = clocks['wall']
    asyncio.run(port.refresh('rosy_02'))
    assert port.arbitrated_pose('rosy_02').state == 'UNKNOWN'


def test_unknown_robot_and_motion_deadband_do_not_invent_poses():
    _, port, sample, _, _ = setup()
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
    m, _, sample, _, _ = setup()
    with pytest.raises(ValueError):
        m.NativeGazeboMapPosePort(replace(sample.binding, **changes), gather_core=None)
