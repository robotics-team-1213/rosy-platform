"""Durable charge motion intents; ports submit to existing trip/native owners only once."""
from __future__ import annotations

import asyncio
import logging
import math
from uuid import uuid4

from core_common.protocol.station_charging import ChargeDecision, StationTargetStatus, StationPoseAck


TERMINAL = ('HOLD', 'CANCELED', 'WORK_AVAILABLE')
_LOG = logging.getLogger(__name__)


class ChargeMotion:
    def __init__(self, service):
        self.s = service
        self._stop_context = {}
        self._closing = set()

    def remember(self, current, intent):
        # Cleanup only: these immutable identifiers never authorize admission/replay.
        self._stop_context[current.robot_id] = (current, None if intent is None else dict(intent))

    def stop_context(self, robot_id):
        return self._stop_context.get(robot_id)

    def session_stop_context(self, session_id):
        return next((value for value in self._stop_context.values() if value[0].session_id == session_id), None)

    async def call(self, function, *args, **kwargs):
        return await asyncio.wait_for(function(*args, **kwargs), timeout=1.5)

    async def _settle(self, awaitable):
        # Cancellation must not release the robot lock while a journal writer or
        # bounded exact-stop attempt can still finish behind its next owner.
        task = asyncio.create_task(awaitable)
        canceled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                canceled = True
        return task.result(), canceled

    async def _cleanup(self, awaitable):
        result, interrupted = await self._settle(awaitable)
        if interrupted:
            raise asyncio.CancelledError
        return result

    async def stop_hold(self, current, reason, *, canceled=False, intent=None):
        s = self.s
        if current.state in TERMINAL:
            return current
        # Close local dispatch before any await. Existing durable claims remain
        # occupied; a stalled journal must not postpone a known exact stop.
        self._closing.add(current.session_id)
        held, failure = current, None
        canceled_await = False
        cached = self.session_stop_context(current.session_id)
        if intent is None and cached is not None:
            previous, saved = cached
            if (saved is not None and saved['operation_id'] == current.operation_id
                    and all(getattr(previous, key) == getattr(current, key) for key in (
                        'robot_id', 'station_id', 'battery_id', 'boot_id', 'map_id', 'map_revision',
                        'pose_revision', 'attempt_id'))):
                intent = dict(saved)
        try:
            if intent is None:
                intent, interrupted = await self._settle(
                    asyncio.to_thread(s.store.operation_intent, current.session_id))
                canceled_await |= interrupted
        except Exception as exc:
            failure = exc
        if intent is None and current.operation_id is not None:
            kind = {'RETURNING': 'return', 'DOCKING': 'dock', 'UNDOCKING': 'undock'}.get(current.state)
            if kind is not None:
                intent = dict(kind=kind, operation_id=current.operation_id, correlation_id=None,
                              session_id=current.session_id, state=current.state, status='UNKNOWN')
        if intent is not None:
            async def attempt_stop():
                nonlocal canceled_await
                try:
                    await self.call(s.ports.stop_operation, current, intent)
                except asyncio.CancelledError:
                    # A port may cancel itself; still close the durable journal.
                    canceled_await = True
                except Exception:
                    pass  # ACK never proves physical stop or permits claim release.
            _, interrupted = await self._settle(attempt_stop())
            canceled_await |= interrupted

        def journal():
            s.store.operation_unknown(current.session_id)
            now = s.clock()
            # A bad clock may close authority; it must never prevent a stop.
            if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
                now = current.updated_at
            return s.store.transition(current.session_id, expected_state=current.state,
                next_state='CANCELED' if canceled else 'HOLD', attempt_id=current.attempt_id,
                now=max(now, current.updated_at), reason=reason)
        try:
            held, interrupted = await self._settle(asyncio.to_thread(journal))
            canceled_await |= interrupted
            self.remember(held, intent)
        except Exception as exc:
            failure = exc
        if failure is not None:
            raise failure  # Never claim HOLD was durable when the write failed.
        if canceled_await:
            raise asyncio.CancelledError
        return held

    async def checked(self, current):
        s = self.s
        if (current.session_id in self._closing or s.policy_enabled() is not True
                or not s.store.admitted(current.session_id)):
            raise ValueError('CHARGE_DISPATCH_CLOSED')
        target = s._target(current.station_id, current.pose_revision)
        accepted = s.stations.ready_for_return(current.robot_id, current.station_id)
        if accepted is None:
            ack = await self.call(s.ports.read_target, current)
            ack = StationPoseAck.model_validate(ack.model_dump(), context={'now': s.clock(),
                **{key: getattr(current, key) for key in ('session_id', 'boot_id', 'map_id', 'map_revision', 'pose_revision')}})
            if (ack.robot_id != current.robot_id or ack.station_id != current.station_id
                    or not s.stations.accept_ack(ack)):
                raise ValueError('STATION_TARGET_NOT_ACCEPTED')
            accepted = s.stations.ready_for_return(current.robot_id, current.station_id)
        if accepted is None or accepted.pose_revision != current.pose_revision:
            raise ValueError('STATION_TARGET_NOT_ACCEPTED')
        snapshot = await self.call(s.ports.snapshot, current.robot_id)
        if (not s._fresh_snapshot(snapshot, current.robot_id)
                or snapshot['boot_id'] != current.boot_id or snapshot['battery_id'] != current.battery_id
                or snapshot.get('map_id') != current.map_id or snapshot.get('map_revision') != current.map_revision):
            raise ValueError('CHARGE_ROBOT_SCOPE_CHANGED')
        if snapshot.get('mode') == 'MANUAL' or snapshot.get('safety_latched') is not False:
            raise ValueError('CHARGE_LOCAL_STOP_OR_MANUAL')
        # Snapshot I/O cannot extend either source's original evidence lifetime.
        if (current.session_id in self._closing or s.policy_enabled() is not True
                or not s.store.admitted(current.session_id)
                or not s._fresh_snapshot(snapshot, current.robot_id)
                or s.stations.ready_for_return(current.robot_id, current.station_id) is None):
            raise ValueError('CHARGE_ADMISSION_CHANGED_DURING_READ')
        target = s._target(current.station_id, current.pose_revision)
        return target, snapshot

    async def start(self, current, *, kind, next_state, target, snapshot):
        s = self.s
        decision = s.admit_return(snapshot, target)
        decision = ChargeDecision.model_validate(decision.model_dump())
        if decision.decision not in ('RETURN_REQUIRED', 'WORK_ALLOWED'):
            return await self.stop_hold(current, 'CHARGE_RETURN_ENERGY_NOT_VERIFIED')
        correlation_id = str(uuid4())
        prepared = s.store.transition(
            current.session_id, expected_state=current.state, next_state=next_state,
            attempt_id=current.attempt_id, now=s.clock(), reason='CHARGE_OPERATION_PREPARED',
            intent_kind=kind, correlation_id=correlation_id)
        intent = dict(session_id=current.session_id, kind=kind, state=next_state,
                      correlation_id=correlation_id, operation_id=None, status='UNKNOWN')
        self.remember(prepared, intent)
        acknowledged, operation_id = None, None
        try:
            start = {'return': s.ports.start_return, 'dock': s.ports.start_dock}[kind]
            operation_id = await self.call(start, prepared, target, correlation_id=correlation_id)
            intent['operation_id'] = operation_id
            acknowledged = s.store.acknowledge_operation(
                current.session_id, correlation_id=correlation_id, operation_id=operation_id, now=s.clock())
            self.remember(acknowledged, intent)
            await self.checked(acknowledged)
            return acknowledged
        except asyncio.CancelledError:
            await self._cleanup(self.stop_hold(acknowledged or prepared,
                'CHARGE_OPERATION_CANCELED', intent=intent))
            raise
        except Exception:
            # Keep intent locally too: the database can disappear after send.
            return await self.stop_hold(acknowledged or prepared, 'CHARGE_OPERATION_SUBMISSION_UNKNOWN', intent=intent)

    async def observe_charge(self, current):
        s = self.s
        if s.policy_enabled() is not True or not s.store.admitted(current.session_id):
            raise ValueError('CHARGE_DISPATCH_CLOSED')
        s._target(current.station_id, current.pose_revision)
        intent = s.store.operation_intent(current.session_id)
        if (intent is None or intent['kind'] != 'dock' or intent['status'] != 'ACKNOWLEDGED'
                or current.operation_id is None or intent['operation_id'] != current.operation_id):
            raise ValueError('CHARGE_OPERATION_UNKNOWN')
        result = await self.call(s.ports.read_operation, current)
        if (result.get('operation_id') != current.operation_id or result.get('boot_id') != current.boot_id
                or result.get('state') != 'SUCCEEDED'):
            raise ValueError('CHARGE_ALIGNMENT_NOT_VERIFIED')
        body = await self.call(s.ports.read_station, current)
        body = body.model_dump() if isinstance(body, StationTargetStatus) else body
        context = {'now': s.clock(), 'session_id': current.session_id, 'boot_id': current.boot_id}
        live = StationTargetStatus.model_validate(body, context=context)
        if (not live.binding_valid or live.battery_id != current.battery_id
                or live.operation_id != current.operation_id or live.correlation_id != intent['correlation_id']
                or live.ack.robot_id != current.robot_id
                or any(getattr(live.ack, key) != getattr(current, key) for key in (
                    'station_id', 'map_id', 'map_revision', 'pose_revision'))):
            raise ValueError('CHARGE_STATION_SCOPE_CHANGED')
        # Refresh the actual binding ACK before checking it; camera/charge flags
        # retain their own original status lifetime and never renew from this ACK.
        if not s.stations.accept_ack(live.ack):
            raise ValueError('STATION_TARGET_NOT_ACCEPTED')
        await self.checked(current)
        StationTargetStatus.model_validate(body, context=context | {'now': s.clock()})
        if live.completion_verified:
            next_state = 'CHARGED_HOLD'
        elif live.state == 'CHARGING' and live.charging_verified:
            next_state = 'CHARGING'
        elif (current.state == 'CHARGE_CONFIRMING' and live.state in ('SEATING', 'CHARGE_CONFIRMING')
                and not live.charging_verified):
            return current
        else:
            raise ValueError('CHARGE_MEASURED_EVIDENCE_LOST')
        if current.state == next_state:
            return current  # Duplicate samples do not create another transition or departure.
        return s.store.transition(current.session_id, expected_state=current.state, next_state=next_state,
            attempt_id=current.attempt_id, operation_id=current.operation_id,
            now=s.clock(), reason='CORE_CHARGE_EVIDENCE_VERIFIED')

    async def advance(self, session_id):
        s = self.s
        current = s.store.get(session_id)
        if current is None:
            raise ValueError('CHARGE_SESSION_NOT_FOUND')
        if session_id not in s._reconciled:
            await s.reconcile(session_id)  # Read existing owner first; never a second submission.
        async with s._lock(current.robot_id):
            current = s.store.get(session_id)
            if current.state in TERMINAL:
                return current
            self.remember(current, s.store.operation_intent(session_id))
            try:
                if current.state in ('CHARGE_CONFIRMING', 'CHARGING', 'CHARGED_HOLD'):
                    return await self.observe_charge(current)
                target, snapshot = await self.checked(current)
                if current.state == 'RETURN_RESERVED':
                    if (snapshot.get('safe_work_boundary') is not True or snapshot.get('mode') != 'IDLE'
                            or snapshot.get('dock_state') not in ('UNDOCKED', 'DOCK_FAILED')):
                        return await self.stop_hold(current, 'CHARGE_WORK_BOUNDARY_REQUIRED')
                    return await self.start(current, kind='return', next_state='RETURNING',
                                            target=target, snapshot=snapshot)
                if current.state not in ('RETURNING', 'DOCKING'):
                    return current
                intent = s.store.operation_intent(session_id)
                if intent is None or intent['status'] != 'ACKNOWLEDGED' or current.operation_id is None:
                    return await self.stop_hold(current, 'CHARGE_OPERATION_UNKNOWN')
                result = await self.call(s.ports.read_operation, current)
                if (result.get('operation_id') != current.operation_id or result.get('boot_id') != current.boot_id
                        or result.get('state') not in ('RUNNING', 'SUCCEEDED')):
                    return await self.stop_hold(current, 'CHARGE_OPERATION_UNKNOWN')
                if result['state'] == 'RUNNING':
                    return current
                # Every handover rechecks target, energy and local scope after owner readback.
                target, snapshot = await self.checked(current)
                if current.state == 'RETURNING':
                    return await self.start(current, kind='dock', next_state='DOCKING',
                                            target=target, snapshot=snapshot)
                return s.store.transition(session_id, expected_state='DOCKING', next_state='CHARGE_CONFIRMING',
                                          attempt_id=current.attempt_id, operation_id=current.operation_id,
                                          now=s.clock(), reason='ALIGNMENT_SUCCEEDED')
            except asyncio.CancelledError:
                cached, intent = self.stop_context(current.robot_id)
                await self._cleanup(self.stop_hold(cached, 'CHARGE_OPERATION_CANCELED', intent=intent))
                raise
            except Exception:
                # The stop stays the same; only its cause is kept (see charge_departure.evaluate, 2026-10-30).
                _LOG.warning('charge %s: CHARGE_MOTION_READBACK_UNAVAILABLE stop', session_id, exc_info=True)
                cached, intent = self.stop_context(current.robot_id)
                return await self.stop_hold(cached, 'CHARGE_MOTION_READBACK_UNAVAILABLE', intent=intent)

    async def cancel(self, session_id, *, reason):
        s = self.s
        current = s.store.get(session_id)
        if current is None:
            raise ValueError('CHARGE_SESSION_NOT_FOUND')
        async with s._lock(current.robot_id):
            return await self.stop_hold(s.store.get(session_id), reason, canceled=True)
