"""Durable reasoning calibration approvals; no current profile or device authority."""
import hashlib
import hmac
import json
import os
import re
import tempfile
from pathlib import Path

from registry import Registry, canonical, seal, write

LIMIT = 2 * 1024 * 1024
ZERO = '0' * 64
KINDS = {'approve': 'reasoning_calibration', 'revoke': 'reasoning_revocation'}


def calibration_digest(candidate):
    return hashlib.sha256(json.dumps(candidate['calibration_report'], sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def receipt_payload(candidate, kind, head):
    if kind not in KINDS.values(): raise ValueError('INVALID_REASONING_RECEIPT_KIND')
    return dict(candidate_revision=candidate['revision'], domain=candidate['domain'],
        profile_sha256=candidate['calibration_report']['full_profile_sha256'],
        calibration_sha256=calibration_digest(candidate), kind=kind, expected_head=head,
        verdict='pass' if kind == KINDS['approve'] else 'revoke')


class ReasoningRegistry:
    def __init__(self, root, *, validator, trusted=None):
        if not callable(validator): raise ValueError('EXPLICIT_REASONING_VALIDATOR_REQUIRED')
        self.validator = validator
        self._ledger = Registry(root, trusted=trusted)
        self.root = self._ledger.root
        with self._ledger._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS reasoning_candidates (revision TEXT PRIMARY KEY, stage TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reasoning_events (sequence INTEGER PRIMARY KEY, body TEXT NOT NULL)')

    def _read(self, path):
        try:
            with Path(path).open('rb') as stream: raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT: raise ValueError('REASONING_SNAPSHOT_TOO_LARGE')
            candidate = json.loads(raw)
            if type(candidate) is not dict or seal(candidate) != candidate or self.validator(candidate) != candidate:
                raise ValueError('INVALID_REASONING_SNAPSHOT')
            return seal(candidate)
        except (OSError, TypeError, KeyError) as error:
            raise ValueError('INVALID_REASONING_SNAPSHOT') from error

    def _candidate(self, revision):
        if type(revision) is not str or re.fullmatch('[0-9a-f]{64}', revision) is None:
            raise ValueError('CANONICAL_REASONING_REVISION_REQUIRED')
        candidate = self._read(self.root / 'reasoning' / revision / 'candidate.json')
        if candidate['revision'] != revision: raise ValueError('REASONING_SNAPSHOT_REVISION_DIFFERS')
        return candidate

    def _verify(self, candidate, receipt, kind, head):
        if (type(receipt) is not dict or set(receipt) != {'principal', 'payload', 'signature'}
                or type(receipt['principal']) is not str or type(receipt['signature']) is not str
                or re.fullmatch('[0-9a-f]{64}', receipt['signature']) is None):
            raise ValueError('INVALID_REASONING_RECEIPT')
        trust = self._ledger.trusted.get(receipt['principal'])
        expected = receipt_payload(candidate, kind, head)
        if not trust or kind not in trust['kinds'] or receipt['payload'] != expected:
            raise ValueError('REASONING_RECEIPT_BINDING_OR_TRUST_DIFFERS')
        signature = hmac.new(trust['key'], canonical(expected).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(receipt['signature'], signature):
            raise ValueError('REASONING_RECEIPT_SIGNATURE_DIFFERS')

    def _audit(self, db):
        events, stages, candidates, previous = [], {}, {}, ZERO
        try:
            for index, (sequence, body) in enumerate(db.execute('SELECT sequence, body FROM reasoning_events ORDER BY sequence'), 1):
                event = json.loads(body)
                if (type(event) is not dict or set(event) != {'sequence', 'previous', 'operation', 'candidate_revision', 'data', 'revision'}
                        or sequence != index or type(event['sequence']) is not int or event['sequence'] != index
                        or event['previous'] != previous or seal(event) != event):
                    raise ValueError('REASONING_EVENT_CHAIN_DIFFERS')
                revision, operation = event['candidate_revision'], event['operation']
                candidate = candidates.setdefault(revision, self._candidate(revision))
                if operation == 'register':
                    if revision in stages or event['data'] != {}: raise ValueError('REASONING_REGISTRATION_DIFFERS')
                    stages[revision] = 'candidate'
                elif operation in KINDS:
                    if (stages.get(revision) != ('candidate' if operation == 'approve' else 'approved')
                            or type(event['data']) is not dict or set(event['data']) != {'receipt'}):
                        raise ValueError('REASONING_TRANSITION_DIFFERS')
                    if operation == 'approve' and candidate['calibration_report']['state'] != 'PASS_OFFLINE_ONLY':
                        raise ValueError('REASONING_CALIBRATION_NOT_ACCEPTABLE')
                    self._verify(candidate, event['data']['receipt'], KINDS[operation], previous)
                    stages[revision] = 'approved' if operation == 'approve' else 'revoked'
                else: raise ValueError('INVALID_REASONING_OPERATION')
                previous = event['revision']; events.append(event)
            if dict(db.execute('SELECT revision, stage FROM reasoning_candidates')) != stages:
                raise ValueError('REASONING_STAGE_DIFFERS')
            self._approved(stages, candidates)
            return events, stages, candidates
        except (KeyError, TypeError) as error:
            raise ValueError('INVALID_REASONING_HISTORY') from error

    def _approved(self, stages, candidates):
        result = {}
        for revision, stage in stages.items():
            if stage != 'approved': continue
            candidate = candidates[revision]
            calibration, digest = candidate['profile']['calibration_revision'], calibration_digest(candidate)
            if calibration in result and result[calibration] != digest:
                raise ValueError('AMBIGUOUS_APPROVED_CALIBRATION_REVISION')
            result[calibration] = digest
        return result

    def _append(self, db, events, revision, operation, stage, data):
        event = seal(dict(sequence=len(events) + 1, previous=events[-1]['revision'] if events else ZERO,
                          candidate_revision=revision, operation=operation, data=data))
        db.execute('INSERT INTO reasoning_events VALUES (?, ?)', (event['sequence'], canonical(event)))
        db.execute('INSERT INTO reasoning_candidates VALUES (?, ?) ON CONFLICT(revision) DO UPDATE SET stage=excluded.stage',
                   (revision, stage))
        return event['revision']

    def register(self, source):
        candidate = self._read(source); revision = candidate['revision']
        with self._ledger._db() as db:
            events, stages, _ = self._audit(db)
            if revision in stages: return revision
            destination = self.root / 'reasoning' / revision
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                with tempfile.TemporaryDirectory(prefix='.reasoning-', dir=self.root) as scratch:
                    stage = Path(scratch) / 'snapshot'; stage.mkdir()
                    write(stage / 'candidate.json', candidate)
                    if self._read(stage / 'candidate.json') != candidate: raise ValueError('REASONING_COPY_DIFFERS')
                    os.replace(stage, destination)
            if self._candidate(revision) != candidate: raise ValueError('EXISTING_REASONING_SNAPSHOT_DIFFERS')
            self._append(db, events, revision, 'register', 'candidate', {})
            return revision

    def history(self):
        with self._ledger._db() as db: return self._audit(db)[0]

    def candidate(self, revision):
        with self._ledger._db() as db:
            _, _, candidates = self._audit(db)
            if revision not in candidates: raise ValueError('REASONING_CANDIDATE_NOT_REGISTERED')
            return candidates[revision]

    def approved_artifacts(self):
        with self._ledger._db() as db:
            _, stages, candidates = self._audit(db)
            return self._approved(stages, candidates)

    def approved_candidate(self, profile, domain):
        if type(profile) is not dict or type(domain) is not str:
            raise ValueError('EXPLICIT_REASONING_PROFILE_AND_DOMAIN_REQUIRED')
        with self._ledger._db() as db:
            _, stages, candidates = self._audit(db)
            matches = [candidate for revision, candidate in candidates.items()
                if stages[revision] == 'approved' and candidate['domain'] == domain
                and canonical(candidate['profile']) == canonical(profile)]
            if len(matches) != 1: raise ValueError('APPROVED_REASONING_PROFILE_NOT_FOUND')
            return matches[0]

    def _transition(self, revision, receipt, expected_head, operation):
        with self._ledger._db() as db:
            events, stages, candidates = self._audit(db)
            head = events[-1]['revision'] if events else ZERO
            if head != expected_head or stages.get(revision) != ('candidate' if operation == 'approve' else 'approved'):
                raise ValueError('REASONING_HEAD_OR_STAGE_CHANGED')
            candidate = candidates[revision]
            if operation == 'approve' and candidate['calibration_report']['state'] != 'PASS_OFFLINE_ONLY':
                raise ValueError('REASONING_CALIBRATION_NOT_ACCEPTABLE')
            self._verify(candidate, receipt, KINDS[operation], head)
            next_stage = 'approved' if operation == 'approve' else 'revoked'
            self._approved({**stages, revision: next_stage}, candidates)
            return self._append(db, events, revision, operation, next_stage, {'receipt': receipt})

    def approve(self, revision, receipt, *, expected_head):
        return self._transition(revision, receipt, expected_head, 'approve')

    def revoke(self, revision, receipt, *, expected_head):
        return self._transition(revision, receipt, expected_head, 'revoke')
