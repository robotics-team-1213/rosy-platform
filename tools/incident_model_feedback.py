"""Export one frozen Fleet incident for offline review; never calls a model or device."""
import argparse
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'operations/fleet'), str(ROOT / 'operations/decision/src'),
                str(ROOT / 'contracts/foundation'), str(ROOT / 'contracts/learning/src'), str(ROOT / 'tools')]
from incident_handoff_snapshot import snapshot_handoff
from rosy.contracts.learning.incident_profiles import validate_primary_roles
from fleet.incidents.automation.contract import CaseBudget, CaseScope, sha256, summary_json
from fleet.incidents.automation.ledger.receipt import ModelReceipt, checked_receipt
from rosy.decision.deliberation import canonical, identifier
from rosy.decision.deliberation.profiles import ModelProfile, incident_profiles


def feedback_json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) >= 1024 * 1024:
        raise ValueError('FEEDBACK_EXPORT_LIMIT')
    return encoded


def money(value):
    if type(value) is not int or not 0 <= value <= 1_000_000_000_000:
        raise ValueError('INVALID_RECORDED_COST')
    return value


def closure_receipt(value, scope, budget, reason, state):
    if value is None:
        if reason == 'RESOLVED_OBSERVED':
            raise ValueError('MISSING_CLOSURE_RECEIPT')
        return None
    fields = {'scope', 'requested_at', 'observed_at', 'closed_at', 'normal_revision', 'action_credit', 'state'}
    if (type(value) is not dict or set(value) != fields or value['scope'] != asdict(scope)
            or value['state'] != reason or reason != 'RESOLVED_OBSERVED' or state != 'HOLD'
            or value['requested_at'] != budget.started_at or value['action_credit'] not in {'NONE', 'UNVERIFIED'}):
        raise ValueError('UNBOUND_CLOSURE_RECEIPT')
    for key in ('requested_at', 'observed_at', 'closed_at'):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]):
            raise ValueError('INVALID_CLOSURE_TIME')
    if min(value['observed_at'], value['closed_at']) <= value['requested_at']:
        raise ValueError('CLOSURE_PRECEDES_REQUEST')
    identifier(value['normal_revision'])
    return value


