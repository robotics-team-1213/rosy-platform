"""Synthetic process-local control units; no peer network or physical device proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import re
from urllib.parse import unquote

from response import error, reply


TERMINAL = {'COMPLETED', 'FAILED', 'CANCELED', 'EXPIRED'}


class ControlUnits:
    def __init__(self, work, spatial, read_state):
        self.work, self.rows, self.tick = work, {}, 0
        self.spatial, self.read_state = spatial, read_state
        self.parents = {'R': None, 'A': 'R', 'A1': 'A', 'B': 'R'}
        self.controls = {unit: {'authority_epoch': 0, 'generation': 1} for unit in self.parents if unit != 'R'}
        self.stops = {}
        self.summary = {'unit_id': 'R', 'config_revision': 'sample-v1', 'parent': None,
                        'resources': ['robot:sample-robot'], 'children': ['A', 'B']}

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
        integrated = self.integrated(method, path, body, actor)
        if integrated is not None:
            return integrated
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

    def subtree(self, target):
        included = {target}
        for _ in self.parents:
            included.update(unit for unit, parent in self.parents.items() if parent in included)
        return included

    def fence(self, unit):
        if unit == 'R':
            return {'authority_epoch': 0, 'generation': self.work.dispatch['generation']}
        return self.controls[unit].copy()

    def local_stop_pending(self):
        return any(result['unit_id'] == 'R' and result['state'] == 'UNKNOWN'
                   for record in self.stops.values() for result in record['snapshot']['results'])

    def map_ref(self, unit):
        if unit != 'R':
            return None
        identity = self.spatial.active['map'].get('map_id')
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', identity):
            return None
        return {'map_id': identity, 'version': self.spatial.active['version'], 'frame': 'unit_local'}

    def tasks(self, robot_ids):
        return [{key: ('COMPLETED' if key == 'status' and task[key] == 'GOAL_CONFIRMED' else task[key])
                 for key in ('task_id', 'robot_id', 'status', 'updated_at')}
                for task in self.work.tasks.values() if task['robot_id'] in robot_ids]

    def information(self, unit):
        robots = []
        if unit == 'R':
            for row in self.read_state()['robots']:
                state = row['state']
                robots.append({'robot_id': row['robot_id'], 'online': row['online'], 'state_age_s': 0.0,
                    'mode': state['mode'], 'battery_percent': float(state['battery']['percent']),
                    'estop': state['safety']['estop'],
                    'pose': {**state['pose'], 'map_id': state['map_id'], 'source': 'sample.synthetic', 'frame': 'map'},
                    'evidence': {channel: state['evidence'][channel]['evidence'] for channel in ('pose', 'battery', 'safety')}})
        tasks = sorted(self.tasks({row['robot_id'] for row in robots}),
                       key=lambda row: (row['updated_at'], row['task_id']), reverse=True)
        return {'unit_id': unit, 'config_revision': self.summary['config_revision'], 'availability': 'AVAILABLE',
                'sampled_at': datetime.now(timezone.utc).isoformat(), 'age_s': 0.0, 'robots': robots,
                'tasks': tasks[:100], 'tasks_truncated': len(tasks) > 100, 'map': self.map_ref(unit), 'dispatch': self.fence(unit)}

    def overview(self):
        units = []
        for unit, parent in self.parents.items():
            detail = self.information(unit)
            tasks = self.tasks({row['robot_id'] for row in detail['robots']})
            units.append({'unit_id': unit, 'parent': parent, 'availability': detail['availability'],
                'sampled_at': detail['sampled_at'], 'age_s': detail['age_s'], 'robots_total': len(detail['robots']),
                'robots_online': sum(row['online'] for row in detail['robots']),
                'tasks_active': sum(task['status'] not in TERMINAL for task in tasks),
                'map': detail['map'], 'dispatch': detail['dispatch'], 'error': None,
                'stop_pending': sum(result['unit_id'] == unit and result['state'] == 'UNKNOWN'
                                    for record in self.stops.values() for result in record['snapshot']['results'])})
        return {'unit_id': 'R', 'config_revision': self.summary['config_revision'], 'units': units}

    def map_snapshot(self):
        model = self.spatial.active['map']
        try:
            places = [{'id': row['id'], 'label': row['name'], 'x': row['x'], 'y': row['y']} for row in model['places']]
            lanes = [{'id': row['id'], 'points': [{'x': x, 'y': y} for x, y in row['polyline']]} for row in model['edges']]
            elements = [(row['id'], row['label']) for row in places] + [(row['id'], row['id']) for row in lanes]
            points = places + [point for lane in lanes for point in lane['points']]
            def valid_id(value, limit):
                return isinstance(value, str) and 1 <= len(value) <= limit and re.fullmatch(r'[A-Za-z0-9_.-]+', value)
            if (not valid_id(model['map_id'], 64) or len(places) > 500 or len(lanes) > 1000
                    or sum(len(lane['points']) for lane in lanes) > 20000
                    or any(len(lane['points']) < 2 for lane in lanes)
                    or any(not valid_id(identity, 32) or not isinstance(label, str) or not 1 <= len(label) <= 128
                           for identity, label in elements)
                    or any(type(point[key]) not in (int, float) or not math.isfinite(point[key])
                           for point in points for key in ('x', 'y'))
                    or any(len({row['id'] for row in rows}) != len(rows) for rows in (places, lanes))):
                raise ValueError()
            snapshot = {'unit_id': 'R', 'config_revision': self.summary['config_revision'], 'map': self.map_ref('R'),
                        'places': places, 'lanes': lanes}
            if len(json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode()) > 2097152:
                raise ValueError()
            return reply(snapshot)
        except (KeyError, TypeError, ValueError):
            return error(422, 'INVALID_CONTROL_MAP_SNAPSHOT')

    def create_stop(self, body):
        if (set(body) != {'stop_id', 'target_unit', 'config_revision', 'expected_controls'}
                or not isinstance(body['stop_id'], str) or not 1 <= len(body['stop_id']) <= 128
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', body['stop_id'])
                or not isinstance(body['target_unit'], str)
                or not isinstance(body['config_revision'], str)
                or not isinstance(body['expected_controls'], dict) or not 1 <= len(body['expected_controls']) <= 4):
            return error(422, 'INVALID_REQUEST')
        fences = body['expected_controls']
        if any(not isinstance(fence, dict) or set(fence) != {'authority_epoch', 'generation'}
               or any(type(value) is not int or value < 0 for value in fence.values()) for fence in fences.values()):
            return error(422, 'INVALID_REQUEST')
        previous = self.stops.get(body['stop_id'])
        if previous:
            return reply(previous['snapshot']) if previous['body'] == body else error(409, 'CONTROL_STOP_CONFLICT')
        if body['config_revision'] != self.summary['config_revision']:
            return error(409, 'CONTROL_UNIT_CONFIG_CHANGED')
        if body['target_unit'] not in self.parents or not set(fences) <= self.subtree(body['target_unit']):
            return error(409, 'CONTROL_UNIT_OUTSIDE_SCOPE')
        if len(self.stops) >= 100:
            return error(409, 'CONTROL_STOP_CAPACITY')
        results = []
        for unit in self.parents:
            if unit not in self.subtree(body['target_unit']):
                continue
            expected = fences.get(unit)
            current = self.fence(unit)
            state = 'NOT_REACHED' if expected is None else 'STALE_FENCE'
            if expected == current:
                if unit == 'R':
                    # Synthetic lost local receipt demonstrates uncertainty without fabricating device proof.
                    self.work.handle('POST', '/estop', {})
                    self.work.dispatch['rearm_available'] = False
                else:
                    self.controls[unit]['generation'] += 1
                current = self.fence(unit)
                state = 'UNKNOWN' if unit == 'R' else 'ACKNOWLEDGED'
            results.append({'unit_id': unit,
                'state': state,
                'dispatch': deepcopy(current), 'acknowledged_robots': 0,
                'unknown_robots': len(self.read_state()['robots']) if state == 'UNKNOWN' else 0,
                'omx_state': 'NOT_CONFIGURED', 'physical_stop': 'UNVERIFIED',
                'error': 'SAMPLE_DELIVERY_UNCERTAIN' if state == 'UNKNOWN' else None})
        snapshot = {'unit_id': 'R', 'origin_id': 'R', 'stop_id': body['stop_id'], 'target_unit': body['target_unit'],
                    'config_revision': body['config_revision'], 'results': results, 'revision': 1}
        self.stops[body['stop_id']] = {'body': deepcopy(body), 'snapshot': snapshot,
                                     'updated_at': datetime.now(timezone.utc).isoformat(), 'attestation': None}
        return reply(snapshot)

    def reconcile_stop(self, record, body, actor):
        if (set(body) != {'expected_generation', 'receiver_channels_terminated', 'receivers_recommissioned',
                          'evidence', 'affected_units'}
                or type(body['expected_generation']) is not int or body['expected_generation'] < 0
                or body['receiver_channels_terminated'] is not True or body['receivers_recommissioned'] is not True
                or not isinstance(body['evidence'], str) or not 16 <= len(body['evidence'].strip()) <= 2048
                or body['affected_units'] != ['R']):
            return error(422, 'INVALID_REQUEST')
        local = next((row for row in record['snapshot']['results'] if row['unit_id'] == 'R'), None)
        if not local or local['state'] != 'UNKNOWN' or body['expected_generation'] != self.fence('R')['generation']:
            return error(409, 'CONTROL_STOP_RECONCILIATION_CONFLICT')
        record['attestation'] = {'actor': actor, 'body': deepcopy(body), 'original_result': deepcopy(local)}
        local['state'] = 'SUPERSEDED_BY_OPERATOR_RECOMMISSIONING'
        record['snapshot']['revision'] += 1
        record['updated_at'] = datetime.now(timezone.utc).isoformat()
        self.work.dispatch['rearm_available'] = not self.local_stop_pending() and not self.work.dispatch['dispatch_enabled']
        return reply(record['snapshot'])

    def integrated(self, method, path, body, actor):
        if (method, path) == ('GET', '/control-unit/overview'):
            return reply(self.overview())
        match = re.fullmatch(r'/control-unit/units/([^/]+)(/map)?', path)
        if method == 'GET' and match:
            unit, geometry = match.groups()
            if unit not in self.parents:
                return error(404, 'UNKNOWN_CONTROL_UNIT')
            if not geometry:
                return reply(self.information(unit))
            if unit != 'R':
                return error(404, 'CONTROL_UNIT_MAP_NOT_FOUND')
            return self.map_snapshot()
        if (method, path) == ('POST', '/control-unit/stop-inbox'):
            return error(403, 'CONTROL_UNIT_NOT_DIRECT_PARENT')
        if path == '/control-unit/stops':
            if method == 'POST':
                return self.create_stop(body)
            if method == 'GET':
                records = sorted(self.stops.values(), key=lambda row: row['updated_at'], reverse=True)
                return reply({'unit_id': 'R', 'config_revision': self.summary['config_revision'], 'stops': [
                    {key: record['snapshot'][key] for key in ('origin_id', 'stop_id', 'target_unit', 'config_revision', 'revision')}
                    | {'incomplete': any(row['state'] in {'UNKNOWN', 'PENDING', 'SENDING', 'NOT_REACHED'}
                                        for row in record['snapshot']['results']),
                       'local_reconciliation_required': any(row['unit_id'] == 'R' and row['state'] == 'UNKNOWN'
                                                            for row in record['snapshot']['results']),
                       'updated_at': record['updated_at']} for record in records]})
        match = re.fullmatch(r'/control-unit/stops/([^/]+)/([^/]+)(/reconcile)?', path)
        if match:
            origin, identity, action = match.groups()
            origin, identity = unquote(origin), unquote(identity)
            record = self.stops.get(identity)
            if origin != 'R' or record is None:
                return error(404, 'CONTROL_STOP_NOT_FOUND')
            if method == 'GET' and not action:
                return reply(record['snapshot'])
            if method == 'POST' and action:
                return self.reconcile_stop(record, body, actor)
        return None
