"""D-620: paired Fleet replies use the existing signal table, never another robot's identity."""
from types import SimpleNamespace

import pytest

from core_common.protocol.schemas import Envelope, EnvelopeType, HeartbeatPayload, StateSnapshot
from fleet.hub.hub import SiteHub
from fleet.server.junction_signal import signal_for
from test_hub import _ep, _hello
from test_traffic_signals import _setup, _signals

REQUEST = 'a' * 32


def heartbeat(robot_id='rosy_01'):
    return Envelope(type=EnvelopeType.HEARTBEAT, payload=HeartbeatPayload(
        state_snapshot=StateSnapshot(robot_id=robot_id), junction_signal_request=REQUEST).model_dump(mode='json'))


def test_paired_query_returns_correlated_signal_but_unpaired_or_other_identity_does_not():
    hub = SiteHub([_ep()])
    seen = []
    hub.junction_signal = lambda robot: seen.append(robot) or dict(lamp='red', may_enter=False, reason='test')
    session = hub.open_session()
    assert hub.handle(heartbeat(), session=session).type == EnvelopeType.ERROR
    hub.handle(_hello(), session=session)
    reply = hub.handle(heartbeat(), session=session)
    assert reply.payload['junction_signal'] == dict(request_id=REQUEST, lamp='red', may_enter=False, reason='test')
    assert hub.handle(heartbeat('other'), session=session).type == EnvelopeType.ERROR
    assert seen == ['rosy_01']


@pytest.mark.parametrize('broken', [False, True])
def test_missing_or_failed_signal_lookup_is_answered_unknown(broken):
    hub = SiteHub([_ep()])
    hub.handle(_hello())
    if broken:
        def fail(_robot):
            raise RuntimeError('test')
        hub.junction_signal = fail
    reply = hub.handle(heartbeat()).payload['junction_signal']
    assert reply['request_id'] == REQUEST and reply['lamp'] == 'unknown' and not reply['may_enter']


def test_mapped_free_approach_is_green_and_busy_zone_is_not_permission():
    runner, _store, _fleet, entries = _setup()
    _signals(runner)
    traffic = runner.traffic
    assert traffic.junction_signal('robot', entries[0]) == dict(lamp='green', may_enter=True, reason='approach_signal')
    traffic._busy = frozenset({'roundabout'})
    traffic._occupancy['roundabout'] = ('occupied', 'other', entries[0])
    assert not traffic.junction_signal('robot', entries[0])['may_enter']
    assert traffic.junction_signal('robot', 'unmapped')['lamp'] == 'unknown'


def test_unknown_pose_does_not_guess_a_signal_or_entry():
    poses = SimpleNamespace(arbitrated_pose=lambda _robot: None)
    traffic = SimpleNamespace(signal_ahead=lambda _robot: None)
    store = SimpleNamespace(active=lambda: None)
    assert signal_for('robot', traffic=traffic, poses=poses, site_maps=store) == dict(
        lamp='unknown', may_enter=False, reason='pose_unknown')


def test_standalone_signal_uses_fresh_inside_lane_map_context():
    runner, store, fleet, entries = _setup()
    _signals(runner)
    arc = store.active()[2].arcs[entries[0]]
    x, y, yaw = arc.point_at(arc.length_m-.1)
    pose = SimpleNamespace(state='LOCALIZED', age_s=.1, x=x, y=y, yaw=yaw)
    poses = SimpleNamespace(arbitrated_pose=lambda _robot: pose)
    assert signal_for('robot', traffic=runner.traffic, poses=poses, site_maps=store)['may_enter']
    pose.age_s = 3
    assert not signal_for('robot', traffic=runner.traffic, poses=poses, site_maps=store)['may_enter']
