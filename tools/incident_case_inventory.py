"""Freeze retained Fleet cases for independent population checks; never dispatch."""
import argparse
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from incident_model_feedback import feedback_json, money, CaseBudget, CaseScope, ModelProfile, incident_profiles, canonical, identifier


def snapshot(path, profiles, *, owner, policy, start, end):
    identifier(owner); identifier(policy)
    if (any(type(t) not in (int, float) or not 0 <= t <= 1e12 or not math.isfinite(t) for t in (start, end))
            or not 0 < end - start <= 86400): raise ValueError('INVALID_INVENTORY_WINDOW')
    if type(profiles) not in (tuple, list) or len(profiles) not in (1, 2): raise ValueError('INVALID_INVENTORY_PROFILES')
    selected = incident_profiles(tuple(ModelProfile(**p) for p in profiles))
    profile_hash = hashlib.sha256(canonical([asdict(p) for p in selected]).encode()).hexdigest()
    scope = dict(owner_id=owner, policy_revision=policy, profile_sha256=profile_hash, start=start, end=end)
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        rows = db.execute('''SELECT * FROM fleet_incident_v2_cases
            WHERE json_extract(scope_json,'$.owner_id')=? AND json_extract(scope_json,'$.policy_revision')=?
            AND json_extract(scope_json,'$.profile_sha256')=?
            AND json_extract(budget_json,'$.started_at')>=? AND json_extract(budget_json,'$.started_at')<?
            ORDER BY subject_id,case_id LIMIT 1001''', (owner, policy, profile_hash, start, end)).fetchall()
        if len(rows) > 1000: raise ValueError('INVENTORY_CASE_LIMIT')
        records = []
        for row in rows:
            case_scope = CaseScope(**json.loads(row['scope_json']))
            budget = CaseBudget(**json.loads(row['budget_json']))
            if ((row['subject_id'], row['case_id']) != (case_scope.subject_id, case_scope.case_id)
                    or (case_scope.owner_id, case_scope.policy_revision, case_scope.profile_sha256) != (owner, policy, profile_hash)
                    or not start <= budget.started_at < end or row['state'] not in {'ACTIVE', 'HOLD', 'NOT_NEEDED'}):
                raise ValueError('INVENTORY_CASE_SCOPE_DIFFERS')
            record = {key: row[key] for key in ('state', 'reason', 'calls', 'observations', 'spent_micros', 'reserved_micros')}
            for key in ('calls', 'observations', 'spent_micros', 'reserved_micros'): money(record[key])
            if record['calls'] > budget.max_calls or record['observations'] > budget.max_observations:
                raise ValueError('INVENTORY_CASE_BUDGET_DIFFERS')
            identifier(record['reason'])
            records.append(dict(scope=asdict(case_scope), budget=asdict(budget), **record))
    body = dict(scope=scope, records=records)
    result = dict(schema='rosy.incident.case_inventory/1', **body,
        digest=hashlib.sha256(feedback_json(body).encode()).hexdigest(), label_state='UNREVIEWED',
        field_accepted=False, coverage='retained_case_rows_only')
    feedback_json(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--owner', required=True); parser.add_argument('--policy', required=True)
    parser.add_argument('--start', type=float, required=True); parser.add_argument('--end', type=float, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.profiles.open('rb') as stream: raw = stream.read(65537)
        if len(raw) > 65536: raise ValueError('INVENTORY_PROFILE_LIMIT')
        result = snapshot(args.database, json.loads(raw), owner=args.owner, policy=args.policy, start=args.start, end=args.end)
        with args.out.open('x', encoding='utf-8', newline='\n') as output: output.write(feedback_json(result) + '\n')
        print(result['digest']); return 0
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        print('CASE_INVENTORY_REJECTED'); return 1


if __name__ == '__main__': raise SystemExit(main())
