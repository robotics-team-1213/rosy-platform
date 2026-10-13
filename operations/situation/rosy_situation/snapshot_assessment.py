"""Existing CORE line-follow state to D-652 shadow inputs, never inferred mission success."""

from datetime import datetime

from .assessment import AssessmentInput, AssessmentPolicy, EvidenceRef, assess, finite, identity

POLICY = AssessmentPolicy('line-follow-shadow-v1', 3.0, 0.0, 3.0)


def robot_input(row: dict, *, now: float, sampled_at: float, pending: dict | None = None):
    rid = row.get('robot_id')
    state = row.get('state') if isinstance(row.get('state'), dict) else {}
    line = state.get('line_follow') if isinstance(state.get('line_follow'), dict) else {}
    stuck = line.get('stuck')
    current_id = stuck.get('stuck_id') if isinstance(stuck, dict) else None
    pending_id = pending.get('stuck_id') if pending else None
    case = pending_id or current_id
    stamp, seq, age = state.get('timestamp'), state.get('seq'), row.get('state_age_s')
    revision = f'core:{seq}:{stamp}' if type(seq) is int and seq >= 0 and identity(stamp) else ''
    observed = None
    try:
        core_time = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if (core_time.tzinfo is not None and finite(age) and age >= 0
                and finite(sampled_at) and sampled_at <= now):
            observed = min(core_time.timestamp(), sampled_at - age)
            # A future device clock cannot be hidden by a fresh Fleet receipt.
            if core_time.timestamp() > now:
                observed = core_time.timestamp()
    except (AttributeError, ValueError, TypeError, OverflowError):
        pass
    condition = 'unknown'
    since = None
    if row.get('online') is True:
        if stuck is None and line.get('mode') == 'OFF':
            condition = 'normal'
        elif isinstance(stuck, dict) and identity(current_id):
            phase = stuck.get('phase')
            if phase in ('ASKING', 'WAITING_CONSOLE'):
                condition, since = 'blocked', observed
            elif phase in ('BACKING', 'SETTLING', 'TURNING', 'CRAWLING', 'YIELDED'):
                condition = 'handling'  # CORE has no bounded handling deadline in this snapshot.
    evidence = state.get('evidence') or {}
    channel = evidence.get('line_follow') if isinstance(evidence, dict) else None
    if channel is not None and (not isinstance(channel, dict) or channel.get('evidence') != 'fresh'):
        condition = 'unknown'
    return AssessmentInput(rid, case, revision, 'core', condition,
                           (EvidenceRef(rid, 'core_state', revision, observed, case_id=case),),
                           since=since, conflicted=bool(pending_id and pending_id != current_id))


def snapshot_assessments(snapshot: dict):
    now = snapshot['observed_at']
    sampled_at = snapshot.get('_state_requested_at', now)
    pending = {row.get('robot_id'): row for row in
               (snapshot.get('line_stuck') or {}).get('pending') or []}
    return {row['robot_id']: assess(robot_input(row, now=now, sampled_at=sampled_at,
                                               pending=pending.get(row['robot_id'])), now=now, policy=POLICY)
            for row in (snapshot.get('state') or {}).get('robots') or []}
