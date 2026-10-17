"""Only calibrated, stable observations and current robot acknowledgements enable return."""
import importlib
import importlib.util

import pytest

from core_common.protocol.station_charging import StationPoseAck
from test_station_store import candidate, registry


def service(tmp_path, **options):
    name = 'fleet.server.station_service'
    assert importlib.util.find_spec(name) is not None, 'station service is not implemented'
    now = [101.0]
    scopes = {'robot-1': ('boot-1', 'session-1')}
    kwargs = dict(clock=lambda: now[0], map_scope=lambda: ('floor', 'map-1'),
                  trusted_sources={'camera-1': ('camera-boot', 'cal-1')},
                  robot_scope=lambda robot: scopes.get(robot), approach_validator=lambda record: True,
                  position_tolerance_m=0.03, heading_tolerance_rad=0.05,
                  max_uncertainty_m=0.02, max_uncertainty_rad=0.03, consistency_samples=3)
    return (importlib.import_module(name).StationService(registry(tmp_path / 'site.sqlite'), **(kwargs | options)),
            now, scopes)


def stable(svc, **changes):
    result = None
    for stamp in (100.0, 100.2, 100.4):
        result = svc.observe(candidate(captured_at=stamp, **changes))
    return result


def ack(**changes):
    return StationPoseAck.model_validate(dict(
        station_id='charger-1', robot_id='robot-1', boot_id='boot-1', session_id='session-1',
        map_id='floor', map_revision='map-1', pose_revision=1, accepted=True,
        captured_at=100.5, valid_until=105.0) | changes)


def test_requires_distinct_stable_observations_and_robot_ack(tmp_path):
    svc, _, _ = service(tmp_path)
    for _ in range(4):
        assert svc.observe(candidate()) is None
    assert svc.ready_for_return('robot-1', 'charger-1') is None
    assert svc.observe(candidate(captured_at=100.2)) is None
    assert svc.observe(candidate(captured_at=100.4)).status == 'VALID'
    assert svc.ready_for_return('robot-1', 'charger-1') is None
    assert svc.accept_ack(ack())
    assert svc.ready_for_return('robot-1', 'charger-1').pose_revision == 1


@pytest.mark.parametrize('changes', [dict(source_id='unknown'), dict(calibration_revision='old'),
                                    dict(source_epoch='restarted'), dict(map_revision='other'),
                                    dict(uncertainty_m=0.5), dict(captured_at=102.0)])
def test_untrusted_uncalibrated_or_uncertain_observation_cannot_confirm(tmp_path, changes):
    svc, _, _ = service(tmp_path)
    with pytest.raises(ValueError):
        svc.observe(candidate(**changes))
    assert svc.store.list() == []


def test_approach_verification_cannot_be_asserted_by_camera_payload(tmp_path):
    svc, _, _ = service(tmp_path, approach_validator=lambda record: False)
    assert stable(svc) is None
    assert svc.store.list() == []


def test_service_records_approach_verification_from_its_own_validator(tmp_path):
    svc, _, _ = service(tmp_path)
    result = stable(svc, approach_verified=False)
    assert result.status == 'VALID'
    assert result.approach_verified


@pytest.mark.parametrize('changes', [dict(boot_id='old'), dict(session_id='old'),
                                    dict(pose_revision=2), dict(accepted=False),
                                    dict(map_revision='old'), dict(captured_at=102.0),
                                    dict(valid_until=100.8)])
def test_ack_is_scoped_to_current_installation_and_robot_session(tmp_path, changes):
    svc, _, _ = service(tmp_path)
    stable(svc)
    assert not svc.accept_ack(ack(**changes))
    assert svc.ready_for_return('robot-1', 'charger-1') is None


def test_movement_revokes_old_ack_before_new_location_is_confirmed(tmp_path):
    svc, _, _ = service(tmp_path)
    stable(svc)
    svc.accept_ack(ack())
    moved = dict(pose={'x': 4.0, 'y': 1.0, 'yaw': 0.0},
                 approach_pose={'x': 3.5, 'y': 1.0, 'yaw': 0.0})
    assert svc.observe(candidate(captured_at=100.6, **moved)) is None
    assert svc.store.get('charger-1').status == 'INVALID'
    assert svc.ready_for_return('robot-1', 'charger-1') is None
    svc.observe(candidate(captured_at=100.7, **moved))
    assert svc.observe(candidate(captured_at=100.8, **moved)).pose_revision == 2
    assert not svc.accept_ack(ack())
    assert svc.accept_ack(ack(pose_revision=2, captured_at=100.9))


def test_stable_refresh_preserves_target_pose_and_version(tmp_path):
    svc, now, _ = service(tmp_path)
    first = stable(svc)
    svc.accept_ack(ack())
    now[0] = 104.0
    refreshed = svc.observe(candidate(captured_at=103.8, valid_until=113.8,
                                     pose={'x': 2.001, 'y': 1.0, 'yaw': 0.0}))
    assert refreshed.pose == first.pose
    assert refreshed.pose_revision == first.pose_revision
    assert refreshed.valid_until == 113.8
    assert svc.ready_for_return('robot-1', 'charger-1') is not None


def test_expiry_boot_change_and_restart_require_reconciliation(tmp_path):
    svc, now, scopes = service(tmp_path)
    stable(svc)
    svc.accept_ack(ack())
    scopes['robot-1'] = ('boot-2', 'session-1')
    assert svc.ready_for_return('robot-1', 'charger-1') is None
    scopes['robot-1'] = ('boot-1', 'session-1')
    now[0] = 106.0
    assert svc.ready_for_return('robot-1', 'charger-1') is None
    fresh, _, _ = service(tmp_path)
    assert fresh.store.get('charger-1').status == 'VALID'
    assert fresh.ready_for_return('robot-1', 'charger-1') is None
