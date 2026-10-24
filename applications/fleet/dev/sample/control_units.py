"""Process-local delegation review; the existing sample Work owns task results."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import re

from response import error, reply


TERMINAL = {'COMPLETED', 'FAILED', 'CANCELED', 'EXPIRED'}


class ControlUnits:
    def __init__(self, work):
        self.work, self.rows, self.tick = work, {}, 0
        self.summary = {'unit_id': 'sample-unit', 'config_revision': 'sample-v1', 'parent': None,
                        'resources': ['robot:sample-robot'], 'children': []}

    def touch(self, row):
        self.tick += 1
        row['revision'] += 1
        row['updated_at'] = (datetime(2026, 10, 24, tzinfo=timezone.utc)
                             + timedelta(seconds=self.tick)).isoformat()

    def snapshot(self, row):
        if row['local_task_id']:
            task = self.work.tasks[row['local_task_id']]
            status = 'COMPLETED' if task['status'] == 'GOAL_CONFIRMED' else task['status']
            result = {key: task[key] for key in ('task_id', 'status', 'reason')}
            if row['status'] != status or row['result'] != result:
                row.update(status=status, result=result)
                self.touch(row)
        return {'unit_id': self.summary['unit_id'], 'config_revision': self.summary['config_revision'],
                'stale': False, 'delegation': row}

    def handle(self, method, path, body, actor):
        if (method, path) == ('GET', '/control-unit'):
            return reply(self.summary)
        if (method, path) == ('GET', '/control-unit/delegations'):
            return reply({'delegations': [self.snapshot(row) for row in self.rows.values()]})
        if (method, path) == ('POST', '/control-unit/delegations'):
            identity, goal = body.get('delegation_id'), body.get('goal')
            if (set(body) != {'delegation_id', 'target_unit', 'robot_id', 'goal'}
                    or not isinstance(identity, str) or len(identity) > 128
                    or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', identity)
                    or not isinstance(goal, dict) or set(goal) != {'x', 'y', 'yaw'}
                    or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n)
                           for n in goal.values())):
                return error(422, 'INVALID_REQUEST')
            request = {key: deepcopy(body[key]) for key in ('target_unit', 'robot_id', 'goal')}
            if identity in self.rows:
                row = self.rows[identity]
                return reply(self.snapshot(row)) if row['request'] == request else error(409, 'CONTROL_UNIT_CONFLICT')
            if body['target_unit'] != self.summary['unit_id']:
                return error(409, 'CONTROL_UNIT_OUTSIDE_SCOPE')
            if body['robot_id'] != 'sample-robot':
                return error(409, 'CONTROL_UNIT_RESOURCE_OUTSIDE_SCOPE')
            if sum(row['status'] not in TERMINAL for row in self.rows.values()) >= 256:
                return error(409, 'CONTROL_UNIT_ACTIVE_CAPACITY')
            row = {'origin_id': self.summary['unit_id'], 'delegation_id': identity, 'request': request,
                   'owner_unit': self.summary['unit_id'], 'config_revision': self.summary['config_revision'],
                   'status': 'PENDING', 'revision': 0, 'owner_revision': 0, 'local_actor': None,
                   'local_task_id': None, 'cancel_requested': False, 'result': {}}
            self.touch(row)
            self.rows[identity] = row
            return reply(self.snapshot(row))
        match = re.fullmatch(r'/control-unit/delegations/([^/]+)/([^/]+)(?:/(approve|cancel))?', path)
        if not match:
            return None
        origin, identity, action = match.groups()
        if origin != self.summary['unit_id'] or identity not in self.rows:
            return error(404, 'CONTROL_UNIT_DELEGATION_NOT_FOUND')
        row = self.rows[identity]
        self.snapshot(row)
        if method == 'GET' and action is None:
            return reply(self.snapshot(row))
        if method == 'POST' and action == 'approve':
            if (set(body) != {'expected_revision'} or type(body['expected_revision']) is not int
                    or body['expected_revision'] < 1):
                return error(422, 'INVALID_REQUEST')
            if (body['expected_revision'] != row['revision'] or row['cancel_requested']
                    or row['status'] in TERMINAL or row['local_actor'] not in (None, actor)):
                return error(409, 'CONTROL_UNIT_CONFLICT')
            if not row['local_task_id']:
                response = self.work.handle('POST', '/robots/sample-robot/goal', row['request']['goal'],
                                            {'idempotency-key': 'sample-control-unit:' + identity})
                if response.status != 200:
                    return response
                row.update(local_actor=actor, local_task_id=json.loads(response.body)['task']['task_id'])
            return reply(self.snapshot(row))
        if method == 'POST' and action == 'cancel':
            if row['status'] in TERMINAL:
                return reply(self.snapshot(row))
            if row['local_task_id']:
                response = self.work.handle('POST', '/tasks/' + row['local_task_id'] + '/cancel', {})
                if response.status != 200:
                    return response
            row['cancel_requested'] = True
            if not row['local_task_id']:
                row['status'] = 'CANCELED'
                self.touch(row)
            return reply(self.snapshot(row))
        return None
