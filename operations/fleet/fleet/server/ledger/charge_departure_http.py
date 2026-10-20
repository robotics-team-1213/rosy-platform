"""Selected-work departure through CORE; no physical facts are synthesized here."""
import asyncio

from core_common.protocol.native_operation import NativeOperation
from core_common.protocol.station_charging import (
    BatteryEnergyEvidence, StationDeparturePermit, StationDepartureReceipt, StationMotionCommand,
    StationTargetStatus,
)
from fleet.server.charge_policy_admission import ChargeEnergyBudget, ChargePolicyAdmission

_SCOPE = ('session_id', 'robot_id', 'station_id', 'battery_id', 'boot_id', 'map_id',
          'map_revision', 'pose_revision', 'attempt_id')
_MUTABLE = {'captured_at', 'valid_until', 'expected_owner_generation'}


class ChargeDepartureHttp:
    def __init__(self, port):
        self.p = port

    def _policy(self, session, target, snapshot, decision, admission, guard):
        if (not isinstance(admission, ChargePolicyAdmission) or guard() is not True
                or decision.decision != 'WORK_ALLOWED'
                or admission(snapshot, target, departing_charge=True) != decision):
            raise ValueError('CHARGE_DEPARTURE_POLICY_CHANGED')
        budget = ChargeEnergyBudget.model_validate(snapshot['charge_budget'], context={'now': self.p.clock(),
            **{key: getattr(session, key) for key in ('robot_id', 'boot_id', 'station_id',
                'map_id', 'map_revision', 'pose_revision')}})
        if (snapshot['boot_id'] != session.boot_id or snapshot['battery_id'] != session.battery_id
                or budget.work_task_id is None or budget.work_request_digest is None):
            raise ValueError('CHARGE_DEPARTURE_WORK_UNVERIFIED')
        return budget

    def _permission(self, session, target, correlation, generation, *, snapshot, decision, admission, guard):
        budget = self._policy(session, target, snapshot, decision, admission, guard)
        battery = BatteryEnergyEvidence.model_validate(snapshot['battery_energy'], context={
            'now': self.p.clock(), 'battery_id': session.battery_id})
        now = self.p.clock()
        expiry = min(now+1., target.valid_until, snapshot['valid_until'], battery.valid_until,
            budget.valid_until, snapshot['captured_at']+admission.max_age_s,
            battery.captured_at+admission.max_age_s, budget.captured_at+admission.max_age_s)
        return StationDeparturePermit.model_validate(dict(
            **{key: getattr(session, key) for key in _SCOPE}, correlation_id=correlation,
            work_task_id=budget.work_task_id, work_request_digest=budget.work_request_digest,
            policy_profile_revision=decision.profile_revision, capacity_revision=decision.capacity_revision,
            expected_owner_generation=generation, captured_at=now, valid_until=expiry), context={'now': now})

    async def permission(self, session, target, *, correlation_id, **policy):
        p = self.p
        live = await p.read_station(session)
        generation = p._owner(await p._client(session).docking_status(), session, vacant=True)
        await p._admitted(session, {'CHARGED_HOLD'})
        StationTargetStatus.model_validate(live.model_dump(), context={'now': p.clock()})
        if live.state != 'CHARGED_HOLD' or not live.completion_verified:
            raise ValueError('CHARGE_DEPARTURE_COMPLETION_REQUIRED')
        return self._permission(session, target, correlation_id, generation, **policy)

    async def start(self, session, target, permission, **policy):
        p = self.p
        await p._admitted(session, {'UNDOCKING'})
        context = await asyncio.to_thread(p.store.departure_context, session.session_id)
        intent = await asyncio.to_thread(p.store.operation_intent, session.session_id)
        live = await p.read_station(session)
        generation = p._owner(await p._client(session).docking_status(), session, vacant=True)
        await p._admitted(session, {'UNDOCKING'})
        self._policy(session, target, **policy)
        permission = StationDeparturePermit.model_validate(permission.model_dump(), context={
            'now': p.clock(), **{key: getattr(session, key) for key in _SCOPE}})
        StationTargetStatus.model_validate(live.model_dump(), context={'now': p.clock()})
        if (context is None or context['permit'] != permission.model_dump()
                or intent is None or intent['kind'] != 'undock' or intent['status'] != 'PREPARED'
                or intent['correlation_id'] != permission.correlation_id or intent['operation_id'] is not None
                or generation != permission.expected_owner_generation
                or live.state != 'CHARGED_HOLD' or not live.completion_verified):
            raise ValueError('CHARGE_DEPARTURE_PREPARATION_CHANGED')
        await asyncio.to_thread(p.store.validate_departure_permission, permission, prepared=True,
            clock=p.clock, admission=lambda: bool(self._policy(session, target, **policy)))
        self._policy(session, target, **policy)
        StationDeparturePermit.model_validate(permission.model_dump(), context={'now': p.clock()})
        # This is the sole motion submission. An unknown response propagates to HOLD.
        operation = await p._client(session).station_undock(permission)
        if (str(operation.boot_id) != session.boot_id or operation.correlation_id != permission.correlation_id
                or operation.kind != 'undock'):
            raise ValueError('CHARGE_DEPARTURE_SUBMISSION_UNKNOWN')
        return str(operation.run_id)

    async def _persist_renewal(self, permission, previous, check):
        p = self.p
        future = asyncio.create_task(asyncio.to_thread(p.store.renew_departure_permission,
            permission, previous=previous, clock=p.clock, admission=check))
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Settle the writer before outer cleanup/reconciliation inspects the ledger.
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    pass
            future.result()
            raise

    def _receipt(self, session, original, active, live, body):
        p = self.p
        proof = live.departure_receipt
        if proof is None:
            raise ValueError('CHARGE_DEPARTURE_RECEIPT_REQUIRED')
        proof = StationDepartureReceipt.model_validate(proof.model_dump(), context={'now': p.clock(),
            **{key: getattr(original, key) for key in (*_SCOPE, 'correlation_id',
                'work_task_id', 'work_request_digest')}})
        operation = self._operation(session, original, body)
        generation = p._owner(body, session, vacant=True)
        if (live.state != 'WORK_AVAILABLE' or operation.phase != 'TERMINAL' or operation.result != 'SUCCEEDED'
                or proof.operation_id != session.operation_id or proof.owner_generation != generation
                or proof.owner_generation <= original.expected_owner_generation
                or proof.owner_generation < active.expected_owner_generation
                or proof.valid_until > active.valid_until):
            raise ValueError('CHARGE_DEPARTURE_RECEIPT_SCOPE_CHANGED')
        return proof

    def _operation(self, session, original, body):
        operation = NativeOperation.model_validate(body['operation'])
        owner = body.get('owner') or {}
        self.p._owner(body, session)
        if (body.get('lookup') != 'FOUND' or str(operation.run_id) != session.operation_id
                or str(operation.boot_id) != session.boot_id or operation.kind != 'undock'
                or operation.correlation_id != original.correlation_id
                or owner.get('owner_run_id') != (None if operation.phase == 'TERMINAL' else session.operation_id)):
            raise ValueError('CHARGE_NATIVE_OPERATION_CHANGED')
        return operation

    async def advance(self, session, context, **policy):
        p = self.p
        await p._admitted(session, {'UNDOCKING'})
        target = await p._target(session)
        live = await p.read_station(session)
        client = p._client(session)
        body = await client.docking_status(session.operation_id)
        original = StationDeparturePermit.model_validate(context['permit'])
        active = StationDeparturePermit.model_validate(context['active_permit'])
        operation = self._operation(session, original, body)
        check = lambda: bool(self._policy(session, target, **policy))
        check()
        if live.departure_receipt is not None:
            proof = self._receipt(session, original, active, live, body)
            check()
            return proof
        StationDeparturePermit.model_validate(active.model_dump(), context={'now': p.clock()})
        actual = live.departure_permit
        if (actual is None or actual.model_dump(exclude={'valid_until'}) != active.model_dump(exclude={'valid_until'})
                or actual.valid_until > active.valid_until or operation.result not in (None, 'SUCCEEDED')):
            raise ValueError('CHARGE_DEPARTURE_AUTHORITY_LOST')
        if p.clock() > active.captured_at:
            renewed = self._permission(session, target, original.correlation_id, p._owner(body, session), **policy)
            if renewed.model_dump(exclude=_MUTABLE) != original.model_dump(exclude=_MUTABLE):
                raise ValueError('CHARGE_DEPARTURE_WORK_CHANGED')
            await asyncio.to_thread(p.store.validate_departure_permission, active, prepared=False,
                clock=p.clock, admission=check)
            check()
            StationDeparturePermit.model_validate(active.model_dump(), context={'now': p.clock()})
            StationDeparturePermit.model_validate(renewed.model_dump(), context={'now': p.clock()})
            try:
                await client.station_departure(renewed)
            except Exception as exc:
                if (getattr(exc, 'status', None) != 409
                        or getattr(exc, 'code', None) != 'OWNER_GENERATION_CHANGED'
                        or operation.phase == 'TERMINAL'):
                    raise
                await p._admitted(session, {'UNDOCKING'})
                live = await p.read_station(session)
                body = await client.docking_status(session.operation_id)
                terminal = self._operation(session, original, body)
                if (terminal.phase != 'TERMINAL' or terminal.result != 'SUCCEEDED'
                        or p._owner(body, session, vacant=True) != renewed.expected_owner_generation+1):
                    raise
                check()
                StationDeparturePermit.model_validate(active.model_dump(), context={'now': p.clock()})
                if live.departure_receipt is not None:
                    proof = self._receipt(session, original, active, live, body)
                    check()
                    return proof
                actual = live.departure_permit
                if (live.state != 'DEPARTURE_CHECK' or actual is None
                        or actual.model_dump(exclude={'valid_until'}) != active.model_dump(exclude={'valid_until'})
                        or actual.valid_until > active.valid_until):
                    raise
                return None  # Same run completed; the next tick rechecks fresh authority before finish.
            await self._persist_renewal(renewed, active, check)
            active = renewed
        if operation.phase != 'TERMINAL':
            return None
        command = StationMotionCommand(session_id=session.session_id, correlation_id=original.correlation_id,
            expected_boot_id=session.boot_id, expected_owner_generation=p._owner(body, session, vacant=True))
        await asyncio.to_thread(p.store.validate_departure_permission, active, prepared=False,
            clock=p.clock, admission=check)
        check()
        try:
            await client.station_departure_finish(command)
        except Exception as exc:
            if (getattr(exc, 'status', None) == 409
                    and getattr(exc, 'code', None) == 'STATION_DEPARTURE_STANDSTILL_REQUIRED'):
                return None  # Explicit rejection: new local stop dwell may become sufficient later.
            if getattr(exc, 'status', None) is not None:
                raise  # Explicit protocol refusal is not a lost response.
            # A finish reply may be lost after CORE committed the receipt. Read only;
            # absence/expiry propagates to HOLD, never another motion submission.
            pass
        live = await client.station_target()
        StationTargetStatus.model_validate(live.model_dump(), context={'now': p.clock()})
        body = await client.docking_status(session.operation_id)
        await p._admitted(session, {'UNDOCKING'})
        proof = self._receipt(session, original, active, live, body)
        check()
        return proof
