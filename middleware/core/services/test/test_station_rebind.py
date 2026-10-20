"""New return sessions use fresh local standstill, never a previous departure receipt."""
import pytest

from core_features.docking.station_motion import StationMotionFeed
from test_station_departure_owner import stopped_departure


def completed():
    owner, manager, now, _, operation, command = stopped_departure()
    receipt = owner.finish_departure(command, principal_id=None)
    # A normal task may take much longer than either the original target or receipt lease.
    now[0] += 30.
    motion = StationMotionFeed(clock=lambda: now[0], source_clock=lambda: now[0],
        max_age_s=owner.profile.sample_max_age_s)
    owner.motion_feed = motion
    def sample(**changes):
        return motion.observe(stamp_ns=round(now[0]*1e9), source_now_ns=round(now[0]*1e9),
            frame_id='odom', child_frame_id='base_link', odom_epoch='odom-1',
            measured_linear_m_s=changes.get('linear', 0.), measured_angular_rad_s=0.)
    session = owner.session.model_copy(update={'session_id': 'charge-2', 'attempt_id': 'attempt-2',
        'state': 'RETURN_RESERVED', 'operation_id': None, 'updated_at': now[0]})
    target = owner.target.model_copy(update={'captured_at': now[0], 'valid_until': now[0]+10.})
    scope = owner.feed.scope.model_copy(update={'session_id': session.session_id,
        'captured_at': now[0], 'valid_until': now[0]+2., 'visible': False, 'pose': None})
    return owner, manager, now, sample, session, target, scope, receipt, operation


def observe_stop(owner, now, sample):
    for _ in range(6):
        now[0] += .1
        assert sample()
        owner.tick()


def test_new_session_after_normal_work_requires_new_stop_and_preserves_native_writer():
    owner, manager, now, sample, session, target, scope, receipt, operation = completed()
    observe_stop(owner, now, sample)
    ack = owner.bind(session, target, scope)
    assert ack.accepted and ack.session_id == session.session_id
    assert owner.state == 'BOUND' and owner.session.attempt_id == session.attempt_id
    assert manager.native.current.run_id == operation.run_id
    assert manager.executor.command == (0., 0.)
    assert owner.departure.receipt is None and owner.departure.permit is None
    assert owner.readback().departure_receipt is None
    assert receipt.valid_until < now[0]  # Expired history is not the new session's authority.
    old = session.model_copy(update={'session_id': 'charge-1', 'attempt_id': 'attempt-3'})
    with pytest.raises(ValueError, match='STATION_SESSION_RETIRED'):
        owner.bind(old, target, scope.model_copy(update={'session_id': old.session_id}))
    assert owner.state == 'BOUND' and owner.session.session_id == session.session_id


@pytest.mark.parametrize('fault', ['missing_motion', 'moving', 'stale', 'no_dwell', 'manual',
    'same_attempt', 'old_request', 'wrong_battery', 'wrong_map', 'wrong_boot', 'native_fence'])
def test_unverified_next_binding_keeps_completed_session_without_motion_or_receipt_transfer(fault):
    owner, manager, now, sample, session, target, scope, receipt, operation = completed()
    if fault not in ('missing_motion', 'no_dwell'):
        observe_stop(owner, now, sample)
    if fault == 'moving':
        now[0] += .05
        assert sample(linear=.02)
    elif fault == 'stale':
        now[0] += .3
    elif fault == 'no_dwell':
        assert sample()
    elif fault == 'manual':
        original = owner.local_scope
        owner.local_scope = owner.local_scope_nowait = lambda: original() | {'mode': 'MANUAL'}
    elif fault in ('same_attempt', 'old_request', 'wrong_battery', 'wrong_map', 'wrong_boot'):
        change = {'same_attempt': {'attempt_id': owner.session.attempt_id},
            'old_request': {'updated_at': receipt.captured_at}, 'wrong_battery': {'battery_id': 'other'},
            'wrong_map': {'map_revision': 'other'}, 'wrong_boot': {'boot_id': 'other'}}[fault]
        session = session.model_copy(update=change)
    kwargs = dict(expected_owner_generation=manager.native_owner()['owner_generation']-1) if fault == 'native_fence' else {}
    with pytest.raises(ValueError):
        owner.bind(session, target, scope, **kwargs)
    assert owner.session.session_id == 'charge-1' and owner.state == 'WORK_AVAILABLE'
    assert owner.departure.receipt == receipt
    assert manager.native.current.run_id == operation.run_id and manager.executor.command == (0., 0.)


def test_movement_between_stop_samples_discards_dwell_and_delayed_binding_can_retry():
    owner, _, now, sample, session, target, scope, _, _ = completed()
    observe_stop(owner, now, sample)
    now[0] += .05
    assert sample(linear=.02)
    owner.tick()
    now[0] += .05
    assert sample()
    with pytest.raises(ValueError):
        owner.bind(session, target, scope)
    assert owner.state == 'WORK_AVAILABLE'
    observe_stop(owner, now, sample)
    assert owner.bind(session, target, scope).accepted


def test_clock_recovery_cannot_restore_expired_stop_from_the_same_motion_sample():
    owner, _, now, sample, session, target, scope, _, _ = completed()
    observe_stop(owner, now, sample)
    at = now[0]
    now[0] += .3
    owner.tick()  # Observe expiry before the clocks return to their previous values.
    now[0] = at
    with pytest.raises(ValueError):
        owner.bind(session, target, scope)
    assert owner.state == 'WORK_AVAILABLE'
    observe_stop(owner, now, sample)
    assert owner.bind(session, target, scope).accepted


def test_source_clock_progress_without_real_monotonic_dwell_cannot_start_next_session():
    owner, _, utc, sample, session, target, scope, _, _ = completed()
    mono = [1_000_000.]
    owner.clock = owner.motion_feed.clock = lambda: mono[0]
    for _ in range(6):
        utc[0] += .1
        mono[0] += .001
        assert sample()
        owner.tick()
    with pytest.raises(ValueError):
        owner.bind(session, target, scope)
    assert owner.state == 'WORK_AVAILABLE'
    for _ in range(6):
        utc[0] += .1
        mono[0] += .1
        assert sample()
        owner.tick()
    assert owner.bind(session, target, scope).accepted
