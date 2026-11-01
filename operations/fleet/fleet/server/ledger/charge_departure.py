"""Fleet's selected-work departure coordinator; CORE remains the motion writer."""
import asyncio
import logging
from copy import deepcopy
from uuid import uuid4

from core_common.protocol.station_charging import StationDeparturePermit, StationDepartureReceipt
from fleet.server.charge_policy_admission import ChargeEnergyBudget, ChargePolicyAdmission, work_request_digest

_SCOPE = ('session_id', 'attempt_id', 'robot_id', 'station_id', 'boot_id', 'battery_id',
          'map_id', 'map_revision', 'pose_revision')
_TERMINAL = {'WORK_AVAILABLE', 'HOLD', 'CANCELED'}
_LOG = logging.getLogger(__name__)


class ChargeDeparture:
    def __init__(self, service):
        self.s = service

    async def _persist(self, function, *args, on_commit=None, **kwargs):
        # A canceled await cannot leave a SQLite writer running after cleanup.
        future = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        canceled = False
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                canceled = True
        result = future.result()
        if on_commit is not None:
            on_commit(result)
        if canceled:
            raise asyncio.CancelledError
        return result

    async def _eligible(self, current, target, snapshot):
        s = self.s
        if not isinstance(s.admit_return, ChargePolicyAdmission):
            return None
        decision = s.admit_return(snapshot, target, departing_charge=True)
        if decision.decision == 'MAINTENANCE_HOLD':
            raise ValueError(decision.reason)
        if decision.decision != 'WORK_ALLOWED':
            return None
        budget = ChargeEnergyBudget.model_validate(snapshot['charge_budget'], context={'now': s.clock(),
            **{key: getattr(current, key) for key in (
                'robot_id', 'boot_id', 'station_id', 'map_id', 'map_revision', 'pose_revision')}})
        if budget.work_task_id is None or budget.work_request_digest is None:
            return None
        task = await asyncio.to_thread(s.store.tasks.get_task, budget.work_task_id)
        if (task is None or task['robot_id'] != current.robot_id or task['status'] != 'QUEUED'
                or task['dispatch_phase'] != 'READY' or task['attempt_id'] is not None
                or work_request_digest(task) != budget.work_request_digest):
            return None
        return decision, budget

    def _validate_policy(self, current, target, snapshot, decision):
        s = self.s
        fresh_target = s._target(current.station_id, current.pose_revision)
        refreshed = {'captured_at', 'valid_until', 'uncertainty_m', 'uncertainty_rad'}
        if (fresh_target.model_dump(exclude=refreshed) != target.model_dump(exclude=refreshed)
                or s.policy_enabled() is not True or not s._fresh_snapshot(snapshot, current.robot_id)
                or s.admit_return(snapshot, fresh_target, departing_charge=True) != decision):
            raise ValueError('CHARGE_DEPARTURE_POLICY_CHANGED')
        return True

    async def _stop(self, current, reason):
        s = self.s
        cached = s.motion.session_stop_context(current.session_id)
        if cached is not None and cached[0].state == 'WORK_AVAILABLE':
            return cached[0]  # A settled, verified release must not recapture a subsequent work owner.
        if cached is not None and cached[1] is not None:
            try:
                await s.motion.call(s.ports.stop_operation, cached[0], cached[1])
            except Exception:
                pass  # A bounded exact stop attempt precedes any potentially stalled database read.
        try:
            latest = await asyncio.to_thread(s.store.get, current.session_id)
        except Exception:
            latest = None
        return await s.motion.stop_hold(latest or (cached[0] if cached else current), reason,
            intent=cached[1] if cached else None)

    async def evaluate(self, session_id):
        s = self.s
        current = await asyncio.to_thread(s.store.get, session_id)
        if current is None:
            raise ValueError('CHARGE_SESSION_NOT_FOUND')
        if current.state in _TERMINAL:
            return current
        if session_id not in s._reconciled:
            current = await s.reconcile(session_id)  # Owner readback only; never resubmit a PREPARED intent.
        async with s._lock(current.robot_id):
            try:
                current = await asyncio.to_thread(s.store.get, session_id)
                if current.state in _TERMINAL or current.state not in ('CHARGED_HOLD', 'UNDOCKING'):
                    return current
                intent = await asyncio.to_thread(s.store.operation_intent, session_id)
                s.motion.remember(current, intent)
                if current.state == 'CHARGED_HOLD':
                    current = await s.motion.observe_charge(current)
                    if current.state != 'CHARGED_HOLD':
                        return current
                target, snapshot = await s.motion.checked(current)
                snapshot = deepcopy(snapshot)
                eligible = await self._eligible(current, target, snapshot)
                if eligible is None:
                    if current.state == 'UNDOCKING':
                        return await self._stop(current, 'CHARGE_DEPARTURE_ENERGY_OR_WORK_UNVERIFIED')
                    return current
                decision, budget = eligible
                kwargs = dict(snapshot=snapshot, decision=decision, admission=s.admit_return,
                    guard=lambda: self._validate_policy(current, target, snapshot, decision))
                self._validate_policy(current, target, snapshot, decision)
                if current.state == 'CHARGED_HOLD':
                    if (snapshot.get('mode') != 'IDLE' or snapshot.get('safe_work_boundary') is not True
                            or snapshot.get('dock_state') not in ('DOCKED', 'CHARGING')):
                        return current
                    correlation = str(uuid4())
                    permission = await s.motion.call(s.ports.departure_permission, current, target,
                        correlation_id=correlation, **kwargs)
                    permission = StationDeparturePermit.model_validate(permission.model_dump(), context={
                        **{key: getattr(current, key) for key in _SCOPE}, 'now': s.clock(),
                        'work_task_id': budget.work_task_id, 'work_request_digest': budget.work_request_digest,
                        'correlation_id': correlation})
                    if (permission.policy_profile_revision != decision.profile_revision
                            or permission.capacity_revision != decision.capacity_revision):
                        raise ValueError('CHARGE_DEPARTURE_POLICY_SCOPE_CHANGED')
                    self._validate_policy(current, target, snapshot, decision)
                    # Cache only stop authority before a cancellable persistence or RPC boundary.
                    prepared = current.model_copy(update={'state': 'UNDOCKING', 'operation_id': None})
                    intent = dict(session_id=session_id, kind='undock', state='UNDOCKING',
                        correlation_id=correlation, operation_id=None, status='PREPARED')
                    s.motion.remember(prepared, intent)
                    prepared = await self._persist(s.store.prepare_departure, permission, clock=s.clock,
                        admission=lambda: self._validate_policy(current, target, snapshot, decision))
                    self._validate_policy(prepared, target, snapshot, decision)
                    operation_id = await s.motion.call(s.ports.start_undock, prepared, target, permission, **kwargs)
                    intent['operation_id'] = operation_id
                    s.motion.remember(prepared.model_copy(update={'operation_id': operation_id}), intent)
                    current = await self._persist(s.store.acknowledge_operation, session_id,
                        correlation_id=correlation, operation_id=operation_id, now=s.clock())
                    s.motion.remember(current, intent)
                    return current
                context = await asyncio.to_thread(s.store.departure_context, session_id)
                if (intent is None or intent['kind'] != 'undock' or intent['status'] != 'ACKNOWLEDGED'
                        or intent['operation_id'] != current.operation_id or context is None):
                    return await self._stop(current, 'CHARGE_DEPARTURE_OPERATION_UNKNOWN')
                permission = StationDeparturePermit.model_validate(context['permit'])
                if (budget.work_task_id != permission.work_task_id
                        or budget.work_request_digest != permission.work_request_digest
                        or decision.profile_revision != permission.policy_profile_revision
                        or decision.capacity_revision != permission.capacity_revision):
                    return await self._stop(current, 'CHARGE_DEPARTURE_SCOPE_CHANGED')
                proof = await s.motion.call(s.ports.advance_departure, current, context, **kwargs)
                if proof is None:
                    return current
                proof = StationDepartureReceipt.model_validate(proof.model_dump(), context={'now': s.clock()})
                self._validate_policy(current, target, snapshot, decision)
                return await self._persist(s.store.complete_departure, proof, clock=s.clock,
                    admission=lambda: self._validate_policy(current, target, snapshot, decision),
                    on_commit=lambda ready: s.motion.remember(ready, intent))
            except asyncio.CancelledError:
                await s.motion._cleanup(self._stop(current, 'CHARGE_DEPARTURE_CANCELED'))
                raise
            except Exception:
                # The stop stays the same; the cause is kept: unrecorded, it hid a station race for days (2026-10-30).
                _LOG.warning('charge %s: CHARGE_DEPARTURE_UNVERIFIED stop', current.session_id, exc_info=True)
                return await self._stop(current, 'CHARGE_DEPARTURE_UNVERIFIED')
