"""The station owner composes the actual parking manager, not a second motor writer."""
import importlib
import importlib.util
from types import SimpleNamespace

import pytest

from core_common.protocol.native.receipts import BOOT_ID
from core_common.protocol.station_charging import ChargeSessionStatus, StationPoseRecord
from core_features.docking.database import DockDatabase, DockInstance, DockType
from core_features.docking.manager import DockingManager
from test_docking_parking_manager import World
from test_station_feed import observation
from test_station_seating import seating


def setup_owner():
    name = 'core_features.docking.station_owner'
    assert importlib.util.find_spec(name) is not None, 'local station lifecycle owner is missing'
    module = importlib.import_module(name)
    now = [100.1]  # The initial permission fixture was captured at 100.1.
    local = dict(robot_id='robot-1', boot_id=str(BOOT_ID), battery_id='pack-1',
                 map_id='floor', map_revision='map-1', odom_epoch='odom-1', mode='IDLE',
                 safety_latched=False, odom_fresh=True)
    db = DockDatabase.empty()
    db.add_type(DockType(name='station-sim', detector='station_observation', staging=False,
                         approach='pose', settle='pose', tag_offset_m=0.15, pose_tolerance_rad=0.05))
    db.add(DockInstance(id='charger-1', type='station-sim', map_id='floor'))
    world = World((0., 0., 0.))
    manager = DockingManager(database=db, safety=SimpleNamespace(estop=False), clock=lambda: now[0],
                             map_id_provider=lambda: 'floor', capability_provider=lambda: True,
                             detector_factory=lambda *_: owner.detector(),
                             pose_provider=lambda: owner.map_pose())
    manager.executor = world
    battery = SimpleNamespace(set_charging=lambda value: None)
    profile = module.StationControlProfile(
        battery_id='pack-1', station_id='charger-1', source_id='station-camera',
        source_epoch='camera-boot', calibration_revision='mount-1', marker_offset_m=0.15,
        max_age_s=0.25, max_uncertainty_m=0.01, max_uncertainty_rad=0.02,
        position_tolerance_m=0.012, heading_tolerance_rad=0.05,
        linear_limit_m_s=0.003, angular_limit_rad_s=0.01, still_s=0.4, debounce_s=0.3,
        sample_max_age_s=0.25, min_full_voltage_v=8.1, max_voltage_v=8.5,
        pack_max_age_s=0.25, charge_confirm_s=0.3)
    owner = module.StationDockingOwner(manager, profile=profile, local_scope=lambda: dict(local),
                                      local_scope_nowait=lambda: dict(local),
                                      clock=lambda: now[0], source_clock=lambda: now[0], battery=battery)
    manager.motion_admission = owner.admit_motion
    target = StationPoseRecord(
        station_id='charger-1', map_id='floor', map_revision='map-1', pose_revision=1,
        pose={'x': 0., 'y': 0., 'yaw': 0.}, approach_pose={'x': -0.4, 'y': 0., 'yaw': 0.},
        approach_verified=True, source_id='global-camera', source_epoch='global-boot',
        calibration_revision='global-cal', uncertainty_m=0.002, uncertainty_rad=0.005,
        status='VALID', captured_at=100., valid_until=110.)
    session = ChargeSessionStatus(session_id='charge-1', robot_id='robot-1', station_id='charger-1',
                                  battery_id='pack-1', boot_id=str(BOOT_ID), pose_revision=1,
                                  map_id='floor', map_revision='map-1', state='RETURN_RESERVED',
                                  attempt_id='attempt-1', reason='SIM', updated_at=100.)
    return owner, manager, now, local, target, session, world


def frame(owner, now, sequence=1, **changes):
    return owner.ingest(observation(boot_id=str(BOOT_ID), sequence=sequence,
                                    captured_at=now[0], valid_until=now[0]+0.2,
                                    pose={'x': 0., 'y': 0., 'yaw': 0.}, **changes), received_at=now[0])


def align(owner, manager, now):
    frame(owner, now)
    owner.start_docking(correlation_id='dock-1')
    for sequence in range(2, 30):
        now[0] += 0.05
        frame(owner, now, sequence)
        owner.tick()
        if owner.state == 'SEATING':
            return
    pytest.fail('actual parking controller never completed alignment')


def test_binding_ack_does_not_start_motion_and_wrong_map_is_rejected():
    owner, manager, now, local, target, session, world = setup_owner()
    local['map_revision'] = 'different'
    with pytest.raises(ValueError, match='SCOPE'):
        owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    local['map_revision'] = 'map-1'
    ack = owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    assert ack.accepted and ack.pose_revision == 1
    assert manager.native.current is None and world.command == (0., 0.)
    with pytest.raises(ValueError, match='OBSERVATION'):
        owner.start_docking(correlation_id='dock-1')
    assert manager.native.current is None


