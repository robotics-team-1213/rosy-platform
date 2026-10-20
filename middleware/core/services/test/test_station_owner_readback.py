"""Runtime fencing and live readback of the real station owner."""
import pytest

from core_features.docking.database import DockError
from test_station_docking_owner import setup_owner, frame, seated_owner, charge_evidence
from test_station_feed import observation


def test_binding_fences_native_owner_and_principal_before_any_change():
    owner, manager, _, _, target, session, _ = setup_owner()
    with pytest.raises((ValueError, DockError)):
        owner.bind(session, target, observation(boot_id=session.boot_id), principal_id='fleet-a',
                   expected_boot_id=session.boot_id, expected_owner_generation=9)
    assert owner.session is None
    assert manager.database.get('charger-1').x == 0.
    owner.bind(session, target, observation(boot_id=session.boot_id), principal_id='fleet-a',
               expected_boot_id=session.boot_id, expected_owner_generation=0)
    with pytest.raises(ValueError, match='PRINCIPAL'):
        owner.bind(session, target, observation(boot_id=session.boot_id), principal_id='fleet-b',
                   expected_boot_id=session.boot_id, expected_owner_generation=0)
    assert owner.state == 'BOUND' and manager.native.current is None


def test_readback_retains_actual_correlation_but_never_stale_completion():
    owner, manager, now, _, target, session, _ = setup_owner()
    assert owner.readback().state == 'UNBOUND'
    owner.bind(session, target, observation(boot_id=session.boot_id))
    assert owner.readback().binding_valid
    frame(owner, now)
    operation = owner.start_docking(correlation_id='intent-1', expected_boot_id=session.boot_id,
                                    expected_owner_generation=0)
    live = owner.readback()
    assert live.correlation_id == 'intent-1' and live.operation_id == str(operation.run_id)
    assert not live.seating_verified and not live.completion_verified
    now[0] = target.valid_until
    stale = owner.readback()
    assert not stale.binding_valid and not stale.completion_verified
    assert stale.operation_id == str(operation.run_id)


def test_motion_uses_callers_generation_instead_of_silently_refreshing_it():
    owner, manager, now, _, target, session, _ = setup_owner()
    owner.bind(session, target, observation(boot_id=session.boot_id))
    frame(owner, now)
    with pytest.raises((ValueError, DockError)):
        owner.start_docking(correlation_id='stale', expected_boot_id=session.boot_id,
                            expected_owner_generation=99)
    assert manager.native.current is None


@pytest.mark.parametrize('fault', ['same_capture', 'expired_binding'])
def test_target_refresh_cannot_extend_replayed_or_already_expired_source(fault):
    owner, manager, now, _, target, session, _ = setup_owner()
    owner.bind(session, target, observation(boot_id=session.boot_id))
    if fault == 'expired_binding':
        now[0] = target.valid_until
    renewed = target.model_copy(update={
        'captured_at': target.captured_at if fault == 'same_capture' else now[0], 'valid_until': now[0]+20.})
    with pytest.raises(ValueError):
        owner.bind(session, renewed, owner.feed.scope.model_copy(update={
            'captured_at': now[0], 'valid_until': now[0]+.2}))
    assert owner.target == target
    assert manager.native.current is None


def test_refresh_changes_only_global_evidence_not_seating_or_camera_lifetimes():
    from core_features.docking.agent import DockReachability, DockStatus
    owner, manager, now = seated_owner()
    evidence = charge_evidence(now[0], termination='NORMAL', charging=False)
    status = DockStatus(load_present=True, charging=False, reachability=DockReachability.OK,
        termination='NORMAL', termination_source=evidence.source,
        termination_sample_at=evidence.termination_sample_at, battery_id=evidence.battery_id)
    assert owner.update_charge(status, evidence, received_at=now[0])
    assert owner.readback().completion_verified
    previous_feed, previous_seating, previous_charge = owner.feed, owner._seated_until, owner._charge_until
    operation = manager.native.current
    renewed = owner.target.model_copy(update={'captured_at': now[0], 'valid_until': now[0]+20.})
    scope = owner.feed.scope.model_copy(update={'captured_at': now[0], 'valid_until': now[0]+.2})
    assert owner.bind(owner.session, renewed, scope).accepted
    assert owner.target == renewed and owner.feed is previous_feed
    assert owner._seated_until == previous_seating and manager.native.current is operation
    assert owner._charge_until == previous_charge and owner.readback().completion_verified
    now[0] += .3
    assert owner.readback().binding_valid
    assert not owner.readback().seating_verified
    assert not owner.readback().completion_verified


