"""Restart reconciliation reads existing owners and never repeats a movement request."""
import asyncio
import importlib
import importlib.util

import pytest

from core_common.protocol.station_charging import ChargeDecision, StationPoseAck
from test_charge_store import store
from test_station_pose_service import service as station_service, stable


class Ports:
    def __init__(self):
        self.calls = []
        self.result = 'RUNNING'
        self.boot = 'boot-1'
        self.boundary = True

    async def snapshot(self, robot_id):
        return {'robot_id': robot_id, 'boot_id': self.boot, 'battery_id': 'pack-1',
                'captured_at': 101.0, 'valid_until': 102.0, 'mode': 'IDLE',
                'safe_work_boundary': self.boundary, 'safety_latched': False, 'dock_state': 'UNDOCKED',
                'map_id': 'floor', 'map_revision': 'map-1'}

    async def bind_target(self, session, target):
        self.calls.append(('bind', session.session_id))
        return StationPoseAck(station_id=target.station_id, robot_id=session.robot_id,
                              boot_id=session.boot_id, session_id=session.session_id,
                              map_id=target.map_id, map_revision=target.map_revision,
                              pose_revision=target.pose_revision, accepted=True,
                              captured_at=101.0, valid_until=102.0)

    async def read_operation(self, session):
        return {'operation_id': session.operation_id, 'boot_id': self.boot, 'state': self.result}


def controller(tmp_path, **options):
    name = 'fleet.server.charge_service'
    assert importlib.util.find_spec(name) is not None, 'charge lifecycle coordinator is not implemented'
    ledger, tasks = store(tmp_path)
    stations, _, scopes = station_service(tmp_path)
    scopes['robot-1'] = ('boot-1', 'charge-1')
    stable(stations)
    ports = Ports()
    kwargs = dict(stations=stations, ports=ports, clock=lambda: 101.0, policy_enabled=lambda: True,
                  admit_return=lambda snapshot, target: ChargeDecision(
                      decision='RETURN_REQUIRED', reason='LOW_SOC_RETURN',
                      profile_revision='sim-profile', capacity_revision='capacity-1'),
                  id_factory=lambda: 'charge-1')
    return importlib.import_module(name).ChargeService(ledger, **(kwargs | options)), ledger, tasks, ports


def test_duplicate_request_binds_once_and_keeps_same_durable_session(tmp_path):
    value, _, _, ports = controller(tmp_path)

    async def scenario():
        first = await value.request_return('robot-1', 'charger-1', pose_revision=1, reason='BATTERY_SCHEDULE')
        again = await value.request_return('robot-1', 'charger-1', pose_revision=1, reason='BATTERY_SCHEDULE')
        assert first.session_id == again.session_id == 'charge-1'
        assert first.state == 'RETURN_RESERVED'
        assert ports.calls == [('bind', 'charge-1')]

    asyncio.run(scenario())


def test_unverified_target_disabled_policy_and_active_work_do_not_request_motion(tmp_path):
    value, _, _, ports = controller(tmp_path)
    with pytest.raises(ValueError, match='STATION_POSITION'):
        asyncio.run(value.request_return('robot-1', 'charger-1', pose_revision=2, reason='SCHEDULE'))
    ports.boundary = False
    with pytest.raises(ValueError, match='WORK_BOUNDARY'):
        asyncio.run(value.request_return('robot-1', 'charger-1', pose_revision=1, reason='SCHEDULE'))
    assert ports.calls == []


def test_restart_reconciliation_never_reissues_existing_operation(tmp_path):
    value, ledger, _, ports = controller(tmp_path)
    asyncio.run(value.request_return('robot-1', 'charger-1', pose_revision=1, reason='SCHEDULE'))
    ledger.transition('charge-1', expected_state='RETURN_RESERVED', next_state='RETURNING',
                      attempt_id='charge-1', now=101.0, operation_id='operation-1', reason='RETURN_STARTED')
    ports.calls.clear()
    result = asyncio.run(value.reconcile('charge-1'))
    assert result.state == 'RETURNING'
    assert ports.calls == []
    ports.result = 'UNKNOWN'
    result = asyncio.run(value.reconcile('charge-1'))
    assert result.state == 'HOLD'
    assert result.operation_id == 'operation-1'
    assert ports.calls == []


def test_changed_boot_or_battery_requires_hold(tmp_path):
    value, ledger, _, ports = controller(tmp_path)
    asyncio.run(value.request_return('robot-1', 'charger-1', pose_revision=1, reason='SCHEDULE'))
    ports.boot = 'restarted'
    result = asyncio.run(value.reconcile('charge-1'))
    assert result.state == 'HOLD'
    assert ledger.admitted('charge-1')
