"""A new native identity cannot inherit cached World odometry or camera anchors."""
import asyncio

import pytest

from fleet.server.map_pose_service import MapPoseService
from test_map_pose_service import Wall, T0, state, row


def _setup():
    wall, active = Wall(), ['floor']
    poses = MapPoseService(lambda: ['r1'], wall=wall, map_id=lambda: active[0])
    assert hasattr(poses, 'begin_source_scope'), 'World ingestion has no native provenance fence'
    return poses, wall, active


def begin(poses, client=None, boot='boot-1', epoch='0'):
    return poses.begin_source_scope('r1', boot_id=boot, odom_epoch=epoch, client=client or object())


def measured(t, **changes):
    body = state(t)
    body['map_id'] = 'floor'
    body['odom_pose']['epoch'] = 0
    body.update(changes)
    return body


def localize(poses, wall, ticket):
    for _ in range(3):
        wall.now += .1
        assert poses.observe_qualified_state(ticket, measured(wall.now))
        poses.observe_sighting(row(wall.now) | {'map_id': 'floor'})
    assert poses.qualified_pose(ticket) is not None


def test_scope_requires_new_original_odom_and_camera_anchor():
    poses, wall, _ = _setup()
    ticket = begin(poses)
    poses.observe_state('r1', measured(wall.now))
    poses.observe_sighting(row(wall.now-.1) | {'map_id': 'floor'})
    assert poses.qualified_pose(ticket) is None
    localize(poses, wall, ticket)
    assert poses.qualified_pose(ticket).odom_stamp == wall.now


@pytest.mark.parametrize('change', ['boot', 'client', 'epoch', 'map'])
def test_identity_change_retires_previous_anchor_and_ticket(change):
    poses, wall, active = _setup()
    client = object()
    ticket = begin(poses, client)
    localize(poses, wall, ticket)
    wall.now += .1
    if change == 'map': active[0] = 'other-map'
    fresh = begin(poses, object() if change == 'client' else client,
                  boot='boot-2' if change == 'boot' else 'boot-1', epoch='1' if change == 'epoch' else '0')
    assert fresh != ticket
    assert poses.qualified_pose(ticket) is None
    assert poses.qualified_pose(fresh) is None


@pytest.mark.parametrize('fault', ['epoch', 'missing_epoch', 'robot', 'map', 'future', 'old'])
def test_unqualified_original_state_cannot_keep_previous_pose_live(fault):
    poses, wall, _ = _setup()
    ticket = begin(poses)
    localize(poses, wall, ticket)
    body = measured(wall.now+.01)
    if fault == 'epoch': body['odom_pose']['epoch'] = 1
    elif fault == 'missing_epoch': del body['odom_pose']['epoch']
    elif fault == 'robot': body['robot_id'] = 'other'
    elif fault == 'map': body['map_id'] = 'other'
    elif fault == 'future': body['odom_pose']['stamp'] = wall.now+10.
    else: body['odom_pose']['stamp'] = T0-.1
    assert not poses.observe_qualified_state(ticket, body)
    assert poses.qualified_pose(ticket) is None
    # Observing a broken input cannot be undone by replaying the last accepted sample.
    assert not poses.observe_qualified_state(ticket, measured(wall.now))
    assert poses.qualified_pose(ticket) is None


def test_unqualified_sink_cannot_replace_scoped_odom_and_pin_is_not_camera_proof():
    poses, wall, _ = _setup()
    ticket = begin(poses)
    localize(poses, wall, ticket)
    accepted = poses.qualified_pose(ticket)
    wall.now += .1
    poses.observe_state('r1', measured(wall.now, odom_pose=dict(x=50., y=0., yaw=0., stamp=wall.now, epoch=0)))
    assert poses.qualified_pose(ticket).odom_stamp == accepted.odom_stamp
    poses._tracker('r1').add_pin((20., 30., 0.), wall.now, 'floor')
    assert poses.qualified_pose(ticket) is None


@pytest.mark.parametrize('force_rest', [True, False])
def test_late_read_from_before_fence_cannot_populate_tracker_or_cache(force_rest):
    async def run():
        poses, wall, _ = _setup()
        started, release = asyncio.Event(), asyncio.Event()
        async def gather(robot):
            started.set()
            await release.wait()
            return measured(wall.now)
        poses._gather_rest = poses._gather = gather
        pending = asyncio.create_task(poses.state('r1') if force_rest else poses.refresh('r1'))
        await started.wait()
        ticket = begin(poses)
        release.set()
        await pending
        assert poses.survey_odom('r1') is None
        assert ('r1', force_rest) not in poses._kept
        assert poses.qualified_pose(ticket) is None
    asyncio.run(run())


def test_observed_map_change_cannot_revive_old_scope_when_map_returns():
    poses, wall, active = _setup()
    client = object()
    ticket = begin(poses, client)
    localize(poses, wall, ticket)
    active[0] = 'other-map'
    assert poses.qualified_pose(ticket) is None
    active[0] = 'floor'
    assert poses.qualified_pose(ticket) is None
    assert begin(poses, client) is not ticket


def test_same_identity_does_not_refresh_cutoff_and_original_samples_expire():
    poses, wall, _ = _setup()
    client = object()
    ticket = begin(poses, client)
    localize(poses, wall, ticket)
    assert begin(poses, client) is ticket
    assert ticket.not_before == T0
    original = wall.now
    wall.now += poses.config.max_odom_age_s+.01
    assert poses.qualified_pose(ticket) is None
    assert not poses.observe_qualified_state(ticket, measured(original))


def test_roster_removal_retires_ticket_even_if_same_id_returns():
    poses, wall, _ = _setup()
    ticket = begin(poses)
    localize(poses, wall, ticket)
    poses._robot_ids = lambda: []
    assert poses.arbitrated_pose('r1') is None
    poses._robot_ids = lambda: ['r1']
    assert poses.qualified_pose(ticket) is None


@pytest.mark.parametrize('clock_change', ['expiry', 'rollback'])
def test_world_accessor_cannot_return_pose_after_expiry_or_clock_reversal(clock_change):
    poses, wall, _ = _setup()
    ticket = begin(poses)
    localize(poses, wall, ticket)
    anchor = poses.odom_to_map
    def delayed(robot):
        result = anchor(robot)
        wall.now += poses.config.max_odom_age_s+.1 if clock_change == 'expiry' else -.1
        return result
    poses.odom_to_map = delayed
    assert poses.qualified_pose(ticket) is None
