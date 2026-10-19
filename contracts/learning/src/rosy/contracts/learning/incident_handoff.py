"""Bounded handoff evidence; recorded claims never verify human identity."""
import math
import json

from .prediction import canonical_sha256 as digest
from .digest import is_sha256_hex


def _hash(value):
    if type(value) is not str or not is_sha256_hex(value):
        raise ValueError('INVALID_HANDOFF_HASH')


def _time(value, minimum):
    if type(value) not in (int, float) or not minimum <= value <= 1_000_000_000_000 or not math.isfinite(value):
        raise ValueError('INVALID_HANDOFF_TIME')


def validate_handoff(value, scope, started_at):
    """Validate JSON only. Caller approval of producer provenance is separate."""
    _time(started_at, 0)
    if (type(scope) is not dict or set(scope) != {'subject_id', 'case_id', 'owner_id', 'profile_sha256', 'policy_revision'}
            or any(type(v) is not str or not v or len(v) > 512 for v in scope.values())):
        raise ValueError('INVALID_HANDOFF_SCOPE')
    _hash(scope['profile_sha256'])
    if (type(value) is not dict or set(value) != {'schema', 'scope_sha256', 'tables', 'queue', 'claim', 'notifications', 'assertions'}
            or value['schema'] != 'rosy.incident.handoff_evidence/1' or value['scope_sha256'] != digest(scope)
            or type(value['assertions']) is not dict
            or set(value['assertions']) != {'verified_human_identity', 'independent_quality'}
            or any(v is not False for v in value['assertions'].values())):
        raise ValueError('INVALID_HANDOFF_EVIDENCE')
    tables = value['tables']
    if (type(tables) is not dict or set(tables) != {'claims', 'outbox', 'queues'}
            or any(type(v) is not str or v not in {'ABSENT', 'PRESENT'} for v in tables.values())):
        raise ValueError('INVALID_HANDOFF_TABLE_COVERAGE')
    queue, claim, notifications = value['queue'], value['claim'], value['notifications']
    if queue is not None:
        if type(queue) is not dict or set(queue) != {'queued_at'} or tables['queues'] != 'PRESENT':
            raise ValueError('INVALID_HANDOFF_QUEUE')
        _time(queue['queued_at'], started_at)
    if claim is not None:
        if (type(claim) is not dict or set(claim) != {'claimed_at', 'judgment_revision', 'record_sha256', 'binding'}
                or claim['binding'] != 'CASE_ONLY' or tables['claims'] != 'PRESENT'):
            raise ValueError('INVALID_HANDOFF_CLAIM')
        _time(claim['claimed_at'], started_at); _hash(claim['judgment_revision']); _hash(claim['record_sha256'])
    if type(notifications) is not list or len(notifications) > 32 or notifications and tables['outbox'] != 'PRESENT':
        raise ValueError('INVALID_HANDOFF_NOTIFICATIONS')
    ids = []
    for row in notifications:
        if (type(row) is not dict or set(row) != {'event_id', 'state', 'attempts', 'created_at', 'delivered_at', 'record_sha256'}
                or type(row['event_id']) is not int or row['event_id'] < 1 or type(row['state']) is not str
                or row['state'] not in {'PENDING', 'RETRY', 'SENDING', 'UNKNOWN', 'EXPIRED', 'SUPERSEDED', 'SENT', 'FAILED'}
                or type(row['attempts']) is not int or not 0 <= row['attempts'] <= 3):
            raise ValueError('INVALID_HANDOFF_NOTIFICATION_ROW')
        _time(row['created_at'], started_at); _hash(row['record_sha256'])
        if row['state'] == 'SENT':
            if row['attempts'] == 0: raise ValueError('UNSUBMITTED_HANDOFF_ACCEPTANCE')
            _time(row['delivered_at'], row['created_at'])
        elif row['delivered_at'] is not None: raise ValueError('UNBOUND_HANDOFF_ACCEPTANCE')
        ids.append(row['event_id'])
    if ids != sorted(set(ids)): raise ValueError('DUPLICATE_HANDOFF_NOTIFICATION')
    raw = json.dumps(value, allow_nan=False)
    if len(raw.encode()) > 16384: raise ValueError('HANDOFF_EVIDENCE_LIMIT')
    return json.loads(raw)