def test_lost_observation_and_target_expiry_close_motion_without_automatic_resume():
    owner, manager, now, local, target, session, world = setup_owner()
    owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    frame(owner, now)
    owner.start_docking(correlation_id='dock-1')
    now[0] += 0.05
    frame(owner, now, 2)
    assert owner.motion_ready('DOCKING')
    now[0] += 0.3
    assert not owner.motion_ready('DOCKING')
    owner.tick()
    assert owner.state == 'HOLD' and not manager.active
    frame(owner, now, 3)
    assert not owner.motion_ready('DOCKING')


def test_alignment_success_does_not_replace_measured_stop_and_contact():
    owner, manager, now, _, target, session, _ = setup_owner()
    owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    align(owner, manager, now)
    assert owner.state == 'SEATING'
    assert not owner.motion_ready('NAVIGATION')
    for index in range(4):
        now[0] += 0.15
        frame(owner, now, 40+index)
        evidence = seating(now[0], boot_id=str(BOOT_ID), measured_linear_m_s=0.02)
        assert not owner.update_seating(evidence)
    assert owner.state == 'SEATING'
    for index in range(5):
        now[0] += 0.15
        frame(owner, now, 50+index)
        owner.update_seating(seating(now[0], boot_id=str(BOOT_ID)))
    assert owner.state == 'CHARGE_CONFIRMING'


def test_revision_cannot_silently_retarget_active_session():
    owner, manager, now, _, target, session, world = setup_owner()
    owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    frame(owner, now)
    owner.start_docking(correlation_id='dock-1')
    moved = target.model_copy(update={'pose_revision': 2, 'pose': target.pose.model_copy(update={'x': 1.})})
    with pytest.raises(ValueError, match='RECONCILIATION'):
        owner.bind(session.model_copy(update={'pose_revision': 2}), moved,
                   observation(boot_id=str(BOOT_ID), pose_revision=2))
    assert owner.state == 'HOLD'
    assert world.command == (0., 0.)


def seated_owner():
    owner, manager, now, local, target, session, world = setup_owner()
    owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    align(owner, manager, now)
    for index in range(5):
        now[0] += 0.15
        frame(owner, now, 50+index)
        owner.update_seating(seating(now[0], boot_id=str(BOOT_ID)))
    return owner, manager, now


def charge_evidence(now, **changes):
    from core_common.protocol.station_charging import ChargeCompletionEvidence
    return ChargeCompletionEvidence.model_validate(dict(
        station_id='charger-1', robot_id='robot-1', session_id='charge-1', boot_id=str(BOOT_ID),
        battery_id='pack-1', captured_at=now, valid_until=now+0.2,
        load_present=True, charging=True, termination='CHARGING', source='charger',
        pack_voltage_v=8.25, pack_sample_at=now, termination_sample_at=now) | changes)


def test_normal_termination_survives_current_window_reset_and_real_manager_tick():
    from core_features.docking.agent import DockStatus, DockReachability
    owner, manager, now = seated_owner()
    for index in range(5):
        now[0] += 0.1
        frame(owner, now, 60+index)
        owner.update_seating(seating(now[0], boot_id=str(BOOT_ID)))
        owner.update_charge(DockStatus(DockReachability.OK, load_present=True, charging=True),
                            charge_evidence(now[0]), received_at=now[0])
    assert owner.state == 'CHARGING'
    now[0] += 0.1
    frame(owner, now, 70)
    owner.update_seating(seating(now[0], boot_id=str(BOOT_ID)))
    assert owner.update_charge(DockStatus(DockReachability.OK, load_present=True, charging=False,
                                          termination='NORMAL', termination_source='charger',
                                          termination_sample_at=now[0], battery_id='pack-1'),
                               charge_evidence(now[0], termination='NORMAL', charging=False), received_at=now[0])
    owner.tick()
    assert owner.state == 'CHARGED_HOLD'
    assert not owner.charging.confirmed  # Deliberately independent from completion.
    assert not owner.motion_ready('NAVIGATION')


@pytest.mark.parametrize('fault', ['unknown', 'lost_contact', 'stale_pack', 'old_session'])
def test_unverified_completion_never_opens_automatic_departure(fault):
    from core_features.docking.agent import DockStatus, DockReachability
    owner, _, now = seated_owner()
    changes = dict(charging=False, termination='UNKNOWN')
    status = DockStatus(DockReachability.OK, load_present=True, charging=False)
    if fault == 'lost_contact':
        status = DockStatus(DockReachability.OK, load_present=False, charging=False)
        changes['load_present'] = False
    elif fault == 'stale_pack':
        changes.update(termination='NORMAL', pack_sample_at=now[0]-1.)
    elif fault == 'old_session':
        changes.update(termination='NORMAL', session_id='previous')
    assert not owner.update_charge(status, charge_evidence(now[0], **changes), received_at=now[0])
    assert owner.state != 'CHARGED_HOLD'
    assert not owner.motion_ready('NAVIGATION')


