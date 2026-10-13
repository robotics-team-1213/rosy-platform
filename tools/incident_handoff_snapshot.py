"""Read only the Fleet export transaction; never sends or claims an incident."""
from dataclasses import asdict
import hashlib
import json

from rosy.contracts.learning.incident_handoff import digest, validate_handoff


def snapshot_handoff(conn, scope, budget, case):
    names = {'claims': 'fleet_incident_claims', 'outbox': 'fleet_notification_outbox', 'queues': 'fleet_incident_v2_handoff_queues'}
    tables = {key: 'PRESENT' if conn.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',
              ('table', name)).fetchone() else 'ABSENT' for key, name in names.items()}
    key = (scope.subject_id, scope.case_id)
    proof = dict(schema='rosy.incident.handoff_evidence/1', scope_sha256=digest(asdict(scope)), tables=tables,
        queue=None, claim=None, notifications=[], assertions=dict(verified_human_identity=False, independent_quality=False))
    if tables['queues'] == 'PRESENT':
        queue = conn.execute('SELECT * FROM fleet_incident_v2_handoff_queues WHERE subject_id=? AND case_id=?', key).fetchone()
        if queue is not None: proof['queue'] = {'queued_at': queue['queued_at']}
    if tables['claims'] == 'PRESENT':
        claim = conn.execute('SELECT * FROM fleet_incident_claims WHERE robot_id=? AND stuck_id=?', key).fetchone()
        if claim is not None:
            raw = dict(claim)
            if type(raw['principal_id']) is not str or not raw['principal_id'] or len(raw['principal_id']) > 512:
                raise ValueError('INVALID_RECORDED_CLAIM')
            proof['claim'] = dict(claimed_at=raw['claimed_at'], judgment_revision=raw['judgment_revision'],
                                 record_sha256=digest(raw), binding='CASE_ONLY')
    if tables['outbox'] == 'PRESENT':
        rows = conn.execute("SELECT * FROM fleet_notification_outbox WHERE robot_id=? AND stuck_id=? AND kind='FINAL_REVIEW' ORDER BY event_id LIMIT 33", key).fetchall()
        if len(rows) > 32: raise ValueError('HANDOFF_OUTBOX_LIMIT')
        for source in rows:
            row = dict(source)
            if row['state'] == 'SENT' and (row['last_code'] != 'PROVIDER_ACCEPTED'
                    or type(row['last_attempt_at']) not in (int, float)
                    or type(row['delivered_at']) not in (int, float)
                    or not row['created_at'] <= row['last_attempt_at'] <= row['delivered_at']):
                raise ValueError('HANDOFF_PROVIDER_ACCEPTANCE_UNBOUND')
            if type(row['payload']) is not str or len(row['payload'].encode()) > 4096: raise ValueError('HANDOFF_SOURCE_LIMIT')
            facts = json.loads(row['payload'])
            scope_json = json.dumps(asdict(scope), sort_keys=True, separators=(',', ':'), allow_nan=False)
            if (type(facts) is not dict or facts.get('scope_json') != scope_json
                    or (facts.get('robot_id'), facts.get('stuck_id'), facts.get('kind')) != (*key, 'FINAL_REVIEW')
                    or facts.get('profile_sha256') != scope.profile_sha256
                    or row['judgment_revision'] != hashlib.sha256(scope_json.encode()).hexdigest()
                    or facts.get('observed_at') != row['created_at']
                    or type(row['created_at']) not in (int, float) or row['created_at'] < budget.started_at
                    or type(row['expires_at']) not in (int, float) or row['expires_at'] != row['created_at'] + 600):
                raise ValueError('HANDOFF_SOURCE_SCOPE_CHANGED')
            for field in ('calls', 'observations', 'spent_micros', 'reserved_micros'):
                if type(facts.get(field)) is not int or facts[field] != case[field]: raise ValueError('HANDOFF_SOURCE_COUNTER_CHANGED')
            if facts.get('reason') != case['reason']: raise ValueError('HANDOFF_SOURCE_REASON_CHANGED')
            revision = facts.get('observation_revision')
            linked = conn.execute('SELECT 1 FROM fleet_incident_v2_attempts WHERE subject_id=? AND case_id=? AND observation_revision=?', (*key, revision)).fetchone()
            if not linked:
                linked = conn.execute('SELECT 1 FROM fleet_incident_v2_origins WHERE subject_id=? AND case_id=? AND observation_revision=?', (*key, revision)).fetchone()
            if not linked: raise ValueError('HANDOFF_SOURCE_REVISION_CHANGED')
            proof['notifications'].append({field: row[field] for field in ('event_id', 'state', 'attempts', 'created_at', 'delivered_at')}
                                          | {'record_sha256': digest(row)})
    return validate_handoff(proof, asdict(scope), budget.started_at)
