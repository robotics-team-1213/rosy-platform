"""ChargeService ports composed from the existing trip owner and robot HTTP client.

Snapshot and observation scope must come from installed, source-aged adapters. A missing
adapter fails closed; HTTP receipt time never manufactures battery/odom readiness.
"""
import asyncio

from fleet.server.charge_departure_http import ChargeDepartureHttp

from core_common.protocol.native_operation import NativeOperation
from core_common.protocol.station_charging import (
    StationMotionCommand, StationTargetBinding, StationTargetStatus, StationPoseRecord, StationObservation,
)

_SCOPE = ('session_id', 'robot_id', 'station_id', 'battery_id', 'boot_id', 'map_id',
          'map_revision', 'pose_revision', 'attempt_id')


class ChargeRobotHttp:
    def __init__(self, *, clients, store, stations, clock, returns, return_http, snapshot, observation_scope):
        self.clients, self.store, self.stations, self.clock = clients, store, stations, clock
        self.returns, self.return_http = returns, return_http
        self.snapshot_source, self.observation_scope = snapshot, observation_scope
        self.departure = ChargeDepartureHttp(self)
        self.work_handover = None

    async def finish_work(self, robot_id, *, expected_boot_id, admission):
        if self.work_handover is None:
            return False
        client = self.clients().get(robot_id)
        if client is None or client.robot_id != robot_id:
            return False
        return await self.work_handover(robot_id, client=client, admission=admission,
                                        expected_boot_id=expected_boot_id)

    async def departure_permission(self, session, target, **kwargs):
        return await self.departure.permission(session, target, **kwargs)

    async def start_undock(self, session, target, permission, **kwargs):
        return await self.departure.start(session, target, permission, **kwargs)

    async def advance_departure(self, session, context, **kwargs):
        return await self.departure.advance(session, context, **kwargs)

    def _client(self, session):
        client = self.clients().get(session.robot_id)
        if client is None or client.robot_id != session.robot_id:
            raise ValueError('CHARGE_ROBOT_UNAVAILABLE')
        return client

    async def snapshot(self, robot_id):
        if self.snapshot_source is None:
            raise ValueError('CHARGE_SOURCE_ADAPTER_REQUIRED')
        return await self.snapshot_source(robot_id)

    async def _admitted(self, session, states):
        current = await asyncio.to_thread(self.store.admitted_session, session.session_id, states=states)
        if current is None or any(getattr(current, key) != getattr(session, key) for key in _SCOPE):
            raise ValueError('CHARGE_SCOPE_CHANGED')
        return current

    def _owner(self, body, session, *, vacant=False):
        owner = body.get('owner') or {}
        generation = owner.get('owner_generation')
        if (owner.get('boot_id') != session.boot_id or type(generation) is not int or generation < 0
                or 'owner_run_id' not in owner or vacant and owner['owner_run_id'] is not None):
            raise ValueError('CHARGE_NATIVE_OWNER_CHANGED')
        return generation

    async def bind_target(self, session, target):
        if self.observation_scope is None:
            raise ValueError('CHARGE_SOURCE_ADAPTER_REQUIRED')
        client = self._client(session)
        scope = await self.observation_scope(session, target)
        body = await client.docking_status()
        generation = self._owner(body, session, vacant=True)
        await self._admitted(session, {'RETURN_RESERVED'})
        scope = StationObservation.model_validate(scope.model_dump(), context={'now': self.clock()})
        StationPoseRecord.model_validate(target.model_dump(), context={'now': self.clock()})
        binding = StationTargetBinding(session=session, target=target, observation_scope=scope,
            expected_boot_id=session.boot_id, expected_owner_generation=generation)
        return await client.station_bind(binding)

    async def read_target(self, session):
        return (await self.read_station(session)).ack

    async def start_return(self, session, target, *, correlation_id):
        return await self.returns.start_return(session, target, correlation_id=correlation_id)

    async def start_dock(self, session, target, *, correlation_id):
        client = self._client(session)
        live = await self.read_station(session)
        refreshed = {'captured_at', 'valid_until', 'uncertainty_m', 'uncertainty_rad'}
        if (live.state != 'BOUND' or live.return_ready
                or live.target.model_dump(exclude=refreshed) != target.model_dump(exclude=refreshed)):
            raise ValueError('CHARGE_DOCK_BOUNDARY_REQUIRED')
        body = await client.docking_status()
        generation = self._owner(body, session, vacant=True)
        await self._admitted(session, {'DOCKING'})
        intent = await asyncio.to_thread(self.store.operation_intent, session.session_id)
        if (intent is None or intent['kind'] != 'dock' or intent['status'] != 'PREPARED'
                or intent['correlation_id'] != correlation_id or intent['operation_id'] is not None):
            raise ValueError('CHARGE_DOCK_INTENT_CHANGED')
        # Recheck source age after database/native I/O, before the sole submission.
        StationTargetStatus.model_validate(live.model_dump(), context={'now': self.clock()})
        StationPoseRecord.model_validate(target.model_dump(), context={'now': self.clock()})
        operation = await client.station_dock(StationMotionCommand(session_id=session.session_id,
            correlation_id=correlation_id, expected_boot_id=session.boot_id, expected_owner_generation=generation))
        if (str(operation.boot_id) != session.boot_id or operation.correlation_id != correlation_id
                or operation.kind != 'dock'):
            raise ValueError('CHARGE_DOCK_SUBMISSION_UNKNOWN')
        return str(operation.run_id)

    async def read_station(self, session):
        client = self._client(session)
        states = {'RETURN_RESERVED', 'RETURNING', 'DOCKING', 'CHARGE_CONFIRMING', 'CHARGING', 'CHARGED_HOLD', 'UNDOCKING'}
        await self._admitted(session, states)
        target = await self._target(session)
        body = await client.station_target()
        live = self.return_http._live(session, target, body, boundary=False)
        if target == live.target:
            return live
        if target.captured_at <= live.target.captured_at:
            raise ValueError('STATION_TARGET_REFRESH_REPLAY')
        if self.observation_scope is None:
            raise ValueError('CHARGE_SOURCE_ADAPTER_REQUIRED')
        scope = await self.observation_scope(session, target)
        for attempt in (1, 2):
            generation = self._owner(await client.docking_status(), session)
            await self._admitted(session, states)
            latest = await self._target(session)
            immutable = {'captured_at', 'valid_until', 'uncertainty_m', 'uncertainty_rad'}
            if latest.model_dump(exclude=immutable) != target.model_dump(exclude=immutable):
                raise ValueError('CHARGE_RETURN_TARGET_CHANGED')
            # Both original leases must still be live after source/native/database I/O.
            StationPoseRecord.model_validate(target.model_dump(), context={'now': self.clock()})
            StationTargetStatus.model_validate(live.model_dump(), context={'now': self.clock()})
            scope = StationObservation.model_validate(scope.model_dump(), context={'now': self.clock()})
            try:
                await client.station_bind(StationTargetBinding(session=session, target=target,
                    observation_scope=scope, expected_boot_id=session.boot_id, expected_owner_generation=generation))
                break
            except Exception as exc:
                # A native run may advance the owner generation between the read above and CORE's compare-and-set
                # (an undock phase under load: CHARGE_DEPARTURE_UNVERIFIED stops, 2026-10-30). Re-read it once and
                # repeat every check; a stale generation is never sent and a second refusal still propagates.
                if (attempt == 2 or getattr(exc, 'status', None) != 409
                        or getattr(exc, 'code', None) != 'OWNER_GENERATION_CHANGED'):
                    raise
        await self._admitted(session, states)
        body = await client.station_target()
        StationPoseRecord.model_validate(target.model_dump(), context={'now': self.clock()})
        return self.return_http._live(session, target, body, boundary=False)

    async def _target(self, session):
        target = await asyncio.to_thread(self.stations.store.get, session.station_id)
        if target is None or target.status != 'VALID':
            raise ValueError('CHARGE_RETURN_TARGET_CHANGED')
        return StationPoseRecord.model_validate(target.model_dump(), context={'now': self.clock(),
            **{key: getattr(session, key) for key in ('station_id', 'map_id', 'map_revision', 'pose_revision')}})

    async def read_operation(self, session):
        intent = await asyncio.to_thread(self.store.operation_intent, session.session_id)
        if intent is None or intent['operation_id'] != session.operation_id or session.operation_id is None:
            raise ValueError('CHARGE_OPERATION_UNKNOWN')
        # ACK reads elsewhere may stay fresh while CORE still holds the older pose lease.
        await self.read_station(session)
        if intent['kind'] == 'return':
            return await self.returns.read_return(session)
        if intent['kind'] not in ('dock', 'undock'):
            raise ValueError('CHARGE_OPERATION_KIND_UNKNOWN')
        body = await self._client(session).docking_status(session.operation_id)
        self._owner(body, session)
        operation = NativeOperation.model_validate(body['operation'])
        if (body.get('lookup') != 'FOUND' or str(operation.run_id) != session.operation_id
                or str(operation.boot_id) != session.boot_id or operation.kind != intent['kind']
                or operation.correlation_id != intent['correlation_id']):
            raise ValueError('CHARGE_NATIVE_OPERATION_CHANGED')
        return dict(operation_id=session.operation_id, boot_id=session.boot_id,
                    state=operation.result if operation.phase == 'TERMINAL' else 'RUNNING')

    async def stop_operation(self, session, intent):
        # Retain the caller's pre-send intent: a lost reply/DB must not remove the stop path.
        if intent.get('session_id') != session.session_id or not intent.get('correlation_id'):
            raise ValueError('CHARGE_STOP_SCOPE_CHANGED')
        if intent['kind'] == 'return':
            return await self.returns.stop_return(session)
        if intent['kind'] not in ('dock', 'undock'):
            raise ValueError('CHARGE_OPERATION_KIND_UNKNOWN')
        client = self._client(session)
        body = await client.docking_status()
        generation = self._owner(body, session)
        return await client.station_stop(StationMotionCommand(session_id=session.session_id,
            correlation_id=intent['correlation_id'], expected_boot_id=session.boot_id,
            expected_owner_generation=generation))
