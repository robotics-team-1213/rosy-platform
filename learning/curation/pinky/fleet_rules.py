"""Read retained rule selections only; never infer execution or complete coverage."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import math

MAX_EXPORT_BYTES = 1024 * 1024

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'contracts/learning/src'))
from rosy.contracts.learning.incident_rule import validate_rule
if __package__:
    from .fleet_observations import _contains_sensitive_field
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fleet_observations import _contains_sensitive_field


def _in_checkout(path) -> bool:
    """True inside a git working tree: artifacts stay out of source checkouts, on any drive."""
    path = Path(path).resolve()
    return any((p / '.git').exists() for p in (path, *path.parents))


# Format pinned: retained rule export digests include the size bound; test_canonical_hash_formats.
def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_EXPORT_BYTES: raise ValueError('RULE_EXPORT_LIMIT')
    return hashlib.sha256(raw).hexdigest()


def snapshot(database, *, subject_id, case_id, owner_id, config_sha256, policy_revision, start, end):
    if (any(type(v) is not str or not v or v != v.strip() or len(v) > 512
            for v in (subject_id, owner_id, policy_revision))
            or case_id is not None and (type(case_id) is not str or not case_id or case_id != case_id.strip() or len(case_id) > 512)
            or type(config_sha256) is not str or re.fullmatch('[0-9a-f]{64}', config_sha256) is None
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1e12 for v in (start, end))
            or not 0 < end-start <= 86400):
        raise ValueError('INVALID_RULE_EXPORT_SCOPE')
    scope = dict(subject_id=subject_id, case_id=case_id, owner_id=owner_id,
                 config_sha256=config_sha256, policy_revision=policy_revision, start=float(start), end=float(end))
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        rows = db.execute('''SELECT selection_id,robot_id,received_at,
            CASE WHEN length(CAST(payload_json AS BLOB))<=65536 THEN payload_json ELSE NULL END
            FROM fleet_rule_selections WHERE robot_id=? AND received_at>=? AND received_at<=?
            ORDER BY selection_id LIMIT 4097''', (subject_id, start, end)).fetchall()
    if len(rows) > 4096: raise ValueError('RULE_EXPORT_ROW_LIMIT')
    records = []
    for oid, rid, received, payload in rows:
        if type(payload) is not str: raise ValueError('INVALID_RULE_EXPORT_PAYLOAD')
        receipt = validate_rule(json.loads(payload))
        request, assessment = receipt['assessment']['request'], receipt['assessment']
        canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if (_contains_sensitive_field(receipt) or canonical != payload or request['subject_id'] != rid
                or type(oid) is not int or oid < 1 or type(received) not in (int, float)
                or not math.isfinite(received) or received < assessment['evaluated_at']):
            raise ValueError('INVALID_RULE_EXPORT_SOURCE')
        if request['case_id'] != case_id: continue
        if (request['owner'] != owner_id or receipt['config_sha256'] != config_sha256
                or assessment['policy_revision'] != policy_revision):
            raise ValueError('RULE_EXPORT_SCOPE_CHANGED')
        records.append(dict(selection_id=oid, received_at=received, receipt=receipt,
                            sha256=hashlib.sha256(payload.encode()).hexdigest()))
    if not records: raise ValueError('NO_RETAINED_RULE_SELECTION')
    exported = dict(schema='rosy.incident.rule_feedback/1', scope=scope, records=records,
                digest=digest(dict(scope=scope, records=records)), label_state='UNREVIEWED',
                field_accepted=False, coverage='retained_selections_only')
    if len(json.dumps(exported, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()) + 1 > MAX_EXPORT_BYTES:
        raise ValueError('RULE_EXPORT_LIMIT')
    return exported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path); parser.add_argument('output', type=Path)
    for name in ('subject-id', 'owner-id', 'config-sha256', 'policy-revision'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--case-id')
    parser.add_argument('--start', type=float, required=True); parser.add_argument('--end', type=float, required=True)
    args = vars(parser.parse_args())
    output, database = args.pop('output'), args.pop('database')
    if _in_checkout(output): raise ValueError('export output belongs outside the source checkout')
    exported = snapshot(database, **args)
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(exported, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n')
    return 0


if __name__ == '__main__': raise SystemExit(main())
