"""Bounded model opinions produce advisory choices, never execution authority."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass

CHOICES = frozenset({'reobserve', 'human', 'map_correction', 'object_reacquire', 'back_and_retry'})
OBJECTIONS = frozenset({'unsafe', 'insufficient_evidence', 'conflict'})


def identifier(value):
    if (type(value) is not str or not value or value != value.strip() or len(value) > 128
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('invalid deliberation identifier')
    return value


def canonical(value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(data.encode()) > 16384:
        raise ValueError('deliberation payload exceeds budget')
    return data


@dataclass(frozen=True)
class Problem:
    subject_id: str
    case_id: str
    generation: str
    domain: str
    observed_at: float
    evidence_ids: tuple[str, ...]
    choices: tuple[str, ...]
    necessity: str
    goal: str = 'inspect'
    facts_json: str = '{"state":"unknown"}'
    fleet_choice: str | None = None

    def __post_init__(self):
        for value in (self.subject_id, self.case_id, self.generation):
            identifier(value)
        identifier(self.goal)
        if (self.domain not in {'door', 'arm_target', 'line_follow', 'fleet_status'}
                or self.necessity not in ({'READ_ONLY_QUERY'} if self.domain == 'fleet_status'
                                        else {'INTERVENE', 'DO_NOT_INTERVENE', 'ABSTAIN'})):
            raise ValueError('invalid domain or necessity')
        if type(self.observed_at) not in (int, float) or not math.isfinite(self.observed_at):
            raise ValueError('invalid observation time')
        facts = json.loads(self.facts_json)
        recovery_choice = type(self.choices) in (tuple, list) and 'back_and_retry' in self.choices
        if type(facts) is dict and 'recovery' in facts:
            from .contracts.recovery import recovery_context
            if (self.domain != 'line_follow' or self.necessity != 'INTERVENE'
                    or set(facts) != {'state', 'recovery'} or facts['state'] != 'blocked'
                    or not recovery_choice):
                raise ValueError('INVALID_RECOVERY_PROBLEM')
            recovery_context(facts['recovery'])
        valid = ({'state': {'unknown', 'offline', 'online', 'mixed', 'empty'}} if self.domain == 'fleet_status' else
                 {'state': {'unknown', 'blocked', 'normal'}} if self.domain == 'line_follow' else
                 {'state': {'unknown', 'open', 'closed'}, 'door_state': {'unknown', 'open', 'closed'}}
                 if self.domain == 'door' else {'state': {'unknown', 'present', 'missing'},
                                              'target_state': {'unknown', 'present', 'missing'}})
        if (type(facts) is not dict or not facts or any(key not in valid or type(value) is not str
                or value not in valid[key] for key, value in facts.items() if key != 'recovery')):
            raise ValueError('invalid approved observation facts')
        if recovery_choice and (self.domain != 'line_follow' or 'recovery' not in facts):
            raise ValueError('INVALID_RECOVERY_PROBLEM')
        object.__setattr__(self, 'facts_json', canonical(facts))
        for name, allowed in (('evidence_ids', None), ('choices', CHOICES)):
            values = getattr(self, name)
            if (type(values) not in (tuple, list) or not 1 <= len(values) <= 16
                    or len(set(values)) != len(values)):
                raise ValueError('invalid bounded input collection')
            for value in values:
                identifier(value)
                if allowed is not None and value not in allowed:
                    raise ValueError('unsupported advisory choice')
            object.__setattr__(self, name, tuple(values))
        if self.fleet_choice is not None and (type(self.fleet_choice) is not str
                or self.fleet_choice not in self.choices):
            raise ValueError('invalid Fleet advisory baseline')
        canonical(asdict(self))

    @property
    def digest(self):
        fields = asdict(self)
        if self.fleet_choice is None:
            fields.pop('fleet_choice')
        return hashlib.sha256(canonical(fields).encode()).hexdigest()


def opinion(problem, payload):
    canonical(payload)
    keys = {'subject_id', 'case_id', 'generation', 'input_hash', 'choice', 'evidence_ids', 'objections'}
    if type(payload) is not dict or set(payload) != keys:
        raise ValueError('invalid opinion fields')
    for key in ('subject_id', 'case_id', 'generation'):
        if payload[key] != getattr(problem, key):
            raise ValueError('opinion belongs to another scope')
    refs, objections = payload['evidence_ids'], payload['objections']
    if (payload['input_hash'] != problem.digest or payload['choice'] not in problem.choices
            or type(refs) is not list or not refs or len(refs) > 16
            or any(type(ref) is not str or ref not in problem.evidence_ids for ref in refs)
            or type(objections) is not list or len(objections) > 3
            or any(type(item) is not str or item not in OBJECTIONS for item in objections)):
        raise ValueError('invalid opinion binding or evidence')
    return json.loads(canonical(payload))


class Supervisor:
    def __init__(self, *, clock=time.time, timeout_s=30.0, max_cost_usd=0.30, max_active=2):
        if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 30
                or type(max_cost_usd) not in (int, float) or not math.isfinite(max_cost_usd)
                or not 0 < max_cost_usd <= 10 or type(max_active) is not int or not 1 <= max_active <= 8):
            raise ValueError('invalid finite deliberation budget')
        self.clock, self.timeout_s, self.max_cost_usd, self.max_active = clock, timeout_s, max_cost_usd, max_active
        self._active = set()

    async def run(self, problem, providers, *, current, record=None):
        key = (problem.subject_id, problem.case_id)
        result = dict(state='HOLD', reason='UNCONFIGURED', choice=None, calls=0,
                      cost_usd=0.0, known_cost_usd=0.0, unknown_cost_calls=0,
                      opinions=[], input_hash=problem.digest, action_admissible=False)
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
        try:
            configured = len(providers) == 2 and len({identifier(p.profile_id) for p in providers}) == 2
        except (ValueError, TypeError, AttributeError):
            configured = False
        if not configured:
            return finish('PROFILES_REQUIRED')
        if key in self._active or len(self._active) >= self.max_active:
            return finish('BUSY')
        self._active.add(key)
        start = time.monotonic()
        try:
            async with asyncio.timeout(self.timeout_s):
                for index in range(3):
                    if not fresh():
                        return finish('STALE_OR_CHANGED')
                    remaining = self.timeout_s - (time.monotonic() - start)
                    result['calls'] += 1
                    result['unknown_cost_calls'] += 1
                    prior = () if index < 2 else tuple(json.loads(canonical(result['opinions'])))
                    payload, cost = await providers[index % 2](problem, prior, remaining,
                        budget_usd=self.max_cost_usd - result['known_cost_usd'])
                    if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
                        return finish('COST_UNKNOWN')
                    result['known_cost_usd'] += cost
                    result['unknown_cost_calls'] -= 1
                    if result['known_cost_usd'] > self.max_cost_usd:
                        return finish('COST_EXCEEDED')
                    checked = opinion(problem, payload)
                    result['opinions'].append({'profile_id': providers[index % 2].profile_id, **checked})
                    if record is not None:
                        await record(json.loads(canonical(finish('OPINION_RECORDED', 'RUNNING'))))
                    if checked['objections']:
                        return finish('UNRESOLVED_OBJECTION')
                    if index == 1 and checked['choice'] != result['opinions'][0]['choice']:
                        return finish('CONFLICT')
                if not fresh():
                    return finish('STALE_OR_CHANGED')
                if len({item['choice'] for item in result['opinions']}) != 1:
                    return finish('CONFLICT')
                return finish('BOUNDED_OPINIONS_ONLY', 'CANDIDATE', checked['choice'])
        except TimeoutError:
            return finish('TIMEOUT')
        except (ValueError, TypeError, KeyError):
            return finish('INVALID_REPLY')
        except Exception:
            return finish('PROVIDER_UNKNOWN')
        finally:
            self._active.discard(key)


from .conditional import ConditionalReview