@pytest.mark.parametrize('future', [False, True])
def test_core_rejects_expired_or_future_observation_permission_on_refresh(future):
    owner, _, now, _, target, session, _ = setup_owner()
    owner.bind(session, target, observation(boot_id=session.boot_id))
    now[0] += .1
    renewed = target.model_copy(update={'captured_at': now[0], 'valid_until': now[0]+20.})
    scope = owner.feed.scope.model_copy(update=(
        {'captured_at': now[0]+.01, 'valid_until': now[0]+.2} if future else {'valid_until': now[0]-.01}))
    with pytest.raises(ValueError):
        owner.bind(session, renewed, scope)
    assert owner.target == target


def test_completion_readback_expires_without_waiting_for_background_tick():
    owner, _, now = seated_owner()
    from core_features.docking.agent import DockStatus, DockReachability
    evidence = charge_evidence(now[0], termination='NORMAL', charging=False)
    status = DockStatus(load_present=True, charging=False, reachability=DockReachability.OK,
                        termination='NORMAL', termination_source=evidence.source,
                        termination_sample_at=evidence.termination_sample_at, battery_id=evidence.battery_id)
    assert owner.update_charge(status, evidence, received_at=now[0])
    assert owner.readback().completion_verified
    now[0] += 0.3
    assert owner.state == 'CHARGED_HOLD'
    assert not owner.readback().completion_verified


@pytest.mark.parametrize('pose', [None, {'x': 0.08, 'y': 0., 'yaw': 0.}])
def test_new_bad_camera_sample_revokes_seating_before_tick(pose):
    owner, _, now = seated_owner()
    assert owner.readback().seating_verified
    owner.ingest(observation(boot_id=owner.session.boot_id, sequence=100, captured_at=now[0],
                             valid_until=now[0]+0.2, visible=pose is not None, pose=pose), received_at=now[0])
    assert not owner.readback().seating_verified


def test_readback_lifetime_cannot_exceed_measured_seating_lifetime():
    owner, _, now = seated_owner()
    now[0] += 0.15
    status = owner.readback()
    assert status.seating_verified
    assert status.valid_until <= owner._seated_until


def test_readback_uses_time_after_ack_when_real_clock_advances_between_calls():
    owner, _, now, _, target, session, _ = setup_owner()
    owner.bind(session, target, observation(boot_id=session.boot_id))

    def advancing_clock():
        now[0] += 0.0001
        return now[0]

    owner.source_clock = advancing_clock
    status = owner.readback()
    assert status.binding_valid and status.ack.captured_at <= status.captured_at


def test_seating_status_cannot_outlive_a_short_camera_validity_window():
    from test_station_seating import seating
    owner, _, now = seated_owner()
    now[0] += 0.01
    owner.ingest(observation(boot_id=owner.session.boot_id, sequence=100, captured_at=now[0],
                             valid_until=now[0]+0.02, pose=dict(x=0., y=0., yaw=0.)), received_at=now[0])
    assert owner.update_seating(seating(now[0], boot_id=owner.session.boot_id))
    status = owner.readback()
    assert status.seating_verified and status.valid_until <= now[0]+0.02


@pytest.mark.parametrize('change', [{'contact': False}, {'moving': True}, {'missing_motion': True}])
def test_latest_local_sensor_contradiction_revokes_completion_before_tick(change):
    from test_station_sensor_reader import sensor_owner
    from test_station_docking_owner import align
    owner, manager, now, signals, _ = sensor_owner()
    align(owner, manager, now)
    for sequence in range(40, 60):
        now[0] += 0.1
        frame(owner, now, sequence)
        owner.tick()
    signals['normal'] = True
    now[0] += 0.1
    frame(owner, now, 60)
    owner.tick()
    assert owner.readback().completion_verified
    signals.update(change)
    assert not owner.readback().completion_verified
    owner.close()
