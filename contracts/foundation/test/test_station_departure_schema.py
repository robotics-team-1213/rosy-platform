"""A departure permit is distinct from proof of completed, stopped departure."""
import importlib

import pytest
from pydantic import ValidationError


def scope():
    return dict(robot_id='robot-1', station_id='charger-1', session_id='charge-1', attempt_id='attempt-1',
        boot_id='boot-1', battery_id='pack-1', map_id='floor', map_revision='map-1', pose_revision=1,
        correlation_id='undock-1', work_task_id='task-1', work_request_digest='a'*64)


def permit():
    wire = importlib.import_module('core_common.protocol.station_charging')
    assert hasattr(wire, 'StationDeparturePermit'), 'scoped departure permit is missing'
    return wire.StationDeparturePermit, scope() | dict(captured_at=100., valid_until=101.,
        expected_owner_generation=1, policy_profile_revision='policy-1', capacity_revision='capacity-1')


def test_permit_exports_and_checks_original_scope_and_time():
    cls, body = permit()
    from core_common.protocol import schemas
    assert schemas.StationDeparturePermit is cls
    assert cls.model_validate(body, context={'now': 100.1, 'session_id': 'charge-1'}).work_task_id == 'task-1'
    for context in ({'now': 101.}, {'now': 99.}, {'boot_id': 'other'}, {'pose_revision': 2}):
        with pytest.raises(ValidationError):
            cls.model_validate(body, context=context)


@pytest.mark.parametrize('change', [dict(expected_owner_generation=True), dict(work_request_digest='guess'),
    dict(captured_at=float('nan')), dict(capacity_revision=''), dict(attempt_id='')])
def test_permit_rejects_untyped_or_unbound_work(change):
    cls, body = permit()
    with pytest.raises(ValidationError):
        cls.model_validate(body | change)


def test_receipt_requires_exact_terminal_owner_and_original_measurements():
    wire = importlib.import_module('core_common.protocol.station_charging')
    assert hasattr(wire, 'StationDepartureReceipt'), 'measured departure receipt is missing'
    from core_common.protocol import schemas
    assert schemas.StationDepartureReceipt is wire.StationDepartureReceipt
    body = scope() | dict(operation_id='native-undock', owner_generation=2, odom_epoch='odom-1',
        departure_profile_revision='departure-1', source_id='local-departure', source_epoch='source-boot',
        captured_at=101., valid_until=101.2, stopped_since=100.5, motion_sample_at=101.,
        contact_sample_at=101., space_sample_at=101., isolation_sample_at=101.,
        contact_released=True, power_isolated=True, route_clear=True, stopped=True)
    assert wire.StationDepartureReceipt.model_validate(body).operation_id == 'native-undock'
    for change in (dict(contact_released=False), dict(stopped=False), dict(power_isolated=False),
                   dict(route_clear=False), dict(motion_sample_at=102.), dict(stopped_since=101.1)):
        with pytest.raises(ValidationError):
            wire.StationDepartureReceipt.model_validate(body | change)
