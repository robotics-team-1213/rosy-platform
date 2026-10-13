"""Immutable incident-budget inputs and bounded receipts; no dispatch authority."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
import re

from rosy.decision.deliberation import CHOICES, canonical, identifier


def sha256(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('FULL_SHA256_REQUIRED')
    return value


def micros(value, *, ceiling=True):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1_000_000:
        raise ValueError('INVALID_COST')
    return int((Decimal(str(value)) * 1_000_000).to_integral_value(
        rounding=ROUND_CEILING if ceiling else ROUND_FLOOR))


@dataclass(frozen=True)
class CaseScope:
    subject_id: str
    case_id: str
    owner_id: str
    profile_sha256: str
    policy_revision: str

    def __post_init__(self):
        for value in (self.subject_id, self.case_id, self.owner_id, self.policy_revision):
            identifier(value)
        sha256(self.profile_sha256)


@dataclass(frozen=True)
class CaseBudget:
    started_at: float
    deadline: float
    max_calls: int
    max_observations: int
    max_cost_usd: float
    role_limits: tuple[tuple[str, int], ...] = ()

    def __post_init__(self):
        if (any(type(value) not in (int, float) or not math.isfinite(value)
                for value in (self.started_at, self.deadline))
                or not 0 < self.deadline - self.started_at <= 120
                or any(type(value) is not int or not 0 <= value <= 8
                       for value in (self.max_calls, self.max_observations))
                or type(self.max_cost_usd) not in (int, float) or not 0 <= self.max_cost_usd <= 10):
            raise ValueError('INVALID_CASE_BUDGET')
        micros(self.max_cost_usd, ceiling=False)
        if (type(self.role_limits) not in (tuple, list) or len(self.role_limits) > 2
                or any(type(item) not in (tuple, list) or len(item) != 2
                       or item[0] not in ('primary', 'reviewer') or type(item[1]) is not int
                       or not 1 <= item[1] <= 8 for item in self.role_limits)):
            raise ValueError('INVALID_CASE_ROLE_LIMITS')
        limits = tuple(tuple(item) for item in self.role_limits)
        if len({item[0] for item in limits}) != len(limits): raise ValueError('DUPLICATE_ROLE_LIMIT')
        object.__setattr__(self, 'role_limits', limits)


def summary_json(value):
    allowed = {'reason', 'verdict', 'choice', 'receipt_sha256', 'observation_revision'}
    if type(value) is not dict or set(value) - allowed:
        raise ValueError('INVALID_RECEIPT_SUMMARY')
    if 'reason' in value and (type(value['reason']) is not str or re.fullmatch('[A-Z0-9_]{1,64}', value['reason']) is None):
        raise ValueError('INVALID_REASON_CODE')
    if 'verdict' in value and value['verdict'] not in {'do_not_intervene', 'reobserve', 'candidate', 'abstain'}:
        raise ValueError('INVALID_SUMMARY_VERDICT')
    if 'choice' in value and value['choice'] is not None and value['choice'] not in CHOICES:
        raise ValueError('INVALID_SUMMARY_CHOICE')
    if 'receipt_sha256' in value:
        sha256(value['receipt_sha256'])
    if 'observation_revision' in value:
        identifier(value['observation_revision'])
    raw = canonical(value)
    if len(raw.encode()) > 1024:
        raise ValueError('SUMMARY_LIMIT_EXCEEDED')
    return raw
