"""Control evidence keeps installation, observation, and battery identities separate."""
import importlib
import importlib.util

import pytest
from pydantic import ValidationError


def contracts():
    name = 'core_common.protocol.station_charging'
    assert importlib.util.find_spec(name) is not None, 'station charging contracts are not implemented'
    return importlib.import_module(name)


def location(**changes):
    value = dict(station_id='charger-1', map_id='floor', map_revision='map-v2', pose_revision=3,
                 pose={'x': 2.0, 'y': 1.0, 'yaw': 0.0},
                 approach_pose={'x': 1.5, 'y': 1.0, 'yaw': 0.0}, approach_verified=True,
                 source_id='ceiling-1', source_epoch='camera-boot', calibration_revision='cal-v7',
                 captured_at=100.0, valid_until=105.0, uncertainty_m=0.01,
                 uncertainty_rad=0.02, status='VALID')
    return value | changes


def observation(**changes):
    return dict(robot_id='robot-1', station_id='charger-1', session_id='session-a', boot_id='boot-a',
                map_id='floor', map_revision='map-v2', pose_revision=3, odom_epoch='odom-a',
                source_id='station-camera', source_epoch='camera-a', calibration_revision='mount-v1',
                sequence=4, captured_at=100.0, valid_until=100.5, frame='base_link',
                pose={'x': 0.30, 'y': 0.01, 'yaw': 0.02}, uncertainty_m=0.005,
                uncertainty_rad=0.01, visible=True) | changes


def test_pose_revision_is_separate_from_calibration_and_session():
    wire = contracts()
    value = wire.StationPoseRecord.model_validate(location())
    seen = wire.StationObservation.model_validate(observation())
    assert value.pose_revision == seen.pose_revision == 3
    assert value.calibration_revision == 'cal-v7'
    assert seen.calibration_revision == 'mount-v1'
    assert seen.session_id == 'session-a'
    assert value.pose.x == 2.0


@pytest.mark.parametrize('field,value', [('x', True), ('y', float('nan')), ('yaw', float('inf'))])
def test_rejects_nonfinite_and_boolean_pose(field, value):
    wire = contracts()
    payload = location()
    payload['pose'][field] = value
    with pytest.raises(ValidationError):
        wire.StationPoseRecord.model_validate(payload)


@pytest.mark.parametrize('changes', [dict(pose_revision=True), dict(pose_revision=0),
                                    dict(map_revision=''), dict(valid_until=99.0),
                                    dict(uncertainty_m=-0.1), dict(station_id='charger\n1'),
                                    dict(approach_verified=False), dict(approach_pose=None)])
def test_invalid_installation_cannot_be_marked_valid(changes):
    wire = contracts()
    with pytest.raises(ValidationError):
        wire.StationPoseRecord.model_validate(location(**changes))


@pytest.mark.parametrize('changes,context', [
    (dict(captured_at=101.0, valid_until=101.5), dict(now=100.0)),
    ({}, dict(now=101.0)),
    ({}, dict(now=100.1, map_id='other')),
    ({}, dict(now=100.1, map_revision='map-v3')),
    ({}, dict(now=100.1, pose_revision=4)),
    ({}, dict(now=100.1, robot_id='robot-2')),
    ({}, dict(now=100.1, station_id='charger-2')),
    ({}, dict(now=100.1, boot_id='boot-b')),
    ({}, dict(now=100.1, session_id='session-b')),
    (dict(frame='map'), dict(now=100.1)),
])
def test_rejects_future_wrong_frame_and_nonmatching_scope(changes, context):
    wire = contracts()
    with pytest.raises(ValidationError):
        wire.StationObservation.model_validate(observation(**changes), context=context)


def test_unknown_health_is_not_full_capacity():
    wire = contracts()
    value = wire.BatteryEnergyEvidence(
        battery_id='pack-a', captured_at=100.0, valid_until=105.0, source='voltage_only',
        capacity_revision=None, soc_percent=55.0, soh_percent=None, usable_energy_wh=None,
        temperature_c=None, fault=None)
    assert value.soh_percent is None
    assert value.usable_energy_wh is None
    assert value.model_dump()['capacity_revision'] is None
    with pytest.raises(ValidationError):
        wire.BatteryEnergyEvidence.model_validate(value.model_dump() | {'soh_percent': 100.0})


