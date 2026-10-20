"""One configured station/robot uses the existing durable service from the Fleet loop."""
import asyncio
from copy import deepcopy
import math

from core_common.protocol.station_charging import ChargeDecision
from fleet.server.charge_policy_admission import ChargePolicyAdmission, work_request_digest

_TERMINAL = {'HOLD', 'CANCELED', 'WORK_AVAILABLE'}
_STATIONARY = {'CHARGE_CONFIRMING', 'CHARGING', 'CHARGED_HOLD'}


class ChargeRuntime:
    def __init__(self, service, *, robot_id, station_id, admission, monotonic, period_s, finish_work=None):
        if (not isinstance(admission, ChargePolicyAdmission) or service.admit_return is not admission
                or robot_id not in admission.profiles or not robot_id or not station_id
                or type(period_s) not in (int, float) or not math.isfinite(period_s)
                or not 0 < period_s <= admission.profiles[robot_id].reevaluate_interval_s):
            raise ValueError('CHARGE_RUNTIME_PROFILE_REQUIRED')
        self.service, self.robot_id, self.station_id = service, robot_id, station_id
        self.admission, self.monotonic, self.period_s = admission, monotonic, period_s
        self.finish_work = finish_work
        self._lock = asyncio.Lock()
        self._last_clock = self._next_evaluation = None
        self._closing = self._closed = self._running = False
        self.decision = None
        self._work_snapshot = self._work_target = None
        self._handover_pending = False
        self.reason = 'CHARGE_RUNTIME_NOT_EVALUATED'

    def work_admission(self, robot_id, *, task=None):
        """Final send guard revalidates original inputs; polling cannot renew their age."""
        if robot_id != self.robot_id:
            return None
        if self._closing or self.service.policy_enabled() is not True:
            return 'CHARGE_RUNTIME_DISPATCH_CLOSED'
        if self._work_snapshot is None:
            return 'CHARGE_POLICY_INPUT_UNVERIFIED'
        try:
            target = self.service._target(self.station_id, self._work_target.pose_revision)
            decision = self.admission(self._work_snapshot, target)
            if decision.decision == 'WORK_ALLOWED' and task is not None:
                budget = self._work_snapshot['charge_budget']
                if (task['robot_id'] != robot_id or budget['work_task_id'] != task['task_id']
                        or budget['work_request_digest'] != work_request_digest(task)):
                    return 'CHARGE_WORK_SCOPE_CHANGED'
        except Exception:
            return 'CHARGE_POLICY_INPUT_UNVERIFIED'
        return None if decision.decision == 'WORK_ALLOWED' else decision.reason

    async def _session(self):
        try:
            rows = await asyncio.to_thread(self.service.store.list)
        except Exception:
            self._closing = True
            await self.service.hold_cached(self.robot_id, reason='CHARGE_RUNTIME_STORAGE_UNAVAILABLE')
            raise
        rows = [row for row in rows if row.robot_id == self.robot_id and row.state != 'WORK_AVAILABLE']
        if len(rows) > 1:
            raise ValueError('CHARGE_RUNTIME_AMBIGUOUS_SESSION')
        return rows[0] if rows else None

    async def _hold(self, session, reason):
        self.reason = reason
        if session is not None and session.state not in _TERMINAL:
            return await self.service.hold(session.session_id, reason=reason)
        return session

    async def _read_policy(self):
        try:
            record = await asyncio.to_thread(self.service.stations.store.get, self.station_id)
            if record is None:
                raise ValueError('STATION_POSITION_NOT_VERIFIED')
            target = await asyncio.to_thread(self.service._target, self.station_id, record.pose_revision)
            snapshot = await self.service.motion.call(self.service.ports.snapshot, self.robot_id)
            if self._closing:
                return
            self.decision = self.admission(snapshot, target)
            self._work_snapshot, self._work_target = deepcopy(snapshot), target
            self.reason = self.decision.reason
            # Re-read the source when its original evidence expires, even if the
            # installed policy's periodic interval has not elapsed yet.
            if self.decision.decision != 'WAIT':
                samples = (snapshot, snapshot['battery_energy'], snapshot['charge_budget'])
                mono = self.monotonic()
                utc = self.admission.clock()
                if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (mono, utc))
                        or mono < self._last_clock):
                    raise ValueError('CHARGE_RUNTIME_CLOCK_INVALID')
                expiry = min(min(item['valid_until'], item['captured_at']+self.admission.max_age_s)
                    for item in samples)
                self._next_evaluation = min(self._next_evaluation, mono+max(0., expiry-utc))
        except Exception:
            self._work_snapshot = self._work_target = None
            self.decision = ChargeDecision(decision='WAIT', reason='CHARGE_RUNTIME_SOURCE_UNAVAILABLE',
                profile_revision=self.admission.profiles[self.robot_id].revision, capacity_revision=None)
            self.reason = self.decision.reason

    async def _finish_work(self):
        if self.finish_work is None:
            return False
        snapshot, target = self._work_snapshot, self._work_target

        def admission():
            if self._closing or self.service.policy_enabled() is not True:
                return 'CHARGE_POLICY_DISABLED'
            try:
                current = self.service._target(self.station_id, target.pose_revision)
                decision = self.admission(snapshot, current)
                return None if decision.decision == 'RETURN_REQUIRED' else decision.reason
            except Exception:
                return 'CHARGE_POLICY_INPUT_UNVERIFIED'

        try:
            if not await self.finish_work(self.robot_id, expected_boot_id=snapshot['boot_id'], admission=admission):
                self.reason = 'CHARGE_WORK_COMPLETION_REQUIRED'
                return False
            await self._read_policy()  # Passive mode acknowledgement cannot refresh source evidence.
            return self.decision.decision == 'RETURN_REQUIRED' and not self._closing
        except Exception:
            self.reason = 'CHARGE_WORK_HANDOVER_UNVERIFIED'
            return False

    async def tick(self):
        async with self._lock:
            if self._closing:
                return
            session = await self._session()
            now = self.monotonic()
            if (type(now) not in (int, float) or not math.isfinite(now)
                    or self._last_clock is not None and now < self._last_clock):
                return await self._hold(session, 'CHARGE_RUNTIME_CLOCK_INVALID')
            self._last_clock = now
            if session is not None and session.state in _TERMINAL:
                return session  # Periodic evaluation cannot reopen an uncertain operation.
            if session is not None and (session.station_id != self.station_id
                    or session.battery_id != self.admission.profiles[self.robot_id].battery_id):
                return await self._hold(session, 'CHARGE_RUNTIME_SCOPE_CHANGED')
            if self.service.policy_enabled() is not True:
                return await self._hold(session, 'CHARGE_POLICY_DISABLED')
            if self._next_evaluation is None or now >= self._next_evaluation:
                self._next_evaluation = now+self.admission.profiles[self.robot_id].reevaluate_interval_s
                await self._read_policy()
                if self._closing:
                    return
                if session is not None:
                    if (self.decision.decision == 'MAINTENANCE_HOLD'
                            or self.decision.decision == 'WAIT' and session.state not in _STATIONARY):
                        return await self._hold(session, self.decision.reason)
                elif self.decision.decision == 'RETURN_REQUIRED':
                    if self._work_snapshot.get('mode') == 'NAVIGATION' or self._handover_pending:
                        self._handover_pending = True
                        if not await self._finish_work():
                            return
                        self._handover_pending = False
                    try:
                        session = await self.service.request_return(self.robot_id, self.station_id,
                            pose_revision=self._work_target.pose_revision, reason=self.decision.reason)
                    except ValueError as exc:
                        self.reason = str(exc)  # Existing work keeps its owner until a safe work boundary.
                        return
            if session is not None and not self._closing:
                current = await self.service.advance(session.session_id)
                if current.state == 'CHARGED_HOLD':
                    current = await self.service.evaluate_departure(current.session_id)
                if current.state == 'WORK_AVAILABLE':
                    self._work_snapshot = self._work_target = None
                    await self._read_policy()  # Fresh selected-work budget at the actual handover.
                return current

    async def run(self):
        if self._running or self._closing:
            raise ValueError('CHARGE_RUNTIME_ALREADY_RUNNING_OR_CLOSED')
        self._running = True
        try:
            while not self._closing:
                await self.tick()
                await asyncio.sleep(self.period_s)
        finally:
            self._running = False
            await asyncio.shield(self.aclose())

    async def aclose(self):
        self._closing = True  # Close new admissions before waiting on an in-flight source/RPC.
        async with self._lock:
            if self._closed:
                return
            session = await self._session()
            await self._hold(session, 'CHARGE_RUNTIME_SHUTDOWN')
            self._closed = True
