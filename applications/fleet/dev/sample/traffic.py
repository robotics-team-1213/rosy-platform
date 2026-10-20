"""Formation lifecycle demo. It never computes or relays robot references."""
import math

from response import error, reply


class Traffic:
    def __init__(self):
        self.formation = {'active': False, 'state': 'IDLE'}

    def advance(self, event):
        if event != 'hold' or not self.formation['active']:
            raise ValueError('unknown event or no formation')
        self.formation.update(state='HOLDING', reason=['nav.stuck', self.formation['leader']])

    def handle(self, method, path, body, robot_ids):
        if (method, path) == ('GET', '/formation'):
            return reply(self.formation)
        if method != 'POST':
            return None
        if path == '/formation/start':
            if self.formation['active']:
                return error(409, 'FORMATION_ACTIVE')
            leader, members = body.get('leader'), body.get('members', [])
            spacing = body.get('spacing', .6)
            if (leader not in robot_ids or not isinstance(members, list) or not members
                    or any(item not in robot_ids or item == leader for item in members)):
                return error(422, 'FORMATION_MEMBERS_INVALID')
            if (body.get('formation') not in ('FOLLOW', 'COLUMN', 'LINE', 'V', 'GRID', 'CIRCLE', 'TRAIL')
                    or isinstance(spacing, bool) or not isinstance(spacing, (int, float)) or not math.isfinite(spacing) or spacing < .4):
                return error(422, 'INVALID_REQUEST')
            self.formation = {'active': True, 'state': 'RUNNING', 'leader': leader, 'formation': body['formation'],
                              'spacing': spacing, 'assignment': {identifier: {'distance': (i + 1) * spacing, 'lateral': 0}
                                                                 for i, identifier in enumerate(members)},
                              'reason': None, 'pending_triggers': [], 'relay': None, 'anchor': None, 'stream_evidence': None}
            return reply(self.formation)
        if path == '/formation/stop':
            self.formation.update(active=False, state='STOPPED', reason=['stopped', None])
            return reply(self.formation)
        if path == '/formation/resume':
            if self.formation['state'] != 'HOLDING':
                return error(409, 'FORMATION_NOT_HOLDING')
            self.formation.update(state='RUNNING', reason=None)
            return reply(self.formation)
        return None