def snapshot(path, subject_id, case_id, profiles, *, include_handoff=False):
    if type(include_handoff) is not bool: raise ValueError('EXPLICIT_HANDOFF_OPTION_REQUIRED')
    identifier(subject_id), identifier(case_id)
    if type(profiles) not in (list, tuple) or len(profiles) not in (1, 2):
        raise ValueError('FROZEN_PROFILE_MANIFEST_REQUIRED')
    selected = incident_profiles(tuple(ModelProfile(**p) for p in profiles))
    manifest = json.loads(canonical([asdict(p) for p in selected]))
    profile_hash = hashlib.sha256(canonical(manifest).encode()).hexdigest()
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        case = conn.execute('SELECT * FROM fleet_incident_v2_cases WHERE subject_id=? AND case_id=?',
                            (subject_id, case_id)).fetchone()
        if case is None:
            raise ValueError('CASE_NOT_FOUND')
        scope = CaseScope(**json.loads(case['scope_json']))
        if (scope.subject_id, scope.case_id, scope.profile_sha256) != (subject_id, case_id, profile_hash):
            raise ValueError('CASE_OR_PROFILE_MANIFEST_CHANGED')
        budget = CaseBudget(**json.loads(case['budget_json']))
        summary_json({'reason': case['reason']})
        if case['state'] not in {'ACTIVE', 'HOLD', 'NOT_NEEDED'}:
            raise ValueError('INVALID_CASE_STATE')
        rows = conn.execute('SELECT * FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? '
                            'ORDER BY attempt_id LIMIT 17', (subject_id, case_id)).fetchall()
        if len(rows) > 16:
            raise ValueError('ATTEMPT_EXPORT_LIMIT')
        traces = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_incident_v2_model_receipts'").fetchone():
            records = conn.execute('SELECT attempt_id,receipt_json FROM fleet_incident_v2_model_receipts '
                                   'WHERE subject_id=? AND case_id=? LIMIT 9', (subject_id, case_id)).fetchall()
            traces = {row['attempt_id']: row['receipt_json'] for row in records}
            if len(records) > 8 or len(traces) != len(records) or set(traces) - {r['attempt_id'] for r in rows}:
                raise ValueError('UNBOUND_MODEL_TRACE')
        attempts, spent, reserved = [], 0, 0
        for source in rows:
            row = dict(source)
            for key in ('attempt_id', 'observation_revision'):
                identifier(row[key])
            sha256(row['input_hash'])
            if (row['state'] not in {'RESERVED', 'SUBMITTING', 'COMPLETED', 'REJECTED', 'UNKNOWN'}
                    or row['kind'] not in {'model', 'observation'} or row.get('role') not in {None, 'primary', 'reviewer'}
                    or row['kind'] == 'observation' and row.get('role') is not None):
                raise ValueError('INVALID_ATTEMPT_RECEIPT')
            amount = money(row['reserved_micros'])
            actual = money(row['actual_micros']) if row['actual_micros'] is not None else None
            if (row['state'] in {'RESERVED', 'SUBMITTING'} and actual is not None
                    or row['kind'] == 'observation' and (amount != 0 or actual not in (None, 0))):
                raise ValueError('IMPOSSIBLE_ATTEMPT_COST')
            if row['state'] in {'COMPLETED', 'REJECTED'} and actual is None:
                raise ValueError('MISSING_TERMINAL_COST')
            spent += actual if actual is not None else 0
            if row['state'] in {'RESERVED', 'SUBMITTING', 'UNKNOWN'}:
                reserved += amount if actual is None else max(0, amount - actual)
            summary = json.loads(row['summary_json']) if row['summary_json'] is not None else None
            if summary is not None:
                summary_json(summary)
            trace = checked_receipt(scope, row, ModelReceipt(traces[row['attempt_id']])) if row['attempt_id'] in traces else None
            attempts.append({key: row.get(key) for key in ('attempt_id', 'input_hash', 'observation_revision',
                            'kind', 'role', 'state', 'reserved_micros', 'actual_micros')} | {'summary': summary, 'model_receipt': trace})
        calls = sum(a['kind'] == 'model' for a in attempts)
        observations = len(attempts) - calls
        if ((calls, observations, spent, reserved) != (case['calls'], case['observations'],
                money(case['spent_micros']), money(case['reserved_micros']))
                or calls > budget.max_calls or observations > budget.max_observations
                or case['state'] == 'NOT_NEEDED' and (calls or observations)):
            raise ValueError('CASE_ATTEMPT_TOTALS_DIFFER')
        proof = None
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_incident_v2_closures'").fetchone():
            proof = conn.execute('SELECT receipt_json FROM fleet_incident_v2_closures WHERE subject_id=? AND case_id=?',
                                 (subject_id, case_id)).fetchone()
        closure = closure_receipt(json.loads(proof[0]) if proof else None, scope, budget, case['reason'], case['state'])
        if closure is not None and any(a['state'] in {'RESERVED', 'SUBMITTING'} for a in attempts):
            raise ValueError('CLOSURE_WITH_INFLIGHT_ATTEMPT')
        result = dict(scope=asdict(scope), budget=asdict(budget), profiles=manifest, state=case['state'],
                      reason=case['reason'], calls=calls, observations=observations, spent_micros=spent,
                      reserved_micros=reserved, attempts=attempts, closure=closure,
                      outcome='RESOLVED_OBSERVED' if closure else 'IN_PROGRESS' if case['state'] == 'ACTIVE'
                      else 'DO_NOT_INTERVENE' if case['state'] == 'NOT_NEEDED' else 'UNRESOLVED')
        if len(selected) == 1: validate_primary_roles(result)
        if include_handoff: result['handoff'] = snapshot_handoff(conn, scope, budget, case)
    exported = dict(schema=f'rosy.incident.model_feedback/{3 if len(selected) == 1 else 2 if include_handoff else 1}', case=result, label_state='UNREVIEWED',
                    field_accepted=False, digest=hashlib.sha256(feedback_json(result).encode()).hexdigest())
    feedback_json(exported)
    return exported


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--subject', required=True)
    parser.add_argument('--case', required=True)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--include-handoff', action='store_true', help='deidentified recorded final-review and claim evidence')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.profiles.open('rb') as source:
            data = source.read(65537)
        if len(data) > 65536:
            raise ValueError('PROFILE_MANIFEST_LIMIT')
        result = snapshot(args.database, args.subject, args.case, json.loads(data), include_handoff=args.include_handoff)
        with args.out.open('x', encoding='utf-8') as output:
            output.write(feedback_json(result) + '\n')
        print(result['digest'])
        return 0
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        print('FEEDBACK_EXPORT_REJECTED', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
