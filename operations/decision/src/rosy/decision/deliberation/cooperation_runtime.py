"""D-913 bounded independent reviews, compatible with the Fleet advisory journal."""
import asyncio
from dataclasses import asdict
import hashlib
import json
import time

from . import Supervisor, canonical
from .cooperation import CooperationProvider, ReviewRequest, cooperation_trigger
from .cooperation_schedule import ExecutionEnvironment, ExecutionMeasurements, number, select_mode


class CooperationSupervisor(Supervisor):
    policy_id = 'conditional-cooperation-v1'

    def __init__(self, *, primary, primary_cost_usd, environment, measurements, admission,
                 mode='auto', reused=None, **kwargs):
        super().__init__(**kwargs)
        if (mode not in ('auto', 'sequential', 'parallel') or not callable(environment)
                or type(measurements) is not ExecutionMeasurements
                or any(not callable(getattr(admission, name, None)) for name in ('reserve', 'release'))
                or number(primary_cost_usd) > self.max_cost_usd):
            raise ValueError('EXPLICIT_COOPERATION_ADMISSION_REQUIRED')
        self.primary_json, self.primary_cost_usd = canonical(primary), primary_cost_usd
        self.environment, self.measurements, self.admission = environment, measurements, admission
        self.mode, self.reused = mode, reused

    def evaluation_key(self, problem, providers):
        return hashlib.sha256(canonical({'policy': self.policy_id, 'input_hash': problem.digest,
            'mode': self.mode, 'measurements': asdict(self.measurements), 'primary': self.primary_json,
            'primary_cost_usd': self.primary_cost_usd, 'timeout_s': self.timeout_s,
            'max_cost_usd': self.max_cost_usd, 'profiles': [p.profile_key for p in providers]}).encode()).hexdigest()

    async def run(self, problem, providers, *, current, record=None):
        result = dict(state='HOLD', reason='UNCONFIGURED', choice=None, calls=0, total_calls=1,
            known_cost_usd=self.primary_cost_usd, cost_usd=self.primary_cost_usd,
            cost_complete=True, unknown_cost_calls=0, opinions=[], policy_id=self.policy_id,
            input_hash=problem.digest, requested_mode=self.mode, effective_mode='hold',
            action_admissible=False, reserved_usd=0.0, reused=False)
        def finish(reason, state='HOLD', choice=None):
            return {**result, 'reason': reason, 'state': state, 'choice': choice,
                'cost_complete': result['unknown_cost_calls'] == 0,
                'cost_usd': result['known_cost_usd'] if result['unknown_cost_calls'] == 0 else None}
        def fresh():
            try:
                return current() is True and 0 <= self.clock() - problem.observed_at < 3
            except Exception:
                return False
        if not fresh():
            return finish('STALE_OR_CHANGED')
        if problem.necessity == 'DO_NOT_INTERVENE':
            result.update(total_calls=0, known_cost_usd=0)
            return finish('NORMAL', 'NOT_NEEDED')
        try:
            trigger = cooperation_trigger(problem, json.loads(self.primary_json))
            if trigger is None:
                return finish('COOPERATION_NOT_NEEDED')
            if trigger != 'baseline_disagreement':
                return finish('REOBSERVATION_OR_DEPENDENT_REVIEW_REQUIRED')
            if (len(providers) != 2 or any(type(p) is not CooperationProvider for p in providers)
                    or tuple(p.profile.role for p in providers) != ('primary', 'reviewer')
                    or len({p.profile_id for p in providers}) != 2):
                return finish('PROFILES_REQUIRED')
            requests = tuple(ReviewRequest(problem, role, trigger) for role in ('proposal', 'critique'))
            keys = tuple(p.profile_key for p in providers)
            if self.measurements.cost_caps != tuple(p.profile.max_cost_usd for p in providers):
                return finish('COST_PROFILE_CHANGED')
        except (ValueError, TypeError, KeyError, AttributeError):
            return finish('INVALID_REVIEW_CONTEXT')
        key = (problem.subject_id, problem.case_id)
        if key in self._active or len(self._active) >= self.max_active:
            return finish('BUSY')
        self._active.add(key)
        started = time.monotonic()
        deadline = min(self.timeout_s, 3 - (self.clock() - problem.observed_at))
        tasks, pending_ids = [], {}
        receipt_by_role = {}
        async def save(reason):
            if record is not None:
                await record(finish(reason, 'RUNNING'))
        def remaining():
            return max(0, deadline - (time.monotonic() - started))
        def unchanged():
            return fresh() and tuple(p.profile_key for p in providers) == keys and remaining() > 0
        async def invoke(index, token=None):
            provider, request = providers[index], requests[index]
            owned = token is None
            if owned:
                token = await self.admission.reserve((keys[index],), plan.environment.revision)
            if token is None:
                raise ValueError('RESOURCE_NOT_ADMITTED')
            confirmed = True
            try:
                if not unchanged():
                    raise ValueError('STALE_OR_CHANGED')
                call_id = provider.call_id(request)
                pending_ids[index] = call_id
                result['calls'] += 1
                result['total_calls'] += 1
                result['unknown_cost_calls'] += 1
                await save('CALL_RESERVED')
                if not unchanged():
                    pending_ids.pop(index)
                    result['unknown_cost_calls'] -= 1
                    raise ValueError('STALE_OR_CHANGED')
                confirmed = False
                receipt = await provider(request, min(remaining(), provider.profile.timeout_s),
                                         budget_usd=self.measurements.cost_caps[index])
                checked = receipt.validate(request, provider)
                pending_ids.pop(index)
                confirmed = True
                result['unknown_cost_calls'] -= 1
                result['known_cost_usd'] += receipt.cost_usd
                receipt_by_role[index] = checked
                result['opinions'].append({'role': request.role, 'profile_key': keys[index],
                    'request_hash': request.digest, 'call_id': receipt.call_id, **checked})
                await save('OPINION_RECORDED')
                if not unchanged():
                    raise ValueError('STALE_OR_CHANGED')
                if checked['objections']:
                    raise ValueError('UNRESOLVED_OBJECTION')
            finally:
                if not confirmed:
                    try:
                        async with asyncio.timeout(0.2):
                            confirmed = await provider.cancel(provider.call_id(request))
                    except Exception:
                        confirmed = False
                if owned and confirmed:
                    if await self.admission.release(token) is not True:
                        raise ValueError('RESOURCE_RELEASE_UNKNOWN')
        try:
            async with asyncio.timeout(deadline):
                environment = self.environment()
                plan = select_mode(requested_mode=self.mode, environment=environment, measurements=self.measurements,
                    profile_keys=keys, input_hash=problem.digest, now=self.clock(), remaining_s=remaining(),
                    remaining_usd=self.max_cost_usd - self.primary_cost_usd)
                result.update(decision_hash=plan.decision_hash, selection_reason=plan.reason,
                    effective_mode=plan.mode, environment_revision=environment.revision,
                    measurement_revision=self.measurements.revision)
                if plan.mode == 'hold':
                    return finish(plan.reason)
                indices = [0, 1]
                if self.reused is not None:
                    from .cooperation import ReviewReceipt
                    if type(self.reused) is not ReviewReceipt:
                        raise ValueError('INVALID_REUSE')
                    checked = self.reused.validate(requests[0], providers[0])
                    if checked['objections'] or self.reused.cost_usd != self.primary_cost_usd:
                        raise ValueError('INVALID_REUSE')
                    receipt_by_role[0] = checked
                    indices = [1]
                    result.update(reused=True, effective_mode='sequential')
                result['reserved_usd'] = sum(self.measurements.cost_caps[i] for i in indices)
                await save('BUDGET_RESERVED')
                if not unchanged():
                    return finish('STALE_OR_CHANGED')
                token = None
                if result['effective_mode'] == 'parallel':
                    token = await self.admission.reserve(keys, environment.revision)
                    if token is None:
                        if self.mode != 'auto':
                            return finish('RESOURCE_NOT_ADMITTED')
                        plan = select_mode(requested_mode='sequential', environment=self.environment(),
                            measurements=self.measurements, profile_keys=keys, input_hash=problem.digest,
                            now=self.clock(), remaining_s=remaining(),
                            remaining_usd=self.max_cost_usd - self.primary_cost_usd)
                        result.update(effective_mode=plan.mode, decision_hash=plan.decision_hash,
                                      selection_reason='PARALLEL_RESERVATION_REFUSED')
                        if plan.mode == 'hold':
                            return finish('RESOURCE_NOT_ADMITTED')
                if token is not None:
                    try:
                        tasks = [asyncio.create_task(invoke(i, token)) for i in indices]
                        await asyncio.gather(*tasks)
                    finally:
                        for task in tasks:
                            if not task.done(): task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        if not pending_ids:
                            if await self.admission.release(token) is not True:
                                raise ValueError('RESOURCE_RELEASE_UNKNOWN')
                else:
                    for i in indices:
                        await invoke(i)
                if not unchanged():
                    return finish('STALE_OR_CHANGED')
                choices = {entry['choice'] for entry in receipt_by_role.values()}
                if len(receipt_by_role) != 2 or len(choices) != 1:
                    return finish('CONFLICT')
                return finish('INDEPENDENT_OPINIONS_ONLY', 'CANDIDATE', choices.pop())
        except TimeoutError:
            return finish('TIMEOUT')
        except (ValueError, TypeError, KeyError, AttributeError):
            return finish('INVALID_OR_CHANGED_REVIEW')
        except Exception:
            return finish('PROVIDER_UNKNOWN')
        finally:
            self._active.discard(key)
