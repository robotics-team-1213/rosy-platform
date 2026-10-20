"""An incoming request is reviewed before it can create a sample task or Cell Job."""
from hashlib import sha256
import json
import re

from response import error, reply


class Channel:
    def __init__(self, work, cell):
        self.work, self.cell = work, cell
        content = '샘플 로봇을 적재 위치로 보내 주세요.'
        self.receipt = {'request_id': 'sample-channel-1', 'principal_id': 'sample', 'guild_id': '10000000000000001',
                        'channel_id': '10000000000000002', 'message_id': '10000000000000003', 'author_id': '10000000000000004',
                        'content': content, 'content_hash': sha256(content.encode()).hexdigest(),
                        'received_at': '2026-10-21T00:00:00Z', 'status': 'REQUESTED'}
        self.review = {'request_id': self.receipt['request_id'], 'content_hash': self.receipt['content_hash'], 'revision': 0,
                       'state': 'REQUESTED', 'candidate': None, 'reason': None, 'work_kind': None, 'work_id': None,
                       'work_status': None, 'request_key': 'sample-channel-intent', 'incident': None}

    def current(self):
        identifier = self.review['work_id']
        if self.review['work_kind'] == 'task' and identifier in self.work.tasks:
            self.review['work_status'] = self.work.tasks[identifier]['status']
        if self.review['work_kind'] == 'cell_job' and identifier in self.cell.jobs:
            self.review['work_status'] = self.cell.jobs[identifier]['status']
        return self.review

    def handle(self, method, path, body, actor='sample'):
        if (method, path) == ('POST', '/channel-requests/discord'):
            return error(401, 'CHANNEL_TRANSPORT_REQUIRED')
        if (method, path) == ('GET', '/channel-requests'):
            return reply({'rows': [self.receipt] if actor == self.receipt['principal_id'] else []})
        match = re.fullmatch(r'/channel-requests/([^/]+)/(review|deliberation|submit|prepare|admit)', path)
        if not match:
            return None
        if match[1] != self.receipt['request_id'] or actor != self.receipt['principal_id']:
            return error(404, 'CHANNEL_REQUEST_NOT_FOUND')
        action = match[2]
        if method == 'GET' and action == 'review':
            return reply(self.current())
        if method == 'GET' and action == 'deliberation':
            return reply({'request_id': match[1], 'state': 'HOLD', 'profile_set_hash': 'a' * 64,
                          'input_hash': self.receipt['content_hash'], 'created_at': 1792454400,
                          'deadline': 1792454410, 'completed_at': 1792454401,
                          'result': {'reason': 'SAMPLE_ADVISORY_ONLY'}, 'action_admissible': False})
        if method not in ('POST', 'PUT'):
            return None
        if self.review['state'] == 'LINKED' and action == 'submit' and body.get('expected_hash') == self.review['content_hash']:
            return reply(self.current())
        if body.get('expected_hash') != self.review['content_hash'] or body.get('expected_revision') != self.review['revision']:
            return error(409, 'CHANNEL_REVIEW_CHANGED')
        if self.review['state'] == 'LINKED' and action != 'admit':
            return error(409, 'CHANNEL_ALREADY_LINKED')
        if action == 'review' and method == 'PUT':
            state, candidate = body.get('state'), body.get('candidate')
            if state not in ('READY', 'HOLD', 'REJECTED') or not body.get('reason') or (state == 'READY') != isinstance(candidate, dict):
                return error(422, 'INVALID_REQUEST')
            if candidate and candidate.get('robot_id') != 'sample-robot':
                return error(404, 'UNKNOWN_ROBOT')
            self.review.update(state=state, candidate=candidate, reason=body['reason'], revision=self.review['revision'] + 1)
            return reply(self.current())
        if action == 'submit' and method == 'POST':
            if self.review['state'] != 'READY':
                return error(409, 'CHANNEL_REVIEW_NOT_READY')
            candidate = self.review['candidate']
            response = self.work.handle('POST', '/robots/' + candidate['robot_id'] + '/goal',
                                        {k: candidate[k] for k in ('x', 'y', 'yaw')},
                                        {'idempotency-key': self.review['request_key']})
            if response.status != 200:
                return response
            task = json.loads(response.body)['task']
            self.review.update(state='LINKED', work_kind='task', work_id=task['task_id'], revision=self.review['revision'] + 1)
            return reply(self.current())
        if action == 'prepare' and method == 'POST' and body.get('kind') == 'cell_job':
            response = self.cell.handle('POST', '/cell-app/proposals', {**body, 'request_key': self.review['request_key']}, actor)
            if response.status != 200:
                return response
            self.review.update(state='LINKED', work_kind='cell_job', work_id=json.loads(response.body)['mission']['mission_id'],
                               revision=self.review['revision'] + 1)
            return reply(self.current())
        if action == 'admit' and method == 'POST' and self.review['work_kind'] == 'cell_job':
            response = self.cell.handle('POST', '/missions/' + self.review['work_id'] + '/admit', body, actor)
            return reply(self.current()) if response.status == 200 else response
        return None
