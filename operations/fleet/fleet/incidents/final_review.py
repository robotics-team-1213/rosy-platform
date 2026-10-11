"""Bounded final-review receipts from the durable automatic case ledger."""
from dataclasses import asdict
import json
import math
import re

from rosy.decision.deliberation import canonical, identifier
from rosy_situation.snapshot_assessment import POLICY
from .automation.contract import CaseScope


def managed_case(connection, rid, sid):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_incident_v2_cases'").fetchone():
        return None
    return connection.execute('SELECT * FROM fleet_incident_v2_cases WHERE subject_id=? AND case_id=?', (rid, sid)).fetchone()


def final_current(connection, rid, sid, scope_json, now, *, receipt=None):
    case = managed_case(connection, rid, sid)
    if case is None or case['state'] != 'HOLD' or case['scope_json'] != scope_json:
        return False
    episode = connection.execute('SELECT closed_at FROM fleet_line_stuck_episodes WHERE robot_id=? AND stuck_id=?', (rid, sid)).fetchone()
    owner = connection.execute('SELECT 1 FROM fleet_incident_claims WHERE robot_id=? AND stuck_id=?', (rid, sid)).fetchone()
    if receipt is None:
        current = connection.execute('SELECT assessment FROM fleet_judgment_current WHERE robot_id=?', (rid,)).fetchone()
        receipt = json.loads(current['assessment']) if current else None
    if episode is None or episode['closed_at'] is not None or owner is not None or receipt is None:
        return False
    request = receipt['request']
    scope = json.loads(scope_json)
    expected_policy = POLICY.revision if case['reason'] == 'POLICY_CHANGED' else scope['policy_revision']
    bound = (request.get('subject_id') == rid and request.get('case_id') == sid
            and request.get('owner') == scope['owner_id'] == 'core'
            and receipt['policy_revision'] == expected_policy
            and receipt['necessity'] != 'DO_NOT_INTERVENE')
    if not bound:
        return False
    fresh = bool(request['evidence']) and all(type(item['observed_at']) in (int, float)
                and math.isfinite(item['observed_at']) and 0 <= now - item['observed_at'] < 3
                for item in request['evidence'])
    return True if fresh else None


def original_revision(connection, scope, revision):
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_incident_v2_origins'").fetchone():
        if connection.execute('SELECT 1 FROM fleet_incident_v2_origins WHERE subject_id=? AND case_id=? AND observation_revision=?',
                              (scope.subject_id, scope.case_id, revision)).fetchone():
            return True
    if connection.execute('SELECT 1 FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND observation_revision=? LIMIT 1',
                          (scope.subject_id, scope.case_id, revision)).fetchone():
        return True
    rows = connection.execute('SELECT assessment FROM fleet_judgment_records WHERE robot_id=? ORDER BY judgment_id DESC LIMIT 8',
                              (scope.subject_id,)).fetchall()
    for row in rows:
        receipt = json.loads(row['assessment'])
        request = receipt['request']
        if (request.get('case_id') == scope.case_id and request.get('revision') == revision
                and request.get('owner') == scope.owner_id and receipt['policy_revision'] == scope.policy_revision):
            return True
    return False


def final_facts(connection, scope, summary, now):
    if type(scope) is not CaseScope or type(summary) is not dict or set(summary) != {
            'reason', 'calls', 'observations', 'spent_micros', 'reserved_micros',
            'profile_sha256', 'observation_revision'}:
        raise ValueError('FINAL_REVIEW_SCOPE_REQUIRED')
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError('FINAL_REVIEW_TIME_INVALID')
    if any(re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', value) is None for value in (scope.subject_id, scope.case_id)):
        raise ValueError('FINAL_REVIEW_ID_INVALID')
    identifier(summary['observation_revision'])
    scope_json = canonical(asdict(scope))
    case = managed_case(connection, scope.subject_id, scope.case_id)
    if not final_current(connection, scope.subject_id, scope.case_id, scope_json, now):
        raise ValueError('FINAL_REVIEW_NOT_CURRENT_HOLD')
    for key in ('calls', 'observations', 'spent_micros', 'reserved_micros'):
        if type(summary[key]) is not int or summary[key] < 0 or summary[key] != case[key]:
            raise ValueError('FINAL_REVIEW_COUNTER_MISMATCH')
    if (summary['reason'] != case['reason'] or re.fullmatch('[A-Z0-9_]{1,64}', summary['reason']) is None
            or summary['profile_sha256'] != scope.profile_sha256
            or not original_revision(connection, scope, summary['observation_revision'])):
        raise ValueError('FINAL_REVIEW_SUMMARY_MISMATCH')
    current = connection.execute('SELECT assessment FROM fleet_judgment_current WHERE robot_id=?', (scope.subject_id,)).fetchone()
    facts = {**summary, 'scope_json': scope_json, 'observed_at': now, 'shadow': True,
             'original_policy_revision': scope.policy_revision,
             'current_policy_revision': json.loads(current['assessment'])['policy_revision'],
             'necessity': 'FINAL_FAILURE', 'cost_status': 'UNKNOWN' if connection.execute(
                 "SELECT 1 FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND state='UNKNOWN' LIMIT 1",
                 (scope.subject_id, scope.case_id)).fetchone() else 'RECORDED'}
    if len(canonical(facts).encode()) > 2048:
        raise ValueError('FINAL_REVIEW_SUMMARY_TOO_LARGE')
    return facts
