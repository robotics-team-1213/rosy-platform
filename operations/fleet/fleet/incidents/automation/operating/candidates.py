"""D-722 durable non-executable candidates in the existing incident database."""
from dataclasses import asdict
import hashlib
import json

from rosy.decision.deliberation import canonical, identifier
from rosy.decision.deliberation.contracts.recovery import recovery_context
from ..ledger.receipt import ModelReceipt, checked_receipt
from ..store import IncidentCaseStore


def observed_recovery(snapshot, subject_id, case_id, revision):
    if type(snapshot) is not dict or type(snapshot.get('robots')) is not list:
        return None
    rows = [row for row in snapshot['robots'] if type(row) is dict and row.get('robot_id') == subject_id]
    if len(rows) != 1 or rows[0].get('online') is not True:
        return None
    try:
        state = rows[0]['state']
        seq, stamp = state.get('seq'), state.get('timestamp')
        if type(seq) is not int or seq < 0 or type(stamp) is not str or not stamp or revision != f'core:{seq}:{stamp}':
            return None
        stuck = state['line_follow']['stuck']
        if type(stuck) is not dict or stuck.get('stuck_id') != case_id:
            return None
        return recovery_context({key: stuck[key] for key in ('phase', 'attempts', 'max_attempts', 'local_enabled', 'cause')})
    except (KeyError, TypeError, ValueError):
        return None


class RecoveryCandidates:
    def __init__(self, store):
        if type(store) is not IncidentCaseStore:
            raise ValueError('EXISTING_INCIDENT_STORE_REQUIRED')
        self.store = store
        with store._transaction() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_incident_v2_recovery_candidates (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
                payload_json TEXT NOT NULL, PRIMARY KEY(subject_id,case_id,attempt_id),
                FOREIGN KEY(subject_id,case_id,attempt_id)
                REFERENCES fleet_incident_v2_attempts(subject_id,case_id,attempt_id))''')

    def _derive(self, conn, scope, attempt_id, worker_id=None):
        if scope.owner_id != 'core':
            raise ValueError('RECOVERY_OWNER_REQUIRED')
        key = self.store._key(scope)
        attempt = conn.execute('''SELECT * FROM fleet_incident_v2_attempts
            WHERE subject_id=? AND case_id=? AND attempt_id=?''', (*key, attempt_id)).fetchone()
        receipt = conn.execute('''SELECT receipt_json FROM fleet_incident_v2_model_receipts
            WHERE subject_id=? AND case_id=? AND attempt_id=?''', (*key, attempt_id)).fetchone()
        if (attempt is None or worker_id is not None and attempt['worker_id'] != worker_id
                or attempt['state'] != 'COMPLETED' or receipt is None):
            raise ValueError('COMPLETED_MODEL_SOURCE_REQUIRED')
        raw = checked_receipt(scope, dict(attempt), ModelReceipt(receipt[0]))
        p, checked = raw['problem'], raw['judgment']
        winners = [v['choice'] for v in checked['alternatives']
                   if v['probability'] == max(i['probability'] for i in checked['alternatives'])]
        if (p['domain'] != 'line_follow' or p['necessity'] != 'INTERVENE'
                or checked['verdict'] != 'candidate' or winners != ['back_and_retry']
                or checked['next_step']['tool_name'] != 'propose_lane_back'
                or checked['objections'] or checked['missing_evidence']):
            raise ValueError('MODEL_RECOVERY_CANDIDATE_NOT_ELIGIBLE')
        context = recovery_context(json.loads(p['facts_json'])['recovery'])
        candidate = dict(schema='rosy.incident.recovery_candidate/1', scope=asdict(scope),
            attempt_id=attempt_id, input_hash=attempt['input_hash'], generation=attempt['observation_revision'],
            role=attempt['role'], action='BACK_AND_RETRY', state='RECORDED', action_admissible=False,
            expected_stuck={'phase': context['phase'], 'attempts': context['attempts']})
        candidate['candidate_id'] = hashlib.sha256(canonical(candidate).encode()).hexdigest()
        return candidate

    def propose(self, scope, attempt_id, *, worker_id):
        identifier(attempt_id), identifier(worker_id)
        with self.store._transaction() as conn:
            self.store._case(conn, scope, active=True)
            key = self.store._key(scope)
            candidate = self._derive(conn, scope, attempt_id, worker_id)
            encoded = canonical(candidate)
            old = conn.execute('''SELECT payload_json FROM fleet_incident_v2_recovery_candidates
                WHERE subject_id=? AND case_id=? AND attempt_id=?''', (*key, attempt_id)).fetchone()
            if old is not None:
                if old[0] != encoded:
                    raise ValueError('RECOVERY_CANDIDATE_CHANGED')
            else:
                conn.execute('INSERT INTO fleet_incident_v2_recovery_candidates VALUES (?,?,?,?)', (*key, attempt_id, encoded))
            return candidate

    def candidates(self, scope):
        with self.store._transaction() as conn:
            self.store._case(conn, scope)
            rows = conn.execute('''SELECT attempt_id,payload_json FROM fleet_incident_v2_recovery_candidates
                WHERE subject_id=? AND case_id=? ORDER BY attempt_id LIMIT 9''', self.store._key(scope)).fetchall()
            if len(rows) > 8:
                raise ValueError('RECOVERY_CANDIDATE_LIMIT_EXCEEDED')
            candidates = []
            for row in rows:
                candidate = self._derive(conn, scope, row['attempt_id'])
                if row['payload_json'] != canonical(candidate):
                    raise ValueError('RECOVERY_CANDIDATE_CHANGED')
                candidates.append(candidate)
            return tuple(candidates)