def test_legacy_station_dock_request_is_rejected_before_receipt_or_entry_turn():
    owner, manager, now, _, target, session, world = setup_owner()
    from core_features.docking.database import DockError
    with pytest.raises(DockError) as rejected:
        manager.dock('charger-1', correlation_id='unbound')
    assert rejected.value.code == 'STATION_BINDING_REQUIRED'
    owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    frame(owner, now)
    with pytest.raises(DockError) as rejected:
        manager.dock('charger-1', correlation_id='unowned')
    assert rejected.value.code == 'STATION_BINDING_REQUIRED'
    assert manager.native.current is None and world.command == (0., 0.)


def test_failure_after_native_admission_keeps_receipt_and_holds_instead_of_retry():
    owner, manager, now, _, target, session, _ = setup_owner()
    owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    frame(owner, now)

    def broken_pose():
        raise RuntimeError('pose read failed after admission')

    owner.map_pose = broken_pose
    with pytest.raises(RuntimeError):
        owner.start_docking(correlation_id='dock-1')
    assert owner.state == 'HOLD'
    assert manager.native.current.correlation_id == 'dock-1'
    assert manager.native.current.phase == 'TERMINAL'


def test_publisher_guard_does_not_wait_for_feed_lock():
    import threading
    owner, _, now, _, target, session, _ = setup_owner()
    owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    frame(owner, now)
    owner.start_docking(correlation_id='dock-1')
    now[0] += 0.05
    frame(owner, now, 2)
    locked, release, finished = threading.Event(), threading.Event(), threading.Event()
    result = []

    def hold_feed():
        with owner.feed._lock:
            locked.set()
            release.wait(2.)

    def publish_guard():
        result.append(owner.motion_ready('DOCKING'))
        finished.set()

    thread = threading.Thread(target=hold_feed)
    thread.start()
    assert locked.wait(1.)
    guard = threading.Thread(target=publish_guard)
    guard.start()
    try:
        returned_without_waiting = finished.wait(0.1)
    finally:
        release.set()
        guard.join(1.)
        thread.join(1.)
    assert returned_without_waiting and result == [False]


def test_station_admission_is_consumed_even_before_start_returns():
    module = importlib.import_module('core_features.docking.station_owner')
    owner = object.__new__(module.StationDockingOwner)
    owner.session = SimpleNamespace(session_id='charge-1', attempt_id='attempt-1')
    owner._valid = lambda: None
    owner._starting = ('dock', 'charger-1', 'exact-correlation', 'charge-1', 'attempt-1')
    dock, kind = SimpleNamespace(id='charger-1'), SimpleNamespace(detector='station_observation')
    assert hasattr(owner, 'admit_motion'), 'station admission seam is missing'
    owner.admit_motion('dock', dock, kind, 'exact-correlation')
    from core_features.docking.database import DockError
    with pytest.raises(DockError) as rejected:
        owner.admit_motion('dock', dock, kind, 'exact-correlation')
    assert rejected.value.code == 'STATION_BINDING_REQUIRED'


def test_caller_cannot_claim_normal_completion_when_dock_source_is_unknown():
    from core_features.docking.agent import DockStatus, DockReachability
    owner, _, now = seated_owner()
    unknown = DockStatus(DockReachability.OK, load_present=True, charging=False)
    assert not owner.update_charge(unknown, charge_evidence(now[0], termination='NORMAL', charging=False),
                                    received_at=now[0])
    assert owner.state != 'CHARGED_HOLD'


@pytest.mark.parametrize('change', ['odom_epoch', 'map_revision', 'expired_target'])
def test_scope_or_target_change_closes_output_even_with_a_new_camera_frame(change):
    owner, manager, now, local, target, session, _ = setup_owner()
    owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    frame(owner, now)
    owner.start_docking(correlation_id='dock-1')
    now[0] += 0.05
    frame(owner, now, 2)
    assert owner.motion_ready('DOCKING')
    if change == 'expired_target':
        now[0] = target.valid_until+0.1
    else:
        local[change] = 'changed'
    frame(owner, now, 3)
    assert not owner.motion_ready('DOCKING')
    owner.tick()
    assert owner.state == 'HOLD' and not manager.active
