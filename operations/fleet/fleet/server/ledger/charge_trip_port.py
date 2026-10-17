"""One durable charging return uses the existing TripRunner, never another motion writer.

Construct explicitly with a measured CORE return port, route-energy admission and a binding
``map_scope(active_version, active_map_id)`` from this installed route map to station map scope.
A returned plan id acknowledges submission tracking; only trip arrival plus CORE stop handover succeeds.
Reconstruction never resumes a submission or repeats an uncertain finish request.
"""
from __future__ import annotations

import asyncio
import inspect
from uuid import uuid4

from core_common.protocol.station_charging import ChargeDecision, StationPoseAck, StationPoseRecord

_SCOPE = ('session_id', 'robot_id', 'station_id', 'battery_id', 'boot_id',
          'map_id', 'map_revision', 'pose_revision', 'attempt_id')


async def _maybe(value):
    return await value if inspect.isawaitable(value) else value


class ChargeReturnTrip:
    def __init__(self, *, runner, plans, store, stations, robot_port, plan, capabilities,
                 principal_id, map_scope, clock, admit_return):
        self.runner, self.plans, self.store, self.stations = runner, plans, store, stations
        self.robot_port, self.plan, self.capabilities = robot_port, plan, capabilities
        self.principal_id, self.map_scope, self.clock = principal_id, map_scope, clock
        self.admit_return = admit_return
        self._tasks, self._tokens, self._locks, self._contexts = {}, {}, {}, {}
        self._stop_locks = {}
        self._arrival_wait = {}
        self.runner.charge_goal_ready = self.ready_free_goal

    def _lock(self, session):
        return self._locks.setdefault(session.session_id, asyncio.Lock())

    async def _checked(self, session, context=None):
        current = await asyncio.to_thread(self.store.admitted_session, session.session_id, states={'RETURNING'})
        if current is None or any(getattr(current, key) != getattr(session, key) for key in _SCOPE):
            raise ValueError('CHARGE_RETURN_SCOPE_CHANGED')
        if context is not None and any(context[key] != getattr(current, key) for key in _SCOPE):
            raise ValueError('CHARGE_RETURN_CONTEXT_CHANGED')
        target = self.stations.store.get(current.station_id)
        active = self.plans.active()
        if (target is None or target.status != 'VALID' or not target.approach_verified
                or target.approach_pose is None or target.pose_revision != current.pose_revision
                or active is None or self.map_scope(active[0], active[1].map_id) != (
                    current.map_id, current.map_revision)):
            raise ValueError('CHARGE_RETURN_TARGET_CHANGED')
        StationPoseRecord.model_validate(target.model_dump(), context={
            'now': self.clock(), 'map_id': current.map_id, 'map_revision': current.map_revision})
        if (target.map_id, target.map_revision) != (current.map_id, current.map_revision):
            raise ValueError('CHARGE_RETURN_MAP_CHANGED')
        return target

    def _plan_checked(self, session, target, plan_id):
        row, active = self.plans.plan(plan_id), self.plans.active()
        if (row is None or active is None or row['robot_id'] != session.robot_id
                or row['principal_id'] != self.principal_id or row['map_version'] != active[0]
                or row['request'].get('repeat') or row['request'].get('convoy')
                or row['request'].get('to') != target.approach_pose.model_dump()
                or row['result'].get('plan', {}).get('map_version') != active[0]):
            raise ValueError('CHARGE_RETURN_PLAN_CHANGED')
        if not self.runner.return_endpoint_matches(row, target.approach_pose):
            raise ValueError('CHARGE_RETURN_ENDPOINT_CHANGED')
        decision = self.admit_return(session, target, row)
        decision = ChargeDecision.model_validate(decision.model_dump())
        if decision.decision not in ('RETURN_REQUIRED', 'WORK_ALLOWED'):
            raise ValueError('CHARGE_RETURN_ENERGY_NOT_VERIFIED')
        return row

    def _lease_checked(self, session, context):
        job = self.runner.lease.jobs.get(session.robot_id)
        if (job is None or job.view.get('owner_kind') != 'charge_session'
                or job.view['job_id'] != session.session_id or job.view['trip_id'] != context['plan_id']
                or job.view['lease']['lease_id'] != context['lease_id']
                or job.view['lease']['state'] != 'held'
                or self.runner.lease.now() - job.view['lease']['renewed_at'] >= self.runner.lease.ttl_s):
            raise ValueError('CHARGE_RETURN_LEASE_LOST')

    async def _guard(self, session, context, token):
        target = await self._checked(session, context)
        self.runner._check_start_token(session.robot_id, token)
        self._plan_checked(session, target, context['plan_id'])
        self._lease_checked(session, context)
        return target

    async def start_return(self, session, target, *, correlation_id):
        token = self.runner._start_token(session.robot_id)  # before the first await, including the lock
        async with self._lock(session):
            actual = await self._checked(session)
            if actual != target or await asyncio.to_thread(self.store.return_context, session.session_id) is not None:
                raise ValueError('CHARGE_RETURN_ALREADY_PREPARED_OR_TARGET_CHANGED')
            plan_id = await _maybe(self.plan(session, actual))
            actual = await self._checked(session)
            self.runner._check_start_token(session.robot_id, token)
            self._plan_checked(session, actual, plan_id)
            context = await asyncio.to_thread(self.store.prepare_return, session.session_id,
                correlation_id=correlation_id, plan_id=plan_id, lease_id=uuid4().hex)
            self._contexts[session.session_id] = context
            self._tokens[session.session_id] = token
            try:
                caps = await _maybe(self.capabilities(session.robot_id))
                actual = await self._checked(session, context)
                self.runner._check_start_token(session.robot_id, token)
                self._plan_checked(session, actual, plan_id)
                await self.runner.hold_job(session.robot_id, session.session_id, self.principal_id, caps,
                    owner_kind='charge_session', trip_id=plan_id, lease_id=context['lease_id'])
                actual = await self._guard(session, context, token)
                await asyncio.wait_for(self.robot_port.grant_return(session, actual, context), 1.0)
                await self._guard(session, context, token)
                await asyncio.to_thread(self.store.return_phase, session.session_id,
                                        expected='PREPARED', next_phase='SUBMITTED')
                await self._guard(session, context, token)
                self._tasks[session.session_id] = asyncio.create_task(self._run(session, context, token))
                return plan_id
            except BaseException:
                await asyncio.shield(self.stop_return(session))
                raise

    async def ready_free_goal(self, robot_id, job):
        """Keep the current native goal until terminal; every wait retains exact charge fences."""
        session = await asyncio.to_thread(self.store.admitted_session, job.view['job_id'], states={'RETURNING'})
        if session is None or session.robot_id != robot_id:
            raise ValueError('CHARGE_RETURN_SCOPE_CHANGED')
        context = self._contexts.get(session.session_id)
        token = self._tokens.get(session.session_id)
        if context is None or token is None or self.runner.lease.jobs.get(robot_id) is not job:
            raise ValueError('CHARGE_RETURN_CONTEXT_CHANGED')
        await self._guard(session, context, token)
        ready = await self.robot_port.navigation_ready(session, context)
        await self._guard(session, context, token)
        if self.runner.lease.jobs.get(robot_id) is not job:
            raise ValueError('CHARGE_RETURN_LEASE_LOST')
        return ready is True

    async def _run(self, session, context, token):
        try:
            await self.runner.start(context['plan_id'], self.principal_id, job_id=session.session_id,
                start_token=token, start_guard=lambda: self._guard(session, context, token))
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.stop_return(session)  # no resubmission after a failed or unknown start

    async def read_return(self, session):
        async with self._lock(session):
            context = await asyncio.to_thread(self.store.return_context, session.session_id)
            if context is None or context['phase'] not in ('SUBMITTED', 'FINISHED'):
                raise ValueError('CHARGE_RETURN_UNKNOWN')
            target = await self._checked(session, context)
            self._plan_checked(session, target, context['plan_id'])
            result = {'operation_id': context['plan_id'], 'boot_id': session.boot_id, 'state': 'RUNNING'}
            if context['phase'] == 'FINISHED':
                return result | {'state': 'SUCCEEDED'}
            token = self._tokens.get(session.session_id)
            task = self._tasks.get(session.session_id)
            if token is None or task is None or task.cancelled():
                raise ValueError('CHARGE_RETURN_RESTART_RECONCILIATION_REQUIRED')
            await self._guard(session, context, token)
            await asyncio.wait_for(self.robot_port.renew_return(session, target, context), 1.0)
            await self._guard(session, context, token)
            view = self.runner.view(context['plan_id'])
            if view is None and not task.done():
                return result  # pending entry alignment, not evidence of physical movement
            if (view is None or view['robot_id'] != session.robot_id
                    or view['started_by'] != self.principal_id
                    or view['map_version'] != self.plans.active()[0]):
                raise ValueError('CHARGE_RETURN_TRIP_UNKNOWN')
            if view['state'] in ('started', 'running', 'link_wait'):
                return result
            if view['state'] != 'arrived':
                raise ValueError('CHARGE_RETURN_NOT_ARRIVED')
            since = self._arrival_wait.setdefault(session.session_id, self.clock())
            ready = await asyncio.wait_for(self.robot_port.navigation_ready(session, context), 1.0)
            target = await self._guard(session, context, token)
            if not 0 <= self.clock()-since < self.runner.config.stall_s:
                raise ValueError('CHARGE_RETURN_NAVIGATION_TERMINAL_TIMEOUT')
            if ready is not True:
                return result  # Route proximity is not native terminal evidence; no finish sent.
            await asyncio.to_thread(self.store.return_phase, session.session_id,
                                    expected='SUBMITTED', next_phase='FINISH_PENDING')
            target = await self._guard(session, context, token)
            # A lost reply leaves FINISH_PENDING; a subsequent read never repeats this command.
            answer = await asyncio.wait_for(self.robot_port.finish_return(session, target, context), 1.0)
            await self._guard(session, context, token)
            if answer is None:  # Only the HTTP port's definite standstill refusal, never an unknown reply.
                await asyncio.to_thread(self.store.return_phase, session.session_id,
                    expected='FINISH_PENDING', next_phase='SUBMITTED',
                    refusal_code='STATION_RETURN_STANDSTILL_REQUIRED')
                return result
            ack = StationPoseAck.model_validate(answer.model_dump(), context={
                'now': self.clock(), 'boot_id': session.boot_id, 'session_id': session.session_id,
                'map_id': session.map_id, 'map_revision': session.map_revision, 'pose_revision': session.pose_revision})
            if (ack.robot_id != session.robot_id or ack.station_id != session.station_id
                    or not self.stations.accept_ack(ack)):
                raise ValueError('CHARGE_RETURN_HANDOVER_UNKNOWN')
            self.runner.release_job(session.robot_id, session.session_id)
            await asyncio.to_thread(self.store.return_phase, session.session_id,
                                    expected='FINISH_PENDING', next_phase='FINISHED')
            self._arrival_wait.pop(session.session_id, None)
            return result | {'state': 'SUCCEEDED'}

    async def stop_return(self, session):
        async with self._stop_locks.setdefault(session.session_id, asyncio.Lock()):
            return await self._stop(session)

    async def _stop(self, session):
        context, failure = self._contexts.get(session.session_id), None
        # A live submission is fenced before any await, including a possibly contended DB read.
        # Restart recovery has no in-memory task and only reads the persisted exact context.
        if context is None:
            context = await asyncio.to_thread(self.store.return_context, session.session_id)
        if context is None or any(context[key] != getattr(session, key) for key in _SCOPE):
            if failure is not None:
                raise failure
            return
        token = self._tokens.pop(session.session_id, None)
        if token is not None and self.runner._start_token(session.robot_id) == token:
            self.runner._start_cancels[session.robot_id] = token[1] + 1
        task = self._tasks.get(session.session_id)
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            await asyncio.wait_for(self.robot_port.stop_return(session, context), 1.0)
        except Exception as exc:
            failure = failure or exc
        finally:
            try:
                view = self.runner.view(context['plan_id'])
                if (view is not None and view['robot_id'] == session.robot_id
                        and view['state'] in ('started', 'running', 'link_wait')):
                    await self.runner.cancel(context['plan_id'], self.principal_id, reason='charge_return_hold')
            except Exception as exc:
                failure = failure or exc
            try:
                job = self.runner.lease.jobs.get(session.robot_id)
                if job is not None and job.view['lease']['lease_id'] == context['lease_id']:
                    self.runner.release_job(session.robot_id, session.session_id)
            except Exception as exc:
                failure = failure or exc
            finally:
                await self.runner.lease.delete(session.robot_id, context['lease_id'])
        try:
            stored = await asyncio.to_thread(self.store.return_context, session.session_id)
            if stored is not None and stored['phase'] not in ('FINISHED', 'UNKNOWN'):
                await asyncio.to_thread(self.store.return_phase, session.session_id,
                                        expected=stored['phase'], next_phase='UNKNOWN')
        except Exception as exc:
            failure = failure or exc
        if failure is not None:
            raise failure
