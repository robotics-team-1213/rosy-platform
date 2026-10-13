"""Current owner evidence and signed epochs in the existing Fleet database."""
from dataclasses import asdict
import hashlib
import json

from rosy.contracts.learning import seal
from rosy.contracts.learning.incident_operation import APPROVE, REVOKE, verify_operation_receipt, validate_operation_receipt, validate_operation_binding
from rosy.decision.deliberation import canonical, identifier
from rosy.decision.deliberation.profiles import ModelProfile, incident_profiles
from ..store import IncidentCaseStore
from .candidates import RecoveryCandidates


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class OperationalState:
    def __init__(self, store, *, trusted, evidence):
        if type(store) is not IncidentCaseStore or not callable(trusted) or not callable(evidence):
            raise ValueError('EXPLICIT_EXISTING_STORE_AND_OWNER_PORTS_REQUIRED')
        self.store, self.trusted, self.evidence = store, trusted, evidence
        self.candidates = RecoveryCandidates(store)
        with store._transaction() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='fleet_line_stuck_answers'").fetchone():
                raise ValueError('EXISTING_STUCK_JOURNAL_REQUIRED')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_operation_events (
                epoch INTEGER PRIMARY KEY, body TEXT NOT NULL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_operation_submissions (
                subject_id TEXT NOT NULL, case_id TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(subject_id,case_id))''')

    def _events(self, conn):
        rows = conn.execute('SELECT epoch,body FROM fleet_operation_events ORDER BY epoch LIMIT 10001').fetchall()
        if len(rows) > 10000: raise ValueError('OPERATION_EVENT_LIMIT')
        events, previous = [], '0' * 64
        for index, row in enumerate(rows, 1):
            event = json.loads(row['body'])
            if (type(event) is not dict or set(event) != {'epoch', 'previous', 'grant_id', 'receipt', 'revision'}
                    or row['epoch'] != index or type(event['epoch']) is not int or event['epoch'] != index
                    or event['previous'] != previous or seal(event) != event or canonical(event) != row['body']):
                raise ValueError('OPERATION_HISTORY_CHANGED')
            identifier(event['grant_id']); validate_operation_receipt(event['receipt'])
            if event['receipt']['payload']['expected_epoch'] != index - 1:
                raise ValueError('OPERATION_HISTORY_EPOCH_CHANGED')
            payload = event['receipt']['payload']
            verify_operation_receipt(event['receipt'], trusted=self.trusted(), expected_binding=payload['binding'],
                epoch=index - 1, now=payload['valid_from_s'], kind=payload['kind'])
            previous = event['revision']; events.append(event)
        return events

    @staticmethod
    def _latest(events, grant_id):
        return next((event for event in reversed(events) if event['grant_id'] == grant_id), None)

    def epoch(self):
        with self.store._transaction() as conn: return len(self._events(conn))

    def _proof(self, grant_id):
        proof = self.evidence(grant_id)
        if type(proof) is not dict or set(proof) != {'binding', 'report', 'profiles', 'profile', 'approved_calibrations'}:
            raise ValueError('INDEPENDENT_CURRENT_OPERATING_EVIDENCE_REQUIRED')
        proof = json.loads(canonical(proof))
        report, binding = proof['report'], validate_operation_binding(proof['binding'])
        if (type(report) is not dict or report.get('schema') != 'rosy.incident.operational_acceptance/1'
                or report.get('state') != 'PASS_FOR_OPERATION' or report.get('missing') != []
                or report.get('field_accepted') is not True or report.get('truth_admitted') is not True
                or digest(report) != binding['evaluation_sha256']):
            raise ValueError('OPERATING_ORIGINAL_EVIDENCE_NOT_ACCEPTED')
        profiles = incident_profiles(tuple(ModelProfile(**p) for p in proof['profiles']))
        selected = ModelProfile(**proof['profile'])
        if (selected not in profiles or selected.calibration_revision is None
                or type(proof['approved_calibrations']) is not dict
                or proof['approved_calibrations'].get(selected.calibration_revision) != binding['calibration_sha256']
                or digest([asdict(p) for p in profiles]) != binding['profile_set_sha256']
                or digest(asdict(selected)) != binding['full_profile_sha256']
                or selected.model_revision != binding['model_revision'] or binding['domain'] not in selected.domains):
            raise ValueError('OPERATING_PROFILE_OR_CALIBRATION_CHANGED')
        return binding

    def apply(self, grant_id, receipt):
        identifier(grant_id)
        receipt = validate_operation_receipt(receipt)
        with self.store._transaction() as conn:
            events = self._events(conn); epoch = len(events)
            previous = self._latest(events, grant_id)
            kind = receipt['payload']['kind']
            if kind == REVOKE:
                if previous is None or previous['receipt']['payload']['kind'] != APPROVE:
                    raise ValueError('ACCEPTED_OPERATION_REQUIRED_FOR_REVOKE')
                binding = previous['receipt']['payload']['binding']
            else: binding = self._proof(grant_id)
            checked = verify_operation_receipt(receipt, trusted=self.trusted(), expected_binding=binding,
                epoch=epoch, now=self.store.clock(), kind=kind)
            event = seal(dict(epoch=epoch + 1, previous=events[-1]['revision'] if events else '0' * 64,
                              grant_id=grant_id, receipt=checked))
            conn.execute('INSERT INTO fleet_operation_events VALUES (?,?)', (event['epoch'], canonical(event)))
            return event

    def _grant(self, conn, grant_id):
        events = self._events(conn); event = self._latest(events, grant_id)
        if event is None or event['receipt']['payload']['kind'] != APPROVE:
            raise ValueError('CURRENT_OPERATION_NOT_ACCEPTED')
        receipt = verify_operation_receipt(event['receipt'], trusted=self.trusted(), expected_binding=self._proof(grant_id),
            epoch=event['epoch'] - 1, now=self.store.clock(), kind=APPROVE)
        return dict(epoch=len(events), revision=event['revision'], receipt=receipt)

    def grant(self, grant_id):
        identifier(grant_id)
        with self.store._transaction() as conn: return self._grant(conn, grant_id)

    @staticmethod
    def _slot_free(conn, subject_id, case_id):
        if conn.execute('SELECT 1 FROM fleet_operation_submissions WHERE subject_id=? AND case_id=?',
                        (subject_id, case_id)).fetchone():
            raise ValueError('CASE_PHYSICAL_SUBMISSION_ALREADY_CONSUMED')
        if conn.execute('''SELECT 1 FROM fleet_line_stuck_answers WHERE robot_id=? AND stuck_id=?
            AND decision!='WAIT' AND (accepted=1 OR code IN
            ('FLEET_STUCK_DISPATCH_PENDING','STUCK_DECISION_OUTCOME_UNKNOWN')) LIMIT 1''',
            (subject_id, case_id)).fetchone():
            raise ValueError('LEGACY_CASE_SUBMISSION_ALREADY_EXISTS')

    def claim_model(self, scope, grant_id, attempt_id, *, expected_epoch, generation, guard, on_claim=None):
        identifier(grant_id); identifier(attempt_id); identifier(generation)
        if type(expected_epoch) is not int or expected_epoch < 0 or not callable(guard) or on_claim is not None and not callable(on_claim):
            raise ValueError('EXPLICIT_EPOCH_AND_FINAL_OWNER_GUARD_REQUIRED')
        with self.store._transaction() as conn:
            self.store._case(conn, scope, active=True)
            self._slot_free(conn, scope.subject_id, scope.case_id)
            approval = self._grant(conn, grant_id)
            candidate = self.candidates._derive(conn, scope, attempt_id)
            saved = conn.execute('''SELECT payload_json FROM fleet_incident_v2_recovery_candidates
                WHERE subject_id=? AND case_id=? AND attempt_id=?''', (*self.store._key(scope), attempt_id)).fetchone()
            if saved is None or saved[0] != canonical(candidate): raise ValueError('RECORDED_CANDIDATE_REQUIRED')
            raw = json.loads(conn.execute('''SELECT receipt_json FROM fleet_incident_v2_model_receipts
                WHERE subject_id=? AND case_id=? AND attempt_id=?''', (*self.store._key(scope), attempt_id)).fetchone()[0])
            selected = next(p for p in raw['profiles'] if p['role'] == candidate['role'])
            binding = approval['receipt']['payload']['binding']
            if (approval['epoch'] != expected_epoch or candidate['generation'] != generation
                    or scope.profile_sha256 != binding['profile_set_sha256']
                    or scope.policy_revision != binding['policy_revision']
                    or digest(selected) != binding['full_profile_sha256']
                    or selected['model_revision'] != binding['model_revision']
                    or selected['calibration_revision'] is None or guard(conn) is not True):
                raise ValueError('CURRENT_OPERATING_CONTEXT_CHANGED')
            if self._grant(conn, grant_id) != approval:
                raise ValueError('OPERATING_ADMISSION_CHANGED_AT_CLAIM')
            self.store._case(conn, scope, active=True)
            record = seal(dict(subject_id=scope.subject_id, case_id=scope.case_id, scope=asdict(scope),
                actor='model', action=candidate['action'], state='SUBMITTING', grant_id=grant_id,
                admission_revision=approval['revision'], admission_epoch=approval['epoch'], candidate_id=candidate['candidate_id'],
                input_hash=candidate['input_hash'], generation=generation, expected_stuck=candidate['expected_stuck'], reply=None))
            conn.execute('INSERT INTO fleet_operation_submissions VALUES (?,?,?)',
                         (scope.subject_id, scope.case_id, canonical(record)))
            if on_claim is not None:
                if on_claim(conn) is not True or guard(conn) is not True or self._grant(conn, grant_id) != approval:
                    raise ValueError('OPERATING_AUDIT_OR_CONTEXT_CHANGED')
                self.store._case(conn, scope, active=True)
            return record

    def claim_rule(self, subject_id, case_id, *, generation, decision, guard):
        for value in (subject_id, case_id, generation): identifier(value)
        if decision not in {'BACK_AND_RETRY', 'RESUME', 'YIELD', 'ABORT', 'REALIGN', 'MANUAL'} or not callable(guard):
            raise ValueError('EXPLICIT_RULE_SUBMISSION_REQUIRED')
        with self.store._transaction() as conn:
            self._slot_free(conn, subject_id, case_id)
            if guard(conn) is not True: raise ValueError('CURRENT_RULE_CONTEXT_CHANGED')
            record = seal(dict(subject_id=subject_id, case_id=case_id, actor='rule', action=decision,
                               state='SUBMITTING', generation=generation, reply=None))
            conn.execute('INSERT INTO fleet_operation_submissions VALUES (?,?,?)', (subject_id, case_id, canonical(record)))
            return record

    @staticmethod
    def _submission(conn, subject_id, case_id):
        row = conn.execute('SELECT body FROM fleet_operation_submissions WHERE subject_id=? AND case_id=?',
                           (subject_id, case_id)).fetchone()
        if row is None: return None
        record = json.loads(row[0])
        if (seal(record) != record or canonical(record) != row[0]
                or (record['subject_id'], record['case_id']) != (subject_id, case_id)):
            raise ValueError('PHYSICAL_SUBMISSION_CHANGED')
        return record

    def submission(self, subject_id, case_id):
        with self.store._transaction() as conn: return self._submission(conn, subject_id, case_id)

    def finish_rule(self, subject_id, case_id, *, generation, state, reply):
        if state not in {'ACK', 'REFUSED', 'UNKNOWN'} or type(reply) is not dict or len(canonical(reply).encode()) > 4096:
            raise ValueError('BOUNDED_SUBMISSION_REPLY_REQUIRED')
        with self.store._transaction() as conn:
            record = self._submission(conn, subject_id, case_id)
            if (record is None or record.get('actor') != 'rule' or record.get('generation') != generation
                    or record.get('state') not in {'SUBMITTING', 'UNKNOWN'}):
                raise ValueError('OWNED_RULE_SUBMISSION_REQUIRED')
            record.update(state='UNKNOWN' if record['state'] == 'UNKNOWN' else state, reply=reply)
            record = seal(record)
            conn.execute('UPDATE fleet_operation_submissions SET body=? WHERE subject_id=? AND case_id=?',
                         (canonical(record), subject_id, case_id))
            return record

    def finish(self, scope, *, state, reply):
        if state not in {'ACK', 'REFUSED', 'UNKNOWN'} or type(reply) is not dict or len(canonical(reply).encode()) > 4096:
            raise ValueError('BOUNDED_SUBMISSION_REPLY_REQUIRED')
        with self.store._transaction() as conn:
            self.store._case(conn, scope)
            record = self._submission(conn, scope.subject_id, scope.case_id)
            if record is None or record.get('scope') != asdict(scope) or record['state'] not in {'SUBMITTING', 'UNKNOWN'}:
                raise ValueError('OWNED_SUBMISSION_REQUIRED')
            try:
                approval = self._grant(conn, record['grant_id'])
                if approval['revision'] != record['admission_revision']: state = 'UNKNOWN'
            except ValueError: state = 'UNKNOWN'
            if record['state'] == 'UNKNOWN': state = 'UNKNOWN'
            record.update(state=state, reply=reply); record = seal(record)
            conn.execute('UPDATE fleet_operation_submissions SET body=? WHERE subject_id=? AND case_id=?',
                         (canonical(record), scope.subject_id, scope.case_id))
            return record
