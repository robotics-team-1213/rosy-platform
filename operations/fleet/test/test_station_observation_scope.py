"""A camera learns only its active observation scope, never a robot credential."""
import asyncio

import httpx
import pytest

from core_common.protocol.station_charging import StationObservation
from test_station_ingress import _setup


def status(ingress, seen, **changes):
    return dict(state='BOUND', reason=None, session_id=seen.session_id, boot_id=seen.boot_id, battery_id='pack-1',
        target=ingress.stations.installations()[0].model_dump(), ack={key: getattr(seen, key) for key in (
            'robot_id', 'station_id', 'session_id', 'boot_id', 'map_id', 'map_revision', 'pose_revision')} | dict(
            accepted=True, captured_at=101., valid_until=101.2), operation_id=None, correlation_id=None,
        binding_valid=True, seating_verified=False, charging_verified=False, completion_verified=False,
        captured_at=101., valid_until=101.2) | changes


def scoped(tmp_path, **changes):
    state = dict(robot_id='robot-1', map_id='floor', odom_pose={'epoch': 7, 'stamp': 101.})
    values = {}
    def handler(request):
        assert request.method == 'GET'
        assert request.headers['Authorization'] == 'Bearer '+values['robot_token']
        return httpx.Response(200, json=values['status'] if request.url.path.endswith('station-target') else state)
    ingress, token, robot, requests, seen, now, charges = _setup(tmp_path, handler)
    values.update(status=status(ingress, seen), robot_token=robot)
    for key, value in changes.items():
        if key == 'odom_pose':
            state[key] = value
        else:
            values['status'][key] = value
    return ingress, token, requests, now, charges, values


def test_source_scope_uses_current_core_binding_and_real_odom_epoch_without_seating_claim(tmp_path):
    ingress, token, requests, now, _, _ = scoped(tmp_path)
    assert hasattr(ingress, 'observation_scope'), 'source-only observation scope readback is missing'
    response = asyncio.run(ingress.observation_scope('Bearer '+token, 'robot-1'))
    value = StationObservation.model_validate(response['scope'], context={'now': now[0]})
    assert value.session_id == 'charge-1' and value.boot_id == 'boot-1' and value.odom_epoch == '7'
    assert value.source_id == 'camera-1' and value.source_epoch == 'camera-boot'
    assert value.pose is None and not value.visible and value.sequence == 0
    assert value.valid_until <= 101.2
    assert all(request.method == 'GET' for request in requests)


@pytest.mark.parametrize('changes', [dict(binding_valid=False),
    dict(odom_pose={'epoch': None, 'stamp': 101.}), dict(odom_pose={'epoch': True, 'stamp': 101.}),
    dict(odom_pose={'epoch': 7, 'stamp': 100.}), dict(odom_pose={'epoch': 7, 'stamp': 102.})])
def test_missing_binding_or_unknown_stale_future_odom_never_creates_scope(tmp_path, changes):
    ingress, token, _, _, _, _ = scoped(tmp_path, **changes)
    assert hasattr(ingress, 'observation_scope'), 'source-only observation scope readback is missing'
    assert asyncio.run(ingress.observation_scope('Bearer '+token, 'robot-1')) == {'scope': None}


def test_hold_after_binding_never_grants_a_camera_new_observation_scope(tmp_path):
    ingress, token, requests, _, charges, _ = scoped(tmp_path)
    assert hasattr(ingress, 'observation_scope'), 'source-only observation scope readback is missing'
    charges.transition('charge-1', expected_state='RETURN_RESERVED', next_state='HOLD',
                       attempt_id='attempt-1', now=101., reason='STOP')
    assert asyncio.run(ingress.observation_scope('Bearer '+token, 'robot-1')) == {'scope': None}
    assert not requests


def test_another_robots_ack_and_unregistered_source_target_are_rejected(tmp_path):
    ingress, token, _, _, _, values = scoped(tmp_path)
    assert hasattr(ingress, 'observation_scope'), 'source-only observation scope readback is missing'
    values['status']['ack']['robot_id'] = 'robot-2'
    assert asyncio.run(ingress.observation_scope('Bearer '+token, 'robot-1')) == {'scope': None}
    with pytest.raises(PermissionError):
        asyncio.run(ingress.observation_scope('Bearer '+token, 'robot-2'))


def test_scope_for_next_frame_does_not_inherit_previous_camera_evidence_deadline(tmp_path):
    ingress, token, _, now, _, values = scoped(tmp_path)
    # True seating status expires with the OLD frame, while the binding/ACK and
    # fresh odometry independently authorize a new metadata-only measurement scope.
    values['status']['valid_until'] = now[0]+0.01
    response = asyncio.run(ingress.observation_scope('Bearer '+token, 'robot-1'))
    scope = StationObservation.model_validate(response['scope'], context={'now': now[0]})
    assert scope.valid_until == pytest.approx(now[0]+0.2)
    assert not scope.visible and scope.pose is None


def test_returning_core_status_remains_metadata_only_camera_scope(tmp_path):
    ingress, token, _, now, _, values = scoped(tmp_path)
    ack = values['status']['ack']
    permit = {key: ack[key] for key in ('robot_id', 'station_id', 'session_id', 'boot_id',
                                       'map_id', 'map_revision', 'pose_revision')}
    permit.update(battery_id='pack-1', correlation_id='return-1', lease_id='lease-1', trip_id='plan-1',
                  expected_owner_generation=0, captured_at=101., valid_until=101.2)
    values['status'].update(state='RETURNING', return_permit=permit, return_ready=True)
    response = asyncio.run(ingress.observation_scope('Bearer '+token, 'robot-1'))
    scope = StationObservation.model_validate(response['scope'], context={'now': now[0]})
    assert not scope.visible and scope.pose is None and scope.session_id == 'charge-1'


def test_acknowledged_undocking_session_retains_only_measurement_scope(tmp_path):
    from test_charge_departure_store import charged
    ingress, token, requests, now, _, values = scoped(tmp_path)
    ledger, _, permit = charged(tmp_path)
    ledger.prepare_departure(permit, clock=lambda: now[0], admission=lambda: True)
    ledger.acknowledge_operation('charge-1', correlation_id=permit.correlation_id,
        operation_id='native-undock', now=now[0])
    values['status'].update(state='UNDOCKING', operation_id='native-undock',
        correlation_id=permit.correlation_id, departure_permit=permit.model_dump())
    result = asyncio.run(ingress.observation_scope('Bearer '+token, 'robot-1'))
    scope = StationObservation.model_validate(result['scope'], context={'now': now[0]})
    assert scope.session_id == 'charge-1' and scope.pose is None and scope.visible is False
    assert all(request.method == 'GET' for request in requests)
    ledger.transition('charge-1', expected_state='UNDOCKING', next_state='HOLD',
        attempt_id='attempt-1', now=now[0], reason='SIM_STOP')
    assert asyncio.run(ingress.observation_scope('Bearer '+token, 'robot-1')) == {'scope': None}
