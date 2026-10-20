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
        return None
