"""A deterministic trip lifecycle; no actuator, dispatcher, or wall-clock timers."""
from copy import deepcopy
import json
import math
import re

from response import error, reply


def visible_state(status, reason=None):
    if status == 'HOLD' and reason == 'CANCELLED_BY_OPERATOR':
        return 'ended'
    if status in ('FAILED', 'UNKNOWN', 'EXPIRED', 'HOLD', 'failed', 'stopped'):
        return 'intervention'
    if status in ('GOAL_CONFIRMED', 'COMPLETED', 'CANCELED', 'arrived', 'canceled'):
        return 'ended'
    return 'approval_pending' if status == 'PROPOSED' else 'in_progress'


class Work:
    def __init__(self):
        self.plans, self.trips = {}, {}
        self.tasks, self.task_keys = {}, {}
        self.cell_jobs = {}
        self.formation = None
        self.dispatch = {'dispatch_enabled': True, 'generation': 1, 'queued_tasks': 0,
                         'unresolved_actions': 0, 'rearm_available': False, 'reason': None}

    def advance(self, event):
        states = {'complete': 'arrived', 'fail': 'failed', 'hold': 'link_wait', 'resume': 'running'}
        if event not in states or not self.trips:
            raise ValueError('unknown event or no trip')
        for trip in self.trips.values():
            if trip['state'] in ('started', 'running', 'link_wait'):
                trip.update(state=states[event], updated_at=trip['updated_at'] + 1)

    def advance_task(self, event):
        states = {'start': 'RUNNING', 'complete': 'GOAL_CONFIRMED', 'fail': 'FAILED', 'unknown': 'UNKNOWN'}
        opened = [task for task in self.tasks.values() if task['status'] in ('QUEUED', 'RUNNING', 'ACCEPTED')]
        if event not in states or not opened:
            raise ValueError('unknown event or no active task')
        for task in opened:
            task.update(status=states[event], reason=None)

    def handle(self, method, path, body, headers=None, robot_ids=('sample-robot',)):
        # D-865 P3: the sample site configures no admission scope, so the work view's
        # policy readback answers fail-closed exactly like an unconfigured real server.
        if path in ('/policy-admission', '/policy-admission/audit'):
            status = {'status': {'scope': {'enabled': False, 'robots': [], 'step_approval_kinds': [],
                    'max_admits': 1, 'valid_until': None, 'scope_revision': 'sample-unset'},
                    'admits_issued': 0, 'admits_remaining': 0, 'reason': 'NOT_CONFIGURED'}}
            if path.endswith('/audit'):
                if method != 'GET':
                    return error(405, 'METHOD_NOT_ALLOWED')
                return reply({'entries': [], 'cursor': None})
            if method == 'GET':
                return reply(status)
            if method == 'POST':
                if body.get('enabled'):
                    return error(409, 'POLICY_ADMISSION_SCOPE_NOT_CONFIGURED')
                return reply(status)
            return error(405, 'METHOD_NOT_ALLOWED')
        match = re.fullmatch(r'/robots/([^/]+)/goal', path)
        if method == 'POST' and match:
            robot = match[1]
            if robot not in robot_ids:
                return error(404, 'UNKNOWN_ROBOT')
            key = (headers or {}).get('idempotency-key')
            if not key:
                return error(400, 'IDEMPOTENCY_KEY_REQUIRED')
            if (set(body) != {'x', 'y', 'yaw'} or any(isinstance(n, bool) or not isinstance(n, (int, float))
                                                    or not math.isfinite(n) for n in body.values())):
                return error(422, 'INVALID_REQUEST')
            if key in self.task_keys:
                identifier, saved_robot, saved_body = self.task_keys[key]
                if saved_robot != robot or saved_body != body:
                    return error(409, 'IDEMPOTENCY_CONFLICT')
                task = self.tasks[identifier]
            else:
                identifier = f'sample-task-{len(self.tasks) + 1}'
                task = {'task_id': identifier, 'robot_id': robot, 'status': 'QUEUED', 'reason': None,
                        'goal': deepcopy(body), 'queue_position': 1, 'waiting_on': [], 'source': 'operator',
                        'updated_at': '2026-10-21T00:00:00Z'}
                self.tasks[identifier] = task
                self.task_keys[key] = identifier, robot, deepcopy(body)
            return reply({'accepted': task['status'] == 'ACCEPTED', 'queued': task['status'] == 'QUEUED', 'task': task})
        match = re.fullmatch(r'/tasks/([^/]+)(/cancel)?', path)
        if match:
            task = self.tasks.get(match[1])
            if task is None:
                return error(404, 'TASK_NOT_FOUND')
            if method == 'GET' and not match[2]:
                return reply({'task': task, 'history': []})
            if method == 'POST' and match[2]:
                if task['status'] not in ('QUEUED', 'RUNNING', 'ACCEPTED'):
                    return error(409, 'TASK_NOT_CANCELABLE')
                task.update(status='CANCELED', reason='OPERATOR_CANCEL')
                return reply({'task': task})
        if (method, path) == ('GET', '/dispatch-control'):
            self.dispatch['queued_tasks'] = sum(task['status'] == 'QUEUED' for task in self.tasks.values())
            return reply(self.dispatch)
        if method == 'POST' and path in ('/estop', '/cancel-all', '/dispatch/rearm'):
            if path == '/dispatch/rearm':
                if body.get('expected_generation') != self.dispatch['generation']:
                    return error(409, 'DISPATCH_GENERATION_CHANGED')
                self.dispatch.update(dispatch_enabled=True, rearm_available=False, reason=None)
            else:
                formation = self.formation.handle('POST', '/formation/stop', {}, robot_ids) if self.formation else None
                canceled = []
                if path == '/estop':
                    self.dispatch.update(dispatch_enabled=False, rearm_available=True, reason='OPERATOR_STOP',
                                         generation=self.dispatch['generation'] + 1)
                for trip in self.trips.values():
                    if trip['state'] in ('started', 'running', 'link_wait'):
                        trip.update(state='canceled', reason='OPERATOR_CANCEL')
                for task in self.tasks.values():
                    if task['status'] in ('QUEUED', 'RUNNING', 'ACCEPTED'):
                        task.update(status='CANCELED', reason='OPERATOR_CANCEL')
                        canceled.append(task['task_id'])
                if path == '/cancel-all':
                    return reply({'cancel_all_id': 'sample-cancel-all', 'record_error': None,
                        'cancelled': len(robot_ids), 'total': len(robot_ids), 'evidence': 'CORE_REPLY_ONLY',
                        'robots': [{'robot_id': robot, 'result': 'cancelled',
                                    'steps': {kind: {'ok': True} for kind in ('swarm', 'navigation', 'line_follow')},
                                    'tasks': {'awaiting_core_result': []}} for robot in robot_ids],
                        'formation': json.loads(formation.body) if formation else None, 'tasks': {'canceled': canceled}})
            return reply(self.dispatch)
        if (method, path) == ('POST', '/robots/sample-robot/trip'):
            if body.get('execute'):
                return error(501, 'TRIP_EXECUTION_NOT_AVAILABLE')
            if body.get('to') not in ('loading', 'home'):
                return error(422, 'TRIP_UNKNOWN_PLACE')
            identifier = f'sample-plan-{len(self.plans) + 1}'
            plan = {'plan_id': identifier, 'robot_id': 'sample-robot', 'to': body['to'],
                    'segments': [], 'waypoints': [{'x': 1, 'y': 1}, {'x': 3, 'y': 1}],
                    'length_m': 2, 'eta_s': 10, 'expires_at': 4102444800,
                    'start_check': {'ok': True, 'code': None}, 'context': {}}
            self.plans[identifier] = plan
            return reply(plan)
        match = re.fullmatch(r'/trips/([^/]+)(?:/(start|cancel|confirm-replan))?', path)
        if match:
            identifier, action = match.groups()
            if method == 'POST' and action == 'start':
                if identifier not in self.plans:
                    return error(404, 'TRIP_PLAN_NOT_FOUND')
                if identifier in self.trips:
                    return error(409, 'TRIP_BUSY')
                if not self.dispatch['dispatch_enabled']:
                    return error(409, 'DISPATCH_LATCHED')
                self.trips[identifier] = {'trip_id': identifier, 'plan_id': identifier, 'robot_id': 'sample-robot',
                                          'state': 'running', 'reason': None, 'updated_at': 1792454400,
                                          'plan': deepcopy(self.plans[identifier]), 'wait': None}
                return reply(self.trips[identifier])
            trip = self.trips.get(identifier)
            if trip is None:
                return error(404, 'TRIP_NOT_FOUND')
            if method == 'GET' and action is None:
                return reply(trip)
            if method == 'POST' and action in ('cancel', 'confirm-replan'):
                if trip['state'] not in ('started', 'running', 'link_wait'):
                    return error(409, 'TRIP_CLOSED')
                trip.update(state='canceled' if action == 'cancel' else 'running', updated_at=trip['updated_at'] + 1)
                return reply(trip)
        if (method, path) == ('GET', '/trips'):
            trips = list(self.trips.values())
            opened = [t for t in trips if t['state'] in ('started', 'running', 'link_wait')]
            return reply({'running': bool(opened), 'open': opened, 'trips': trips})
        if (method, path) == ('GET', '/work'):
            rows = [{'source': 'trip', 'source_id': t['trip_id'], 'device_id': t['robot_id'], 'action_kind': 'trip',
                     'status': t['state'], 'updated_at': '2026-10-21T00:00:00Z', 'reason': t['reason'],
                     'workcell_id': None, 'approval': None, 'wait': None,
                     'visible_state': visible_state(t['state'], t['reason'])}
                    for t in self.trips.values()]
            rows.extend({'source': 'task', 'source_id': task['task_id'], 'device_id': task['robot_id'], 'action_kind': 'navigate',
                         'status': task['status'], 'reason': task['reason'], 'updated_at': task['updated_at'],
                         'workcell_id': None, 'approval': None, 'wait': None,
                         'visible_state': visible_state(task['status'], task['reason'])}
                        for task in self.tasks.values())
            rows.extend({'source': 'cell_job', 'source_id': job['mission_id'], 'device_id': job['instance_id'],
                         'action_kind': 'CELL_TRANSFER', 'workcell_id': job['workcell_id'], 'status': job['status'],
                         'reason': job['reason'], 'updated_at': '2026-10-21T00:00:00Z', 'wait': None,
                         'visible_state': visible_state(job['status'], job['reason']),
                         'approval': 'two_person' if job['status'] == 'PROPOSED' else None}
                        for job in self.cell_jobs.values())
            return reply({'observed_at': '2026-10-21T00:00:00Z', 'rows': rows, 'kinds': ['trip', 'CELL_TRANSFER'],
                          'tasks_available': True, 'missions_available': True, 'cell_jobs_available': True,
                          'truncated_sources': []})
        return None
