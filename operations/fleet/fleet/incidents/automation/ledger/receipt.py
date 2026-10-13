"""Bounded validated judgment evidence, never a truth label or dispatch authority."""
from dataclasses import asdict, dataclass
import hashlib
import json

from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.judgment import Judgment, judgment
from rosy.decision.deliberation.profiles import BoundProfile, ModelProfile, incident_profiles
from rosy.decision.deliberation.contracts.billing import CostEvidence
from .contract import CaseScope, micros


@dataclass(frozen=True)
class ModelReceipt:
    payload_json: str

    def __post_init__(self):
        if type(self.payload_json) is not str or len(self.payload_json.encode()) > 16384:
            raise ValueError('MODEL_RECEIPT_LIMIT')


def _checked(scope, receipt):
    if type(scope) is not CaseScope or type(receipt) is not ModelReceipt:
        raise ValueError('TYPED_MODEL_RECEIPT_REQUIRED')
    raw = json.loads(receipt.payload_json)
    fields = {'schema', 'profiles', 'role', 'problem', 'judgment'}
    single = type(raw) is dict and raw.get('schema') == 'rosy.incident.model_receipt/3'
    versioned = type(raw) is dict and (raw.get('schema') == 'rosy.incident.model_receipt/2' or single and 'cost_evidence' in raw)
    if (type(raw) is not dict or set(raw) != fields | ({'cost_evidence'} if versioned else set())
            or raw['schema'] not in {'rosy.incident.model_receipt/1', 'rosy.incident.model_receipt/2', 'rosy.incident.model_receipt/3'} or canonical(raw) != receipt.payload_json
            or type(raw['profiles']) is not list or len(raw['profiles']) != (1 if single else 2)):
        raise ValueError('INVALID_MODEL_RECEIPT_FIELDS')
    profiles = incident_profiles(tuple(ModelProfile(**value) for value in raw['profiles']))
    if hashlib.sha256(canonical([asdict(p) for p in profiles]).encode()).hexdigest() != scope.profile_sha256:
        raise ValueError('MODEL_RECEIPT_MANIFEST_CHANGED')
    selected = next((p for p in profiles if p.role == raw['role']), None)
    p = Problem(**raw['problem'])
    if (selected is None or (p.subject_id, p.case_id) != (scope.subject_id, scope.case_id)
            or p.domain not in selected.domains or 'text' not in selected.modalities
            or canonical(asdict(p)) != canonical(raw['problem'])):
        raise ValueError('MODEL_RECEIPT_CASE_OR_ROLE_CHANGED')
    checked = judgment(p, BoundProfile(selected, p.digest), raw['judgment'])
    if canonical(checked.payload) != canonical(raw['judgment']):
        raise ValueError('MODEL_RECEIPT_JUDGMENT_CHANGED')
    if versioned:
        evidence = CostEvidence(canonical(raw['cost_evidence']))
        evidence.validate(p, BoundProfile(selected, p.digest), checked, evidence.payload['marginal_cash_usd'])
    return raw, p, selected


def model_receipt(scope, problem, bound, checked, *, profiles, cost_evidence=None):
    """Build only from the trusted input, frozen pair and semantically checked output."""
    if (type(problem) is not Problem or type(bound) is not BoundProfile or type(checked) is not Judgment
            or type(profiles) is not tuple or any(type(p) is not ModelProfile for p in profiles)
            or bound.profile not in profiles):
        raise ValueError('CHECKED_MODEL_RECEIPT_REQUIRED')
    bound.validate(problem)
    verified = judgment(problem, bound, checked.payload)
    if verified != checked:
        raise ValueError('FORGED_CHECKED_JUDGMENT')
    raw = dict(schema='rosy.incident.model_receipt/3' if len(profiles) == 1 else 'rosy.incident.model_receipt/1',
        profiles=[asdict(p) for p in profiles], role=bound.profile.role,
        problem=asdict(problem), judgment=verified.payload)
    if cost_evidence is not None:
        if type(cost_evidence) is not CostEvidence: raise ValueError('TYPED_COST_EVIDENCE_REQUIRED')
        raw.update(schema=raw['schema'] if len(profiles) == 1 else 'rosy.incident.model_receipt/2', cost_evidence=cost_evidence.payload)
    receipt = ModelReceipt(canonical(raw))
    _checked(scope, receipt)
    return receipt


def checked_receipt(scope, attempt, receipt):
    """Revalidate historical evidence against its durable attempt, including known stale results."""
    try:
        raw, problem, profile = _checked(scope, receipt)
        if (attempt['kind'] != 'model' or attempt['role'] != profile.role
                or attempt['input_hash'] != problem.digest
                or attempt['observation_revision'] != problem.generation
                or attempt['state'] not in {'COMPLETED', 'REJECTED'}
                or type(attempt['actual_micros']) is not int or attempt['actual_micros'] < 0):
            raise ValueError('MODEL_RECEIPT_ATTEMPT_CHANGED')
        if 'cost_evidence' in raw and micros(raw['cost_evidence']['marginal_cash_usd']) != attempt['actual_micros']:
            raise ValueError('MODEL_COST_EVIDENCE_AMOUNT_CHANGED')
        return raw
    except (TypeError, KeyError, StopIteration, json.JSONDecodeError, RecursionError, OverflowError) as error:
        raise ValueError('INVALID_MODEL_RECEIPT') from error
