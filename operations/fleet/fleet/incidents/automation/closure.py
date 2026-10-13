"""Trusted observation closure, distinct from action success and model declarations."""
from dataclasses import dataclass
from datetime import datetime

from rosy_situation.assessment import Assessment
from rosy_situation.snapshot_assessment import POLICY
from .contract import CaseScope


@dataclass(frozen=True)
class ObservedClosure:
    scope: CaseScope
    requested_at: float
    observed_at: float
    closed_at: float
    normal_revision: str
    action_credit: str


def observe_closure(scope, *, requested_at, board, snapshot, human_owned, now):
    if type(scope) is not CaseScope or human_owned(scope.subject_id, scope.case_id) is not False:
        raise ValueError('CLOSURE_SCOPE_UNAVAILABLE')
    current = board.intervention_assessment(scope.subject_id)
    if (not isinstance(current, Assessment) or current.necessity != 'DO_NOT_INTERVENE'
            or current.request.condition != 'normal' or current.request.owner != scope.owner_id
            or current.request.subject_id != scope.subject_id or current.request.case_id is not None
            or not current.applies_to(current.request, now=now, policy_revision=scope.policy_revision)
            or current.policy_revision != POLICY.revision
            or not current.request.evidence or any(e.source != 'core_state' for e in current.request.evidence)):
        raise ValueError('NORMAL_READBACK_UNAVAILABLE')
    rows = [row for row in snapshot['robots'] if row.get('robot_id') == scope.subject_id]
    if len(rows) != 1 or rows[0].get('online') is not True:
        raise ValueError('CLOSURE_SUBJECT_UNAVAILABLE')
    state = rows[0].get('state') or {}
    if current.request.revision != f"core:{state.get('seq')}:{state.get('timestamp')}":
        raise ValueError('CLOSURE_REVISION_MISMATCH')
    episodes = [e for e in board.episodes(1000) if (e['robot_id'], e['stuck_id']) == (scope.subject_id, scope.case_id)]
    if len(episodes) != 1 or episodes[0]['close_reason'] != 'cleared' or not episodes[0]['closed_at']:
        raise ValueError('ORIGINAL_CLEARED_TRANSITION_REQUIRED')
    closed_at = datetime.fromisoformat(episodes[0]['closed_at']).timestamp()
    observed_at = min(e.observed_at for e in current.request.evidence)
    if not requested_at < observed_at <= now or not requested_at < closed_at <= now:
        raise ValueError('LATER_CLOSURE_REQUIRED')
    report = board.reports(1, robot_id=scope.subject_id, stuck_id=scope.case_id)
    credit = 'UNVERIFIED' if report and report[0]['closure']['action_credit'] == 'UNVERIFIED' else 'NONE'
    return ObservedClosure(scope, requested_at, observed_at, closed_at, current.request.revision, credit)