def test_charger_termination_requires_session_identity_and_measured_source():
    wire = contracts()
    value = dict(station_id='charger-1', robot_id='robot-1', session_id='session-a', boot_id='boot-a',
                 battery_id='pack-a', captured_at=100.0, valid_until=101.0,
                 load_present=True, charging=False, termination='NORMAL', termination_sample_at=100.0,
                 source='charger', pack_voltage_v=8.3, pack_sample_at=100.0, faults=[])
    assert wire.ChargeCompletionEvidence.model_validate(value).termination == 'NORMAL'
    for bad in ({'session_id': ''}, {'source': 'voltage_only'}, {'pack_sample_at': 101.0}):
        with pytest.raises(ValidationError):
            wire.ChargeCompletionEvidence.model_validate(value | bad)


def test_control_contracts_reject_invented_authority():
    wire = contracts()
    with pytest.raises(ValidationError):
        wire.StationObservation.model_validate(observation() | {'authorized': True})


def test_all_plan_contracts_have_strict_shapes():
    wire = contracts()
    for name in ('StationPoseRecord', 'StationPoseAck', 'StationObservation', 'MapPoseEvidence',
                 'SeatingEvidence', 'ChargeCompletionEvidence', 'BatteryEnergyEvidence',
                 'ChargePolicyProfile', 'ChargeDecision', 'ChargeSessionStatus'):
        assert getattr(wire, name).model_config['extra'] == 'forbid'


def test_runtime_binding_and_motion_require_native_owner_fences():
    wire = contracts()
    assert hasattr(wire, 'StationTargetBinding'), 'runtime station binding contract is missing'
    assert hasattr(wire, 'StationMotionCommand'), 'runtime station motion contract is missing'
    command = dict(session_id='charge-1', correlation_id='intent-1', expected_boot_id='boot-1',
                   expected_owner_generation=0)
    assert wire.StationMotionCommand.model_validate(command).correlation_id == 'intent-1'
    for bad in ({'expected_owner_generation': True}, {'expected_owner_generation': -1},
                {'expected_boot_id': ''}, {'correlation_id': ''}, {'safety_override': True}):
        with pytest.raises(ValidationError):
            wire.StationMotionCommand.model_validate(command | bad)


def test_runtime_status_cannot_claim_completion_without_binding_and_seating():
    wire = contracts()
    assert hasattr(wire, 'StationTargetStatus'), 'station owner readback contract is missing'
    status = dict(state='UNBOUND', reason=None, session_id=None, boot_id=None, battery_id=None,
                  target=None, ack=None, operation_id=None, correlation_id=None,
                  binding_valid=False, seating_verified=False, charging_verified=False,
                  completion_verified=False, captured_at=100.0, valid_until=101.0)
    assert wire.StationTargetStatus.model_validate(status).state == 'UNBOUND'
    for changes in ({'completion_verified': True}, {'seating_verified': True}, {'binding_valid': True},
                    {'charging_verified': True}, {'authorized': True}):
        with pytest.raises(ValidationError):
            wire.StationTargetStatus.model_validate(status | changes)


def test_station_return_permit_requires_session_scope_lease_and_native_fence():
    wire = contracts()
    assert hasattr(wire, 'StationReturnPermit'), 'scoped return permit contract is missing'
    body = dict(robot_id='robot-1', station_id='charger-1', battery_id='pack-1', session_id='charge-1',
        boot_id='boot-1', map_id='floor', map_revision='map-1', pose_revision=1,
        correlation_id='return-1', lease_id='lease-1', trip_id='plan-1', expected_owner_generation=0,
        captured_at=100., valid_until=102.)
    assert wire.StationReturnPermit.model_validate(body, context={'now': 100.1}).trip_id == 'plan-1'
    for change in (dict(expected_owner_generation=True), dict(lease_id=''), dict(session_id=''),
                   dict(valid_until=100.), dict(motion_override=True)):
        with pytest.raises(ValidationError):
            wire.StationReturnPermit.model_validate(body | change)
    with pytest.raises(ValidationError):
        wire.StationReturnPermit.model_validate(body, context={'now': 100.1, 'session_id': 'other'})
