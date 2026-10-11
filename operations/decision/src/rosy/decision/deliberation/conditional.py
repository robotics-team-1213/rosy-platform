"""D-679 independent second review is conditional and cannot clear a HOLD."""
import asyncio
import json
import math
import time

from . import Supervisor, canonical, identifier, opinion


class ConditionalReview(Supervisor):
    policy_id = 'conditional-review-v1'

    async def run(self, problem, providers, *, current, record=None):
        key = (problem.subject_id, problem.case_id)
        result = dict(state='HOLD', reason='UNCONFIGURED', choice=None, calls=0,
            known_cost_usd=0.0, unknown_cost_calls=0, opinions=[], input_hash=problem.digest,
            action_admissible=False, policy_id=self.policy_id, review_trigger=None)
        def finish(reason, state='HOLD', choice=None):
            complete = result['unknown_cost_calls'] == 0
            return {**result, 'reason': reason, 'state': state, 'choice': choice,
                'cost_complete': complete, 'cost_usd': result['known_cost_usd'] if complete else None}
        def fresh():
            try:
                return current() is True and 0 <= self.clock() - problem.observed_at <= 3
            except Exception:
                return False
        if not fresh():
            return finish('STALE_OR_CHANGED')
        if problem.necessity == 'DO_NOT_INTERVENE':
            return finish('NORMAL', 'NOT_NEEDED')
        if problem.necessity != 'INTERVENE':
            return finish('INSUFFICIENT_JUDGMENT')
        try:
            configured = len(providers) == 2 and len({identifier(p.profile_id) for p in providers}) == 2
        except (ValueError, TypeError, AttributeError):
            configured = False
        if not configured:
            return finish('PROFILES_REQUIRED')
        if key in self._active or len(self._active) >= self.max_active:
            return finish('BUSY')
        self._active.add(key)
        started = time.monotonic()
        review_prior = ()
        try:
            async with asyncio.timeout(self.timeout_s):
                for index in range(2):
                    if not fresh():
                        return finish('STALE_OR_CHANGED')
                    budget = self.max_cost_usd - result['known_cost_usd']
                    if budget <= 0:
                        return finish('COST_EXCEEDED')
                    result['calls'] += 1
                    result['unknown_cost_calls'] += 1
                    payload, cost = await providers[index](problem, review_prior if index else (),
                        self.timeout_s - (time.monotonic() - started), budget_usd=budget)
                    if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
                        return finish('COST_UNKNOWN')
                    result['known_cost_usd'] += cost
                    result['unknown_cost_calls'] -= 1
                    if cost > budget:
                        return finish('COST_EXCEEDED')
                    if not fresh():
                        return finish('STALE_OR_CHANGED')
                    try:
                        checked = opinion(problem, payload)
                    except (ValueError, TypeError, KeyError):
                        if index:
                            return finish('INVALID_REPLY')
                        if (type(payload) is dict and type(payload.get('objections')) is list
                                and 'unsafe' in payload['objections']):
                            return finish('UNRESOLVED_OBJECTION')
                        result['review_trigger'] = 'INVALID_REPLY'
                        checked = None
                    if checked is not None:
                        result['opinions'].append({'profile_id': providers[index].profile_id, **checked})
                        if index == 0:
                            if 'unsafe' in checked['objections']:
                                return finish('UNRESOLVED_OBJECTION')
                            if checked['objections']:
                                result['review_trigger'] = ('insufficient_evidence'
                                    if 'insufficient_evidence' in checked['objections'] else 'conflict')
                            if problem.fleet_choice is not None and checked['choice'] != problem.fleet_choice:
                                result['review_trigger'] = 'fleet_qwen_disagreement'
                                review_prior = tuple(json.loads(canonical(result['opinions'])))
                    if record is not None:
                        await record(json.loads(canonical(finish('OPINION_RECORDED', 'RUNNING'))))
                    if not fresh():
                        return finish('STALE_OR_CHANGED')
                    if index:
                        return finish('SECONDARY_REVIEW_COMPLETED')
                    if checked is not None and result['review_trigger'] is None:
                        return finish('PRIMARY_OPINION_ONLY', 'CANDIDATE', checked['choice'])
            return finish('UNCONFIGURED')
        except TimeoutError:
            return finish('TIMEOUT')
        except (ValueError, TypeError, KeyError):
            return finish('INVALID_REPLY')
        except Exception:
            return finish('PROVIDER_UNKNOWN')
        finally:
            self._active.discard(key)
