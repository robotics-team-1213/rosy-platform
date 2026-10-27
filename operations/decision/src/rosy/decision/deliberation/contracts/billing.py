"""Immutable trusted call cost evidence; observed charges remain separate from policy cost."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re

from .. import canonical, identifier
from .judgment import Judgment, judgment
from .profiles import BoundProfile


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


def usd(value):
    if type(value) not in (int, float) or not 0 <= value <= 1_000_000 or not math.isfinite(value):
        raise ValueError('INVALID_COST_EVIDENCE_AMOUNT')
    return value


class RejectedJudgment(ValueError):
    """Validated transport cost of a rejected call, never a judgment or independently certified bill."""
    def __init__(self, bound, cost_usd, unsafe=False):
        if type(bound) is not BoundProfile or type(unsafe) is not bool:
            raise ValueError('INVALID_REJECTED_CALL_CONTEXT')
        self.bound, self.cost_usd, self.unsafe = bound, usd(cost_usd), unsafe
        super().__init__('MODEL_RESULT_REJECTED')


@dataclass(frozen=True)
class CostEvidence:
    payload_json: str

    def __post_init__(self):
        if type(self.payload_json) is not str or len(self.payload_json.encode()) > 2048:
            raise ValueError('COST_EVIDENCE_LIMIT')
        p = json.loads(self.payload_json)
        fields = {'schema', 'input_hash', 'job_sha256', 'profile_sha256', 'judgment_sha256', 'basis',
                  'policy_revision', 'evidence_sha256', 'credential_sha256', 'provider_request_id',
                  'provider_response_id', 'usage', 'marginal_cash_usd', 'observed_usd_charge'}
        if type(p) is not dict or set(p) != fields or p['schema'] != 'rosy.model.cost_evidence/1':
            raise ValueError('INVALID_COST_EVIDENCE_FIELDS')
        if canonical(p) != self.payload_json or p['basis'] not in {'included_plan', 'local_free', 'provider_reported'}:
            raise ValueError('INVALID_COST_EVIDENCE_BASIS')
        for key in ('input_hash', 'job_sha256', 'profile_sha256', 'judgment_sha256', 'evidence_sha256'):
            if type(p[key]) is not str or re.fullmatch('[0-9a-f]{64}', p[key]) is None:
                raise ValueError('INVALID_COST_EVIDENCE_HASH')
        identifier(p['policy_revision'])
        credential = p['credential_sha256']
        if credential is not None and (type(credential) is not str or re.fullmatch('[0-9a-f]{64}', credential) is None):
            raise ValueError('INVALID_COST_CREDENTIAL_BINDING')
        for key in ('provider_request_id', 'provider_response_id'):
            if p[key] is not None and (type(p[key]) is not str or re.fullmatch('[A-Za-z0-9_.:-]{1,128}', p[key]) is None):
                raise ValueError('INVALID_COST_PROVIDER_REFERENCE')
        if p['basis'] != 'local_free' and any(p[key] is None for key in ('credential_sha256', 'provider_request_id', 'provider_response_id')):
            raise ValueError('COST_PROVIDER_BINDING_REQUIRED')
        usd(p['marginal_cash_usd'])
        if p['observed_usd_charge'] is not None: usd(p['observed_usd_charge'])
        if p['basis'] in {'included_plan', 'local_free'} and p['marginal_cash_usd'] != 0:
            raise ValueError('INVALID_ZERO_MARGINAL_POLICY')
        usage = p['usage']
        if (type(usage) is not dict or not {'input_tokens', 'output_tokens', 'total_tokens'} <= set(usage)
                or set(usage) - {'input_tokens', 'output_tokens', 'total_tokens', 'reasoning_tokens'}
                or any(type(v) is not int or not 0 <= v <= 1_000_000 for v in usage.values())
                or usage['total_tokens'] != usage['input_tokens'] + usage['output_tokens']
                or usage.get('reasoning_tokens', 0) > usage['output_tokens']):
            raise ValueError('INVALID_COST_USAGE')

    @property
    def payload(self): return json.loads(self.payload_json)

    def validate(self, problem, bound, checked, cost, *, body=None):
        bound.validate(problem)
        p = self.payload
        if (type(checked) is not Judgment or judgment(problem, bound, checked.payload) != checked
                or p['input_hash'] != problem.digest or p['profile_sha256'] != digest(asdict(bound.profile))
                or p['judgment_sha256'] != digest(checked.payload) or p['marginal_cash_usd'] != usd(cost)
                or body is not None and p['job_sha256'] != digest(json.loads(body))):
            raise ValueError('COST_EVIDENCE_CALL_CHANGED')


@dataclass(frozen=True)
class CallResult:
    judgment: Judgment
    cost_usd: float
    cost_evidence: CostEvidence | None = None
    evidence_error: bool = False

    def __post_init__(self):
        usd(self.cost_usd)
        if (type(self.judgment) is not Judgment or type(self.evidence_error) is not bool
                or self.cost_evidence is not None and type(self.cost_evidence) is not CostEvidence
                or self.evidence_error and self.cost_evidence is not None):
            raise ValueError('INVALID_CALL_RESULT')

    def __len__(self): return 2
    def __iter__(self): return iter((self.judgment, self.cost_usd))
    def __getitem__(self, index): return (self.judgment, self.cost_usd)[index]


def call_cost_evidence(invocation, problem, bound, checked, cost):
    if type(invocation) is not CallResult: return None, False
    evidence = invocation.cost_evidence
    if evidence is not None:
        try: evidence.validate(problem, bound, checked, cost)
        except (ValueError, TypeError): return None, True
    return evidence, invocation.evidence_error
