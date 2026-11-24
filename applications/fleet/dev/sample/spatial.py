"""Editable sample map, shared by planning, activation and monitoring reads."""
from copy import deepcopy
import re

from response import error, reply

INITIAL_MAP = {
    'map_id': 'sample-site', 'places': [
        {'id': 'home', 'name': '출발', 'x': 1, 'y': 1, 'kind': 'park'},
        {'id': 'loading', 'name': '적재', 'x': 3, 'y': 1, 'kind': 'stop'}],
    'edges': [{'id': 'home-loading', 'from': 'home', 'to': 'loading', 'polyline': [[1, 1], [3, 1]],
               'width_m': 0.5, 'speed_cap_mps': 0.2, 'drive_mode': 'free', 'bidirectional': True}],
    'crosswalks': [], 'zones': [], 'signals': [], 'view_turn_deg': 0,
}


class Spatial:
    def __init__(self):
        self.draft = {'revision': 1, 'map': deepcopy(INITIAL_MAP), 'updated_by': 'sample'}
        self.active = {'version': 1, 'map': deepcopy(INITIAL_MAP), 'activated_by': 'sample'}
        self.profiles = {}
        self.markers = []
        self.localizations = {
            'sample-robot': {
                'localization': {'state': 'CANDIDATES', 'pose_frame': 'odom', 'request_id': 'q1', 'needs_human': False},
                'candidates': {'robot_id': 'sample-robot', 'request_id': 'q1',
                               'candidates': [{'x': -0.53, 'y': 0.2, 'yaw': -0.02, 'scan_fit': 0.99, 'paint_score': None}]},
                'motion_allowed': False,
            },
        }
        self.bindings = {}

    def handle(self, method, path, body):
        if (method, path) == ('GET', '/site-map/active'):
            return reply(self.active)
        if (method, path) == ('GET', '/site-map/draft'):
            return reply(self.draft)
        if (method, path) == ('PUT', '/site-map/draft'):
            if body.get('expected_revision') != self.draft['revision']:
                return error(409, 'SITE_MAP_REVISION_CONFLICT')
            value = body.get('map')
            if not isinstance(value, dict) or not isinstance(value.get('places'), list) or not isinstance(value.get('edges'), list):
                return error(422, 'SITE_MAP_INVALID')
            self.draft = {'revision': self.draft['revision'] + 1, 'map': deepcopy(value), 'updated_by': 'sample'}
            return reply(self.draft)
        if (method, path) == ('POST', '/site-map/activate'):
            if body.get('expected_revision') != self.draft['revision']:
                return error(409, 'SITE_MAP_REVISION_CONFLICT')
            self.active = {'version': self.active['version'] + 1, 'map': deepcopy(self.draft['map']),
                           'activated_by': 'sample'}
            return reply(self.active)
        if (method, path) == ('GET', '/site-map/profiles'):
            return reply({'profiles': list(self.profiles.values())})
        match = re.fullmatch('/site-map/profiles/([^/]+)', path)
        if method == 'PUT' and match:
            identifier = match[1]
            old = self.profiles.get(identifier)
            if body.get('expected_revision') != (old['revision'] if old else None):
                return error(409, 'SITE_MAP_PROFILE_REVISION_CONFLICT')
            if not isinstance(body.get('map'), dict) or not body.get('name'):
                return error(422, 'SITE_MAP_INVALID')
            self.profiles[identifier] = {**body, 'profile_id': identifier, 'revision': old['revision'] + 1 if old else 1}
            return reply(self.profiles[identifier])
        if (method, path) == ('GET', '/site-map'):
            return reply({'maps': [{'map_id': 'sample-site', 'frame': 'map', 'units': 'm',
                                   'bounds_m': {'min_x': 0, 'min_y': 0, 'max_x': 4, 'max_y': 2},
                                   'polygon_m': [[0, 0], [4, 0], [4, 2], [0, 2]], 'sources': []}]})
        if (method, path) == ('GET', '/place-markers'):
            return reply({'markers': self.markers})
        if (method, path) == ('GET', '/site-points'):
            return reply({'detail': 'Not Found'}, status=404)
        return self._handle_robot_loc(method, path, body)

    def _robot_loc_state(self, robot_id):
        if robot_id != 'sample-robot':
            return None
        return self.localizations.setdefault(robot_id, {
            'localization': {'state': 'CANDIDATES', 'pose_frame': 'odom', 'request_id': 'q1', 'needs_human': False},
            'candidates': {'robot_id': robot_id, 'request_id': 'q1', 'candidates': []},
            'motion_allowed': False,
        })

    def _handle_robot_loc(self, method, path, body):
        m = re.fullmatch(r'/robots/([^/]+)/(localization|localization/confirm|relocalize|map-binding)', path)
        if not m:
            return None
        robot_id, sub = m[1], m[2]
        entry = self._robot_loc_state(robot_id)
        if entry is None:
            return error(404, 'UNKNOWN_ROBOT')
        if method == 'GET' and sub == 'localization':
            return reply({'robot_id': robot_id, **entry})
        if method == 'POST' and sub == 'relocalize':
            if entry['localization']['state'] == 'LOCALIZED':
                return error(409, 'ALREADY_LOCALIZED')
            entry['motion_allowed'] = True
            return reply({'robot_id': robot_id, 'requested_by': 'sample', 'motion_allowed': True, 'mission': {'kind': 'rotate_in_place', 'result': 'sent'}})
        if method == 'POST' and sub == 'localization/confirm':
            cands = entry['candidates']['candidates']
            idx = body.get('candidate_id')
            if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(cands):
                return error(404, 'CANDIDATE_NOT_REPORTED')
            entry['localization'] = {'state': 'LOCALIZED', 'pose_frame': 'map', 'request_id': entry['candidates']['request_id'], 'needs_human': False}
            return reply({'robot_id': robot_id, 'candidate_index': idx, 'core': {'request_id': entry['candidates']['request_id']}})
        if method == 'GET' and sub == 'map-binding':
            active = self.bindings.get(robot_id)
            return reply({'active': active, 'history': [active] if active else [], 'matches': active is not None,
                          'reason': None if active is not None else 'MAP_BINDING_REQUIRED', 'robot_grid_id': 'occupancy:sample',
                          **({'slam_camera_gap_m': 0.02} if active is not None else {})})
        if method == 'POST' and sub == 'map-binding':
            pairs, holdout = body.get('pairs') or [], body.get('holdout') or []
            if len(pairs) < 3:
                return error(409, 'TOO_FEW_PAIRS')
            if not holdout:
                return error(409, 'HOLDOUT_REQUIRED')
            record = {'binding_id': f'bind-{robot_id}', 'robot_grid_id': 'occupancy:sample', 'fit': {'yaw': 0.0, 'tx': 0.0, 'ty': 0.0}}
            self.bindings[robot_id] = record
            return reply(record)
        if method == 'DELETE' and sub == 'map-binding':
            revoked = self.bindings.pop(robot_id, None) is not None
            return reply({'revoked': revoked})
        return None
