"""D-652 pure necessity assessment; recommendations never grant execution authority."""

from dataclasses import dataclass
import math


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def identity(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


@dataclass(frozen=True)
class EvidenceRef:
    subject_id: str
    source: str
    reference: str
    observed_at: float | None
    case_id: str | None = None


@dataclass(frozen=True)
class AssessmentInput:
    subject_id: str
    case_id: str | None
    revision: str
    owner: str | None
    condition: str
    evidence: tuple[EvidenceRef, ...]
    since: float | None = None
    until: float | None = None
    conflicted: bool = False


@dataclass(frozen=True)
class AssessmentPolicy:
    revision: str
    max_age_s: float
    confirm_s: float
    ttl_s: float

    def __post_init__(self):
        if (not identity(self.revision)
                or any(not finite(v) for v in (self.max_age_s, self.confirm_s, self.ttl_s))
                or self.max_age_s <= 0 or self.confirm_s < 0 or self.ttl_s <= 0):
            raise ValueError('invalid assessment policy')


@dataclass(frozen=True)
class Assessment:
    necessity: str
    reason: str
    request: AssessmentInput
    policy_revision: str
    evaluated_at: float
    valid_until: float

    @property
    def revision(self):
        return self.request.revision

    def applies_to(self, request, *, now, policy_revision):
        return (self.necessity != 'ABSTAIN' and finite(now)
                and self.evaluated_at <= now < self.valid_until and self.request == request
                and self.policy_revision == policy_revision)


def assess(request: AssessmentInput, *, now: float, policy: AssessmentPolicy) -> Assessment:
    expires = now + policy.ttl_s if finite(now) else 0.0

    def result(necessity, reason):
        return Assessment(necessity, reason, request, policy.revision,
                          now, now if necessity == 'ABSTAIN' and finite(now) else expires)

    def abstain(reason):
        return result('ABSTAIN', reason)

    if not finite(now) or not finite(expires):
        return abstain('evaluation_time_invalid')
    if not identity(request.subject_id) or (request.case_id is not None and not identity(request.case_id)):
        return abstain('identity_invalid')
    if not identity(request.revision):
        return abstain('revision_missing')
    if not identity(request.owner):
        return abstain('owner_unknown')
    if type(request.conflicted) is not bool or request.conflicted:
        return abstain('evidence_conflict')
    if not isinstance(request.evidence, tuple) or not request.evidence:
        return abstain('evidence_missing')
    for evidence in request.evidence:
        if not isinstance(evidence, EvidenceRef) or not identity(evidence.source) or not identity(evidence.reference):
            return abstain('evidence_invalid')
        if (evidence.subject_id, evidence.case_id) != (request.subject_id, request.case_id):
            return abstain('evidence_binding_mismatch')
        if not finite(evidence.observed_at):
            return abstain('evidence_time_invalid')
        if evidence.observed_at > now:
            return abstain('evidence_future')
        expires = min(expires, evidence.observed_at + policy.max_age_s)
        if expires <= now:
            return abstain('evidence_stale')
    if request.since is not None and (not finite(request.since) or request.since > now):
        return abstain('duration_invalid')
    if request.until is not None and not finite(request.until):
        return abstain('deadline_invalid')
    condition = request.condition
    if condition in ('normal', 'progressing', 'resolved'):
        if condition == 'resolved' and request.case_id is None:
            return abstain('resolution_binding_missing')
        return result('DO_NOT_INTERVENE', condition)
    if condition in ('safe_wait', 'handling'):
        if request.until is None:
            return abstain('deadline_unknown')
        if request.until <= now:
            return result('INTERVENE', 'wait_expired' if condition == 'safe_wait' else 'handling_expired')
        expires = min(expires, request.until)
        return result('DO_NOT_INTERVENE', condition)
    if condition == 'blocked':
        if request.since is None:
            return abstain('duration_unknown')
        if now - request.since < policy.confirm_s:
            expires = min(expires, request.since + policy.confirm_s)
            return result('DO_NOT_INTERVENE', 'confirmation_pending')
        return result('INTERVENE', 'persistent_blockage')
    if condition in ('deadline_exceeded', 'budget_exhausted', 'hazard', 'owner_lost'):
        return result('INTERVENE', condition)
    return abstain('condition_unknown')
