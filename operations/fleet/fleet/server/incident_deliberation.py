"""D-672 trusted line judgment to advisory-only Decision input."""
from rosy.decision.deliberation import Problem
from rosy_situation.assessment import Assessment
from rosy_situation.snapshot_assessment import POLICY


async def run_line_judgment(assessment, journal, supervisor, providers, *, current):
    def stop(reason, state='HOLD'):
        return dict(state=state, reason=reason, choice=None, calls=0, action_admissible=False)
    if not isinstance(assessment, Assessment):
        return stop('JUDGMENT_UNAVAILABLE')
    request = assessment.request
    def fresh():
        try:
            latest = current()
            now = supervisor.clock()
            return (isinstance(latest, Assessment) and latest.request == request
                and latest.necessity == assessment.necessity
                and latest.policy_revision == assessment.policy_revision == POLICY.revision
                and assessment.applies_to(request, now=now, policy_revision=POLICY.revision)
                and latest.applies_to(request, now=now, policy_revision=POLICY.revision))
        except Exception:
            return False
    if not fresh():
        return stop('STALE_OR_INSUFFICIENT_JUDGMENT')
    if assessment.necessity == 'DO_NOT_INTERVENE':
        return stop(assessment.reason, 'NOT_NEEDED')
    if (assessment.necessity != 'INTERVENE' or request.condition != 'blocked'
            or request.owner != 'core' or not request.case_id
            or not request.evidence or any(e.source != 'core_state' for e in request.evidence)):
        return stop('UNSUPPORTED_JUDGMENT')
    problem = Problem(request.subject_id, request.case_id, request.revision, 'line_follow',
        min(e.observed_at for e in request.evidence), tuple(dict.fromkeys(e.reference for e in request.evidence)),
        ('reobserve', 'human'), assessment.necessity, facts_json='{"state":"blocked"}')
    return await journal.run(problem, supervisor, providers, current=fresh)
