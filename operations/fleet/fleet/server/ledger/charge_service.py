"""Charge-session admission and read-only recovery. Device owners retain motion authority."""
from __future__ import annotations

import asyncio
import math
from uuid import uuid4

from core_common.protocol.station_charging import ChargeDecision, ChargeSessionStatus
from fleet.server.charge_motion import ChargeMotion
from fleet.server.charge_departure import ChargeDeparture


class ChargeService:
    def __init__(self, store, *, stations, ports, clock, policy_enabled, admit_return,
                 id_factory=lambda: str(uuid4())):
        self.store, self.stations, self.ports = store, stations, ports
        self.clock, self.policy_enabled, self.admit_return = clock, policy_enabled, admit_return
        self.id_factory = id_factory
        self._locks = {}
        self._reconciled = set()
        self.motion = ChargeMotion(self)
        self.departure = ChargeDeparture(self)

    def _lock(self, robot_id):
        return self._locks.setdefault(robot_id, asyncio.Lock())

    def _target(self, station_id, pose_revision):
        if type(pose_revision) is not int or pose_revision < 1:
            raise ValueError('STATION_POSITION_NOT_VERIFIED')
        target = next((r for r in self.stations.installations() if r.station_id == station_id), None)
        if target is None or target.status != 'VALID' or target.pose_revision != pose_revision:
            raise ValueError('STATION_POSITION_NOT_VERIFIED')
        return target

    def _fresh_snapshot(self, snapshot, robot_id):
        now = self.clock()
        try:
            captured, expiry = snapshot['captured_at'], snapshot['valid_until']
            return (snapshot['robot_id'] == robot_id and all(
                not isinstance(v, bool) and isinstance(v, (float, int)) and math.isfinite(v)
                for v in (now, captured, expiry)) and captured <= now < expiry
                and isinstance(snapshot.get('boot_id'), str) and bool(snapshot['boot_id'])
                and isinstance(snapshot.get('battery_id'), str) and bool(snapshot['battery_id']))
        except (KeyError, TypeError):
            return False

    def _hold(self, current, reason):
        if current.state in ('HOLD', 'CANCELED', 'WORK_AVAILABLE'):
            return current
        return self.store.transition(current.session_id, expected_state=current.state, next_state='HOLD',
                                     attempt_id=current.attempt_id, now=self.clock(), reason=reason)

    async def request_return(self, robot_id: str, station_id: str, *, pose_revision: int,
                             reason: str) -> ChargeSessionStatus:
        async with self._lock(robot_id):
            if self.policy_enabled() is not True:
                raise ValueError('CHARGE_POLICY_DISABLED')
            target = self._target(station_id, pose_revision)
            previous = next((s for s in self.store.list() if s.robot_id == robot_id
                             and s.state != 'WORK_AVAILABLE'), None)
            if previous is not None:
                if previous.station_id != station_id or previous.pose_revision != pose_revision:
                    raise ValueError('STATION_POSITION_REQUIRES_RECONCILIATION')
                return previous
            snapshot = await self.ports.snapshot(robot_id)
            if not self._fresh_snapshot(snapshot, robot_id):
                raise ValueError('CHARGE_ROBOT_STATE_NOT_VERIFIED')
            if (snapshot.get('mode') != 'IDLE' or snapshot.get('safe_work_boundary') is not True
                    or snapshot.get('safety_latched') is not False):
                raise ValueError('CHARGE_WORK_BOUNDARY_REQUIRED')
            if snapshot.get('dock_state') not in ('UNDOCKED', 'DOCK_FAILED'):
                raise ValueError('CHARGE_LOCAL_DOCK_OWNER_ACTIVE')
            decision = self.admit_return(snapshot, target)
            decision = ChargeDecision.model_validate(decision.model_dump())
            if decision.decision not in ('RETURN_REQUIRED', 'WORK_ALLOWED'):
                raise ValueError('CHARGE_RETURN_ENERGY_NOT_VERIFIED')
            if self.policy_enabled() is not True:
                raise ValueError('CHARGE_POLICY_DISABLED')
            self._target(station_id, pose_revision)
            session = self.store.reserve(ChargeSessionStatus(
                session_id=self.id_factory(), robot_id=robot_id, station_id=station_id,
                battery_id=snapshot['battery_id'], boot_id=snapshot['boot_id'],
                pose_revision=target.pose_revision, map_id=target.map_id, map_revision=target.map_revision,
                state='RETURN_RESERVED', attempt_id=self.id_factory(), reason=reason, updated_at=self.clock()))
            self.motion.remember(session, None)
            if self.policy_enabled() is not True or not self.store.admitted(session.session_id):
                return self._hold(session, 'CHARGE_DISPATCH_CLOSED')
            try:
                ack = await self.ports.bind_target(session, target)
                if not self.stations.accept_ack(ack):
                    return self._hold(session, 'STATION_TARGET_NOT_ACCEPTED')
            except Exception:
                return self._hold(session, 'STATION_TARGET_ACCEPTANCE_UNKNOWN')
            self._reconciled.add(session.session_id)
            return session

    async def reconcile(self, session_id: str) -> ChargeSessionStatus:
        current = self.store.get(session_id)
        if current is None:
            raise ValueError('CHARGE_SESSION_NOT_FOUND')
        async with self._lock(current.robot_id):
            current = self.store.get(session_id)
            if current.state in ('HOLD', 'CANCELED', 'WORK_AVAILABLE'):
                return current
            if self.policy_enabled() is not True or not self.store.admitted(session_id):
                return await self.motion.stop_hold(current, 'CHARGE_DISPATCH_CLOSED')
            try:
                intent = self.store.operation_intent(session_id)
                self.motion.remember(current, intent)
                if intent is not None and intent['status'] != 'ACKNOWLEDGED':
                    return await self.motion.stop_hold(current, 'CHARGE_OPERATION_UNKNOWN')
                self._target(current.station_id, current.pose_revision)
                snapshot = await self.ports.snapshot(current.robot_id)
                if (not self._fresh_snapshot(snapshot, current.robot_id)
                        or snapshot['boot_id'] != current.boot_id or snapshot['battery_id'] != current.battery_id):
                    return await self.motion.stop_hold(current, 'CHARGE_ROBOT_SCOPE_CHANGED')
                if snapshot.get('safety_latched') is not False or snapshot.get('mode') == 'MANUAL':
                    return await self.motion.stop_hold(current, 'CHARGE_LOCAL_STOP_OR_MANUAL')
                if current.operation_id is not None:
                    operation = await self.ports.read_operation(current)
                    if (operation.get('operation_id') != current.operation_id
                            or operation.get('boot_id') != current.boot_id
                            or operation.get('state') not in ('RUNNING', 'SUCCEEDED')):
                        return await self.motion.stop_hold(current, 'CHARGE_OPERATION_UNKNOWN')
                else:
                    ack = await self.ports.read_target(current)
                    if not self.stations.accept_ack(ack):
                        return await self.motion.stop_hold(current, 'STATION_TARGET_NOT_ACCEPTED')
                self._reconciled.add(session_id)
                return current
            except asyncio.CancelledError:
                await self.motion._cleanup(self.motion.stop_hold(current, 'CHARGE_READBACK_CANCELED', intent=intent))
                raise
            except Exception:
                return await self.motion.stop_hold(current, 'CHARGE_READBACK_UNAVAILABLE')

    async def advance(self, session_id: str) -> ChargeSessionStatus:
        current = await asyncio.to_thread(self.store.get, session_id)
        if current is not None and current.state == 'UNDOCKING':
            return await self.departure.evaluate(session_id)
        return await self.motion.advance(session_id)

    async def evaluate_departure(self, session_id: str) -> ChargeSessionStatus:
        return await self.departure.evaluate(session_id)

    async def cancel(self, session_id: str, *, reason: str) -> ChargeSessionStatus:
        return await self.motion.cancel(session_id, reason=reason)

    async def hold(self, session_id: str, *, reason: str) -> ChargeSessionStatus:
        try:
            current = self.store.get(session_id)
        except Exception:
            context = self.motion.session_stop_context(session_id)
            if context is None:
                raise
            return await self.hold_cached(context[0].robot_id, reason=reason)
        if current is None:
            raise ValueError('CHARGE_SESSION_NOT_FOUND')
        async with self._lock(current.robot_id):
            try:
                current = self.store.get(session_id)
            except Exception:
                context = self.motion.session_stop_context(session_id)
                if context is None:
                    raise
                return await self.motion.stop_hold(context[0], reason, intent=context[1])
            return await self.motion.stop_hold(current, reason)

    async def hold_cached(self, robot_id: str, *, reason: str):
        async with self._lock(robot_id):
            context = self.motion.stop_context(robot_id)
            if context is not None:
                return await self.motion.stop_hold(context[0], reason, intent=context[1])
