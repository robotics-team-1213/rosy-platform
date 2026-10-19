"""Measured CORE return permission through the existing authenticated robot HTTP client.

The trip adapter owns submission/arrival. This port binds native generation once, validates
source evidence on every handover, and revokes only its persisted trip lease on stop.
"""
import asyncio
import math

from core_common.protocol.station_charging import StationTargetStatus, StationPoseAck, StationReturnPermit, StationMotionCommand

_SCOPE = ('session_id', 'robot_id', 'station_id', 'battery_id', 'boot_id', 'map_id',
          'map_revision', 'pose_revision', 'attempt_id')
_CONTEXT = (*_SCOPE, 'correlation_id', 'plan_id', 'lease_id')


class StationReturnHttp:
    def __init__(self, *, clients, store, stations, clock, permit_ttl_s):
        if (isinstance(permit_ttl_s, bool) or not isinstance(permit_ttl_s, (float, int))
                or not math.isfinite(permit_ttl_s) or not 0 < permit_ttl_s <= 2.):
            raise ValueError('CHARGE_RETURN_PERMIT_TTL_INVALID')
        self.clients, self.store, self.stations, self.clock = clients, store, stations, clock
        self.permit_ttl_s = permit_ttl_s

    def _client(self, session):
        client = self.clients().get(session.robot_id)
        if client is None or client.robot_id != session.robot_id:
            raise ValueError('CHARGE_RETURN_ROBOT_UNAVAILABLE')
        return client

    async def _context(self, session, context):
        current = await asyncio.to_thread(self.store.admitted_session, session.session_id, states={'RETURNING'})
        stored = await asyncio.to_thread(self.store.return_context, session.session_id)
        if (current is None or stored is None or stored['phase'] not in ('PREPARED', 'SUBMITTED', 'FINISH_PENDING')
                or any(getattr(current, key) != getattr(session, key) for key in _SCOPE)
                or any(stored[key] != context.get(key) for key in _CONTEXT)):
            raise ValueError('CHARGE_RETURN_CONTEXT_CHANGED')
        return stored

    def _live(self, session, target, body, *, returning=False, context=None, boundary=True):
        live = StationTargetStatus.model_validate(body.model_dump(), context={'now': self.clock(),
            'boot_id': session.boot_id, 'session_id': session.session_id})
        if (not live.binding_valid or live.battery_id != session.battery_id
                or live.ack.robot_id != session.robot_id or live.ack.station_id != session.station_id
                or live.target.model_dump(exclude={'captured_at', 'valid_until', 'uncertainty_m', 'uncertainty_rad'})
                    != target.model_dump(exclude={'captured_at', 'valid_until', 'uncertainty_m', 'uncertainty_rad'})):
            raise ValueError('CHARGE_RETURN_CORE_SCOPE_CHANGED')
        if returning:
            permit = live.return_permit
            if (not live.return_ready or permit is None or any(
                    getattr(permit, key) != context[key] for key in ('correlation_id', 'lease_id', 'expected_owner_generation'))
                    or permit.trip_id != context['plan_id']):
                raise ValueError('CHARGE_RETURN_CORE_AUTHORITY_LOST')
        elif boundary and (live.state != 'BOUND' or live.return_ready):
            raise ValueError('CHARGE_RETURN_CORE_BOUNDARY_REQUIRED')
        if not self.stations.accept_ack(live.ack):
            raise ValueError('CHARGE_RETURN_TARGET_NOT_ACCEPTED')
        return live

    async def read_target(self, session):
        """Refresh an actual binding ACK; no camera, seating or charge lifetime is renewed."""
        body = await self._client(session).station_target()
        current = await asyncio.to_thread(self.store.admitted_session, session.session_id, states={
            'RETURN_RESERVED', 'RETURNING', 'DOCKING', 'CHARGE_CONFIRMING', 'CHARGING', 'CHARGED_HOLD'})
        if current is None or any(getattr(current, key) != getattr(session, key) for key in _SCOPE):
            raise ValueError('CHARGE_RETURN_SCOPE_CHANGED')
        target = self.stations.store.get(session.station_id)
        if target is None:
            raise ValueError('CHARGE_RETURN_TARGET_CHANGED')
        return self._live(session, target, body, boundary=False).ack

    async def _owner(self, client, session, context=None):
        body = await client.docking_status()
        owner = body.get('owner') or {}
        generation = owner.get('owner_generation')
        if (owner.get('boot_id') != session.boot_id or type(generation) is not int or generation < 0
                or 'owner_run_id' not in owner or owner['owner_run_id'] is not None
                or context is not None and generation != context.get('expected_owner_generation')):
            raise ValueError('CHARGE_RETURN_NATIVE_OWNER_CHANGED')
        return generation

    def _permit(self, session, target, context, captured_at):
        return StationReturnPermit(**{key: getattr(session, key) for key in _SCOPE if key != 'attempt_id'},
            correlation_id=context['correlation_id'], lease_id=context['lease_id'], trip_id=context['plan_id'],
            expected_owner_generation=context['expected_owner_generation'], captured_at=captured_at,
            valid_until=min(captured_at+self.permit_ttl_s, target.valid_until))

    async def grant_return(self, session, target, context):
        captured = self.clock()
        client = self._client(session)
        stored = await self._context(session, context)
        if stored['phase'] != 'PREPARED' or 'expected_owner_generation' in stored:
            raise ValueError('CHARGE_RETURN_ALREADY_GRANTED_OR_UNKNOWN')
        body = await client.station_target()
        self._live(session, target, body)
        generation = await self._owner(client, session)
        stored = await asyncio.to_thread(self.store.bind_return_owner, session.session_id, context,
                                        owner_generation=generation)
        permit = self._permit(session, target, stored, captured)
        StationReturnPermit.model_validate(permit.model_dump(), context={'now': self.clock()})
        self._live(session, target, body)
        await self._context(session, stored)
        StationReturnPermit.model_validate(permit.model_dump(), context={'now': self.clock()})
        self._live(session, target, body)
        body = await client.station_return(permit)
        await self._context(session, stored)
        StationReturnPermit.model_validate(permit.model_dump(), context={'now': self.clock()})
        live = self._live(session, target, body, returning=True, context=stored)
        if live.return_permit != permit:
            raise ValueError('CHARGE_RETURN_GRANT_UNCONFIRMED')
        return live

    async def renew_return(self, session, target, context):
        captured = self.clock()
        client = self._client(session)
        stored = await self._context(session, context)
        body = await client.station_target()
        live = self._live(session, target, body, returning=True, context=stored)
        await self._owner(client, session, stored)
        permit = self._permit(session, target, stored, captured)
        StationReturnPermit.model_validate(permit.model_dump(), context={'now': self.clock()})
        await self._context(session, stored)
        StationReturnPermit.model_validate(permit.model_dump(), context={'now': self.clock()})
        self._live(session, target, body, returning=True, context=stored)
        # Same source time is a read, never a manufactured renewal.
        if captured > live.return_permit.captured_at:
            body = await client.station_return(permit)
        await self._context(session, stored)
        return self._live(session, target, body, returning=True, context=stored)

    async def finish_return(self, session, target, context):
        client = self._client(session)
        stored = await self._context(session, context)
        body = await client.station_target()
        self._live(session, target, body, returning=True, context=stored)
        await self._owner(client, session, stored)
        await self._context(session, stored)
        self._live(session, target, body, returning=True, context=stored)
        command = StationMotionCommand(session_id=session.session_id, correlation_id=stored['correlation_id'],
            expected_boot_id=session.boot_id, expected_owner_generation=stored['expected_owner_generation'])
        try:
            answer = await client.station_return_finish(command)
        except Exception as exc:
            if getattr(exc, 'status', None) == 409 and getattr(exc, 'code', None) == 'STATION_RETURN_STANDSTILL_REQUIRED':
                return None  # Explicit unchanged authority; every other refusal/unknown propagates.
            raise
        ack = StationPoseAck.model_validate(answer.model_dump(), context={'now': self.clock(),
            **{key: getattr(session, key) for key in ('session_id', 'boot_id', 'map_id', 'map_revision', 'pose_revision')}})
        body = await client.station_target()
        await self._context(session, stored)
        self._live(session, target, body)
        if ack.robot_id != session.robot_id or ack.station_id != session.station_id or not self.stations.accept_ack(ack):
            raise ValueError('CHARGE_RETURN_HANDOVER_UNCONFIRMED')
        return ack

    async def stop_return(self, session, context):
        if any(context.get(key) != getattr(session, key) for key in _SCOPE):
            raise ValueError('CHARGE_RETURN_STOP_SCOPE_CHANGED')
        # No DB dependency here: cancellation already owns this immutable context.
        # Exact DELETE revokes permission; it never proves measured standstill.
        try:
            await self._client(session).trip_lease_release(context['lease_id'])
        except Exception as exc:
            if getattr(exc, 'status', None) != 404:
                raise

    async def navigation_ready(self, session, context):
        """Read actual readiness before another lookahead; never cancel a live goal."""
        stored = await self._context(session, context)
        client = self._client(session)
        target = self.stations.store.get(session.station_id)
        live = await client.station_target()
        self._live(session, target, live, returning=True, context=stored)
        body = await client.station_navigation_state()
        await self._context(session, stored)
        fresh = await client.station_target()
        StationTargetStatus.model_validate(live.model_dump(), context={'now': self.clock()})
        self._live(session, target, fresh, returning=True, context=stored)
        owner = body.get('owner') or {}
        if (owner.get('boot_id') != session.boot_id or type(owner.get('owner_generation')) is not int
                or owner['owner_generation'] < 0
                or 'owner_run_id' not in owner or body.get('map_id') != session.map_id
                or body.get('mapping_active') is not False):
            raise ValueError('CHARGE_RETURN_NAVIGATION_UNKNOWN')
        # False means defer this lookahead, not accepted submission or physical arrival.
        if owner['owner_run_id'] is not None:
            return False
        operation = body.get('operation')
        if operation is None:
            return body.get('navigation') == 'IDLE'
        return (body.get('navigation') == 'ARRIVED' and operation.get('phase') == 'TERMINAL'
                and operation.get('result') == 'SUCCEEDED' and operation.get('boot_id') == session.boot_id)
