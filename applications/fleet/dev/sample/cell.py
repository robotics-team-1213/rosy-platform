"""Revisioned documents and simulated job receipts, using a recorded compiler result."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from response import error, reply


def digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Cell:
    def __init__(self, dispatch):
        self.dispatch = dispatch
        self.preview = json.loads((Path(__file__).parent / 'fixtures/cell-preview.json').read_text(encoding='utf-8'))
        self.documents, self.jobs, self.requests = {}, {}, {}
        self.proposers = {}
        for kind in ('recipe', 'cell'):
            document = self.preview['candidate'][kind]
            self.documents[kind, 'sample'] = {'kind': kind, 'id': 'sample', 'document': document,
                                             'digest': digest(document), 'updated_at': '2026-10-21T00:00:00Z'}

    def advance(self, event):
        states = {'hold': 'HOLD', 'complete': 'GOAL_CONFIRMED', 'action-complete': 'ACTION_SUCCEEDED'}
        opened = [job for job in self.jobs.values() if job['status'] in ('READY', 'HOLD', 'ACTION_SUCCEEDED')
                  and job['reason'] != 'CANCELLED_BY_OPERATOR']
        if event not in states or not opened:
            raise ValueError('unknown event or no open Cell Job')
        for job in opened:
            job.update(status=states[event], reason='SAMPLE_HOLD' if event == 'hold' else None)
            if event == 'complete':
                job['current_step_index'] = len(job['steps']) - 1
                for step in job['steps']:
                    step.update(status='GOAL_CONFIRMED', reason=None)

    def compile(self, body):
        for kind in ('recipe', 'cell'):
            row = self.documents.get((kind, body.get(kind + '_id')))
            if row is None:
                return error(404, 'CELL_APP_DOCUMENT_NOT_FOUND')
            if row['digest'] != body.get(kind + '_digest'):
                return error(409, 'CELL_APP_DOCUMENT_CHANGED')
            # shortcut: only the recorded canonical recipe is planned; use connected mode for arbitrary compiler inputs.
            if row['document'] != self.preview['candidate'][kind]:
                return error(422, 'CELL_APP_COMPILE_INVALID', 'Sample preview supports the supplied example documents')
        return reply(self.preview)

    def mission(self, job):
        return {'mission_id': job['mission_id'], 'status': job['status'], 'reason': job['reason'],
                'workcell_id': job['workcell_id'], 'instance_id': job['instance_id']}

    def proposal(self, job):
        return {'proposal': {'proposal_id': job['mission_id']}, 'mission': self.mission(job)}

    def handle(self, method, path, body, actor='sample'):
        if (method, path) == ('GET', '/cell-app/object-catalog'):  # D-934: one measured, one not yet weighed
            return reply({'objects': [
                {'id': 'container-2', 'kind': 'green shipping container', 'length_mm': 60, 'width_mm': 30,
                 'top_height_mm': 30, 'mass_kg': 0.048, 'mass_measured': {'at': '2026-10-30T12:00:00+00:00',
                 'source': 'cell_scale', 'reading': '48.0 g'}, 'max_gross_kg': None,
                 'carry': 'ok: the gate checks it against the reviewed bound'},
                {'id': 'container-3', 'kind': 'green shipping container', 'length_mm': 90, 'width_mm': 30,
                 'top_height_mm': 30, 'mass_kg': None, 'mass_measured': None, 'max_gross_kg': None,
                 'carry': 'blocked: no measured mass (D-935)'}]})
        if (method, path) == ('GET', '/cell-app/documents'):
            return reply({'documents': [{k: v for k, v in row.items() if k != 'document'}
                                        for _, row in sorted(self.documents.items())]})
        match = re.fullmatch(r'/cell-app/documents/(recipe|cell)/([A-Za-z0-9][A-Za-z0-9_-]{0,63})', path)
        if match:
            key = match[1], match[2]
            row = self.documents.get(key)
            if method == 'GET':
                return reply(row) if row else error(404, 'CELL_APP_DOCUMENT_NOT_FOUND')
            if method == 'POST':
                if body.get('expected_digest') != (row['digest'] if row else None):
                    return error(409, 'CELL_APP_DOCUMENT_CHANGED')
                document = body.get('document')
                if not isinstance(document, dict):
                    return error(422, 'CELL_APP_DOCUMENT_INVALID')
                try:
                    value = digest(document)
                except (ValueError, TypeError):
                    return error(422, 'CELL_APP_DOCUMENT_INVALID')
                self.documents[key] = {'kind': key[0], 'id': key[1], 'document': deepcopy(document),
                                       'digest': value, 'updated_at': '2026-10-21T00:00:00Z'}
                return reply(self.documents[key])
        if (method, path) == ('POST', '/cell-app/compile'):
            return self.compile(body)
        if (method, path) == ('POST', '/cell-app/proposals'):
            result = self.compile(body)
            if result.status != 200:
                return result
            request = body.get('request_key')
            if not request or not body.get('workcell_id') or not body.get('instance_id'):
                return error(422, 'INVALID_REQUEST')
            if request in self.requests:
                old, identifier = self.requests[request]
                return reply(self.proposal(self.jobs[identifier])) if old == body else error(409, 'IDEMPOTENCY_CONFLICT')
            identifier = f'sample-cell-job-{len(self.jobs) + 1}'
            steps = []
            for index, step in enumerate(s for s in self.preview['candidate']['job']['steps'] if s['kind'] == 'place'):
                steps.append({'step_index': index, 'status': 'WAITING', 'reason': None,
                              'step': {'inputs': {'pallet_id': step['pallet'], 'layer_index': step['layer'], 'item': step['item']}}})
            self.jobs[identifier] = {'mission_id': identifier, 'status': 'PROPOSED', 'reason': None, 'steps': steps,
                                     'current_step_index': 0, 'workcell_id': body['workcell_id'], 'instance_id': body['instance_id'],
                                     'events': [], 'operator_checkpoints': []}
            self.requests[request] = body.copy(), identifier
            self.proposers[identifier] = actor
            return reply(self.proposal(self.jobs[identifier]))
        match = re.fullmatch(r'/(cell-jobs|missions)/([^/]+)(?:/(admit|cancel|resume|reconcile))?', path)
        if match:
            kind, identifier, action = match.groups()
            job = self.jobs.get(identifier)
            if job is None:
                return None
            if method == 'GET' and action is None:
                return reply({'job': job} if kind == 'cell-jobs' else {'mission': self.mission(job)})
            if method == 'POST' and action:
                if action in ('admit', 'resume'):
                    expected = 'PROPOSED' if action == 'admit' else 'HOLD'
                    if (body.get('expected_generation') != self.dispatch['generation'] or not self.dispatch['dispatch_enabled']
                            or job['status'] != expected or job['reason'] == 'CANCELLED_BY_OPERATOR'):
                        return error(409, 'CELL_JOB_RECOVERY_REFUSED')
                    if action == 'admit' and actor == self.proposers[identifier]:
                        return error(403, 'CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER')
                    job.update(status='READY', reason=None)
                elif action == 'cancel':
                    if job['status'] not in ('READY', 'HOLD', 'ACTION_SUCCEEDED'):
                        return error(409, 'CELL_JOB_RECOVERY_REFUSED')
                    job.update(status='HOLD', reason='CANCELLED_BY_OPERATOR')
                elif action == 'reconcile':
                    if job['status'] != 'HOLD':
                        return error(409, 'CELL_JOB_RECOVERY_REFUSED')
                    return reply({'job': job, 'readback': []})
                return reply({'job': job} if kind == 'cell-jobs' else {'mission': self.mission(job)})
        return None
