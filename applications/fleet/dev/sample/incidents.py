"""Historical sample evidence and durable human review, with no resolver actions."""
from response import error, reply


class Incidents:
    def __init__(self):
        self.report = {'robot_ids': ['sample-robot'], 'stuck_id': 'sample-stuck', 'classification': 'line_stuck',
                       'opened_at': '2026-10-21T00:00:00Z', 'closed_at': '2026-10-21T00:01:00Z', 'reviews': [],
                       'actions': [], 'notifications': [], 'handoff': None, 'judgment_revision': 'a' * 64,
                       'closure': {'status': 'OBSERVATION_ENDED'},
                       'evidence': {'core': {'cause': 'OBSTACLE', 'held_s_max': 10, 'attempts_max': 1},
                                    'fleet': {'pose_state': 'LOCALIZED', 'pose_age_s': 0}, 'rosy_cam': None, 'ai_facts': []}}

    def handle(self, method, path, body, actor='sample'):
        if (method, path) == ('GET', '/incidents'):
            return reply({'reports': [self.report], 'traffic_reports': []})
        if (method, path) == ('POST', '/incidents/sample-robot/sample-stuck/review'):
            if (body.get('root_cause') not in ('line_marking', 'obstacle', 'robot_fault', 'localization', 'traffic_wait', 'unknown')
                    or not isinstance(body.get('note'), str) or len(body['note']) > 1000):
                return error(422, 'INVALID_REQUEST')
            self.report['reviews'].append({**body, 'principal_id': actor})
            return reply({'reviewed': True})
        return None
