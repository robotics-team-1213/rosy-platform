"""Display-only calibration records; these samples never establish physical calibration."""
from hashlib import sha256
import json
import math
import re

from response import error, reply


class Calibration:
    def __init__(self):
        self.records, self.points = {}, {}

    def handle(self, method, path, body):
        if (method, path) == ('GET', '/calibrations'):
            return reply({'calibrations': list(self.records.values()), 'use': 'display-only'})
        if (method, path) == ('POST', '/calibrations'):
            matrix = body.get('map_to_image')
            if (body.get('source_id') != 'sample-camera' or not isinstance(matrix, list) or len(matrix) != 9
                    or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in matrix)):
                return error(422, 'CALIBRATION_INVALID')
            revision = 'sample-' + sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
            row = {**body, 'calibration_revision': revision, 'map_id': 'sample-site',
                   'approved_by': 'sample', 'approved_at': '2026-10-21T00:00:00Z', 'use': 'display-only'}
            self.records[body['source_id']] = row
            return reply(row)
        match = re.fullmatch('/calibrations/([^/]+)', path)
        if method == 'DELETE' and match:
            return reply({'source_id': match[1], 'removed': self.records.pop(match[1], None) is not None})
        if (method, path) == ('GET', '/start-points'):
            return reply({'start_points': list(self.points.values())})
        match = re.fullmatch('/start-points/([^/]+)', path)
        if match:
            source = match[1]
            if method == 'DELETE':
                return reply({'source_id': source, 'removed': self.points.pop(source, None) is not None})
            if method == 'PUT':
                if source not in self.records:
                    return error(409, 'CALIBRATION_REQUIRED')
                if any(not isinstance(body.get(key), (int, float)) or not math.isfinite(body[key]) for key in ('x', 'y', 'yaw')):
                    return error(422, 'INVALID_REQUEST')
                self.points[source] = {**body, 'source_id': source, 'valid': True,
                                       'calibration_revision': self.records[source]['calibration_revision']}
                return reply(self.points[source])
        return None
