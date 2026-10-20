"""A deterministic trip lifecycle; no actuator, dispatcher, or wall-clock timers."""
from copy import deepcopy
import re

from response import error, reply


class Work:
    def __init__(self):
        self.plans, self.trips = {}, {}
        self.dispatch = {'dispatch_enabled': True, 'generation': 1, 'queued_tasks': 0,
                         'unresolved_actions': 0, 'rearm_available': False, 'reason': None}

    def advance(self, event):
        states = {'complete': 'arrived', 'fail': 'failed', 'hold': 'link_wait', 'resume': 'running'}
        if event not in states or not self.trips:
            raise ValueError('unknown event or no trip')
        for trip in self.trips.values():
            if trip['state'] in ('started', 'running', 'link_wait'):
                trip.update(state=states[event], updated_at=trip['updated_at'] + 1)

    def handle(self, method, path, body):
        if (method, path) == ('GET', '/dispatch-control'):
            return reply(self.dispatch)
        if method == 'POST' and path in ('/estop', '/cancel-all', '/dispatch/rearm'):
            if path == '/dispatch/rearm':
                if body.get('expected_generation') != self.dispatch['generation']:
                    return error(409, 'DISPATCH_GENERATION_CHANGED')
                self.dispatch.update(dispatch_enabled=True, rearm_available=False, reason=None)
            else:
                self.dispatch.update(dispatch_enabled=False, rearm_available=True, reason='OPERATOR_STOP',
                                     generation=self.dispatch['generation'] + 1)
                for trip in self.trips.values():
                    trip.update(state='canceled', reason='OPERATOR_CANCEL')
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
                     'visible_state': 'ended' if t['state'] in ('arrived', 'canceled') else 'in_progress'}
                    for t in self.trips.values()]
            return reply({'observed_at': '2026-10-21T00:00:00Z', 'rows': rows, 'kinds': ['trip'],
                          'tasks_available': True, 'missions_available': False, 'cell_jobs_available': False,
                          'truncated_sources': []})
        return None
