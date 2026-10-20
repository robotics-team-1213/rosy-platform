"""Local enrollment demo; codes never trigger discovery, TLS enrollment or robot calls."""
import re

from response import error, reply


class Installation:
    def __init__(self):
        self.robots = {}

    def handle(self, method, path, body):
        if (method, path) == ('GET', '/enrollment/robots'):
            return reply({'available': True, 'unavailable_reason': None, 'static_robot_ids': ['sample-robot'],
                          'robots': list(self.robots.values()), 'alarms': []})
        if (method, path) == ('GET', '/discovery'):
            return reply({'scanner_online': True, 'scanner_state': 'online', 'scanner_age_s': 0,
                          'devices': [{'name': 'sample-new', 'address': 'sample.invalid', 'port': 443,
                                       'stage': 'ready', 'status': 'registered' if self.robots else 'discovered'}]})
        if (method, path) == ('POST', '/enrollment/robots'):
            if body.get('code') != '123456':
                return error(422, 'INVALID_PAIR_CODE')
            if body.get('discovery_name') != 'sample-new':
                return error(404, 'DISCOVERY_NOT_FOUND')
            if self.robots:
                return error(409, 'ROBOT_ALREADY_ENROLLED')
            self.robots['sample-enrolled'] = {
                'robot_id': 'sample-enrolled', 'hostname': 'sample-new', 'serial_number': 'SAMPLE',
                'device_uid': 'sample-device', 'discovery_name': 'sample-new', 'address': 'sample.invalid',
                'token_id': 'sample-only', 'role': 'operator', 'source': 'pair-site', 'expires_at': 4102444800,
                'fleet_expires_at': 4102444800, 'warn_at': None, 'principal_id': 'sample', 'state': 'active',
                'created_at': 1792454400, 'origin': 'enrolled', 'hold': None, 'expiry_warning': False,
                'legacy_lifetime': False, 'lifetime_shortened': False, 'hub_linked': False,
                'hub_host': None, 'hub_online': False, 'hub_state': 'unlinked', 'hub_linkable': True}
            return reply(self.robots['sample-enrolled'], 201)
        match = re.fullmatch(r'/enrollment/robots/([^/]+)(/move-address)?', path)
        if match:
            row = self.robots.get(match[1])
            if row is None:
                return error(404, 'UNKNOWN_ROBOT')
            if method == 'DELETE' and not match[2]:
                del self.robots[match[1]]
                return reply({'robot_id': match[1], 'state': 'removed'})
            if method == 'POST' and match[2]:
                if body.get('code') != '123456':
                    return error(422, 'INVALID_PAIR_CODE')
                row['address'] = 'moved-sample.invalid'
                return reply(row)
        return None
