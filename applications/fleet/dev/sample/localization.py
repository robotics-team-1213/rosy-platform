"""Sample localization panel cases: fourteen labelled robots mirroring the FINAL relocalize/operator
route shapes (operations/fleet/fleet/server/pose/relocalize_routes.py, branch
fix/fleet-relocalize-operator), with no robot behind them and no command authority.

Served under /api/fleet: GET /auto-locate, POST /auto-locate/{id}/lift-block, GET /robots/{id}/localization,
and the operator-only writes POST /robots/{id}/relocalize and POST /robots/{id}/localization/confirm.
`age_s` inside `localization` is the sample's additive freshness field; LocalizationStatus itself carries
no clock Fleet trusts. Confirm takes exactly the real body ({candidate_id} or {x,y,yaw}); the dev event `expire` makes the next
confirm return CORE's STALE_REQUEST refusal ("request <id> is not the open one") verbatim, once.
"""
import json
import re
from pathlib import Path

from response import reply

LIVE_ID = 'loc-1'  # the robot the dev-panel events (/__dev/advance, flow localization) move
NOW_S = 1792454400.0  # the sample clock (the engine /state ts)
MOTION_ALLOW_S = 120.0
ROTATE_MISSION = {'kind': 'rotate_in_place', 'rung': 'rotate', 'held': [], 'result': 'sent'}
FAILED_MISSION = {'kind': 'rotate_in_place', 'rung': 'rotate', 'held': [], 'result': 'path_not_clear'}


def _revoked(reason):
    """One press, one motion (relocalize_routes 9d88d56b1d): once the gate closes the view is {revoked: {reason, at}}
    with reason `estop` or `mission_<CORE reason>`; no requester and no expires_in_s."""
    return {'allowed': False, 'last_operator_request': {'revoked': {'reason': reason, 'at': NOW_S}}}


def _refuse(status, code, message, **extra):
    return reply({'detail': {'code': code, 'message': message, **extra}}, status)


def _status(state, frame, **extra):
    return {'state': state, 'pose_frame': frame, 'confidence': 0.0, 'reason': None,
            'needs_human': False, 'request_id': None, 'unmapped_objects': [],
            'objects_stamp': None, **extra}


def _ladder(rung=None, candidates_for_s=None, last_decision=None, last_mission=None):
    return {'rung': rung, 'needs_human': False, 'candidates_for_s': candidates_for_s,
            'rung_missions': ['rotate_in_place'] if rung else [],
            'last_decision': last_decision, 'last_mission': last_mission, 'pose_request': None}


class Localization:
    def __init__(self):
        raw = json.loads((Path(__file__).parent / 'fixtures/localization.json').read_text(encoding='utf-8'))
        self.label = raw['label']
        self.report_candidates = raw['report_candidates']
        self.sequence = 0
        self.robots = {robot['id']: robot for robot in raw['robots']}

    def _sample(self, **payload):
        return {'sample': True, 'label': self.label, **payload}

    def _report(self):
        return {'robot_id': LIVE_ID, 'request_id': f'req-{LIVE_ID}-{self.sequence}',
                'candidates': [dict(candidate) for candidate in self.report_candidates],
                'unmapped_objects': [], 'square_sightings': [], 'pickup': False, 'stamp': NOW_S}

    def handle(self, method, path, body, actor='sample'):
        if (method, path) == ('GET', '/auto-locate'):
            robots = [robot['auto_locate'] for robot in self.robots.values() if robot.get('auto_locate')]
            return reply(self._sample(use='observation-only', robots=robots))
        if (method, path) == ('POST', '/auto-locate'):  # main: operator-only start, answers the snapshot
            robots = [robot['auto_locate'] for robot in self.robots.values() if robot.get('auto_locate')]
            return reply(self._sample(use='observation-only', robots=robots))
        match = re.fullmatch('/auto-locate/([^/]+)/lift-block', path)
        if match:
            entry = (self.robots.get(match[1]) or {}).get('auto_locate') or {}
            if method != 'POST' or not entry.get('anchor_blocked'):
                return _refuse(409, 'AUTO_LOCATE_NOT_ENABLED', 'auto locate is not blocked for this robot')
            entry['anchor_blocked'] = False
            entry['anchor_refused_reason'] = None
            return reply(self._sample(robot_id=match[1], anchor_blocked=False))
        match = re.fullmatch('/robots/([^/]+)/relocalize', path)
        if method == 'POST' and match:
            return self._relocalize(match[1], actor)
        match = re.fullmatch('/robots/([^/]+)/localization', path)
        if method == 'GET' and match:
            return self._read(match[1])
        match = re.fullmatch('/robots/([^/]+)/localization/confirm', path)
        if method == 'POST' and match:
            return self._confirm(match[1], body)
        return None

    def _relocalize(self, robot_id, actor):
        """The real route's refusal order: roster, service, trip, offline, already LOCALIZED."""
        robot = self.robots.get(robot_id)
        if robot is None:
            return _refuse(404, 'UNKNOWN_ROBOT', 'robot is not on the roster')
        if robot.get('disabled'):
            return _refuse(503, 'LOCALIZATION_DISABLED', 'this Fleet runs without the localization service')
        if robot.get('trip'):
            return _refuse(409, 'RELOCALIZE_TRIP_ACTIVE',
                           'the robot is on a trip or formation; stop it before relocalizing')
        if robot.get('offline'):
            return _refuse(409, 'ROBOT_OFFLINE', "the robot's state is unreadable (sample)")
        status = robot.get('localization')
        if status and status.get('state') == 'LOCALIZED':
            return _refuse(409, 'ALREADY_LOCALIZED', 'the robot is already LOCALIZED', localization=status)
        robot['phase'] = 'rotating'
        robot['localization'] = status or _status('UNKNOWN', 'odom')
        robot['ladder'] = _ladder(last_mission=dict(ROTATE_MISSION))
        robot['motion'] = {'allowed': True, 'last_operator_request': {
            'by': actor, 'at': NOW_S, 'expires_in_s': MOTION_ALLOW_S}}
        return reply(self._sample(robot_id=robot_id, requested_by=actor, motion_allowed=True,
                                  motion_allow_s=MOTION_ALLOW_S,
                                  last_operator_request=robot['motion']['last_operator_request'],
                                  mission=dict(ROTATE_MISSION)))

    def _read(self, robot_id):
        robot = self.robots.get(robot_id)
        if robot is None:
            return _refuse(404, 'UNKNOWN_ROBOT', 'robot is not on the roster')
        if robot.get('disabled'):
            return _refuse(503, 'LOCALIZATION_DISABLED', 'this Fleet runs without the localization service')
        motion = robot.get('motion') or {}
        return reply(self._sample(robot_id=robot_id, localization=robot.get('localization'),
                                  candidates=robot.get('candidates'), ladder=robot.get('ladder'),
                                  motion_allowed=motion.get('allowed', False),
                                  motion_allow_s=MOTION_ALLOW_S,
                                  last_operator_request=motion.get('last_operator_request')))

    def _confirm(self, robot_id, body):
        """Real order: body 422 -> roster 404 -> NO_CANDIDATES 409 -> index 404 -> CORE STALE_REQUEST 409.
        candidate_id indexes the CURRENT report."""
        pose = {'x', 'y', 'yaw'} & set(body)
        cid = body.get('candidate_id')
        if set(body) - {'candidate_id', 'x', 'y', 'yaw'} or (cid is None) == (not pose) or (pose and len(pose) != 3) or (cid is not None and (not isinstance(cid, int) or isinstance(cid, bool) or not 0 <= cid <= 7)):
            return _refuse(422, 'VALIDATION_ERROR', 'either candidate_id (0-7) or all of x, y, yaw')  # ConfirmRequest
        robot = self.robots.get(robot_id)
        if robot is None:
            return _refuse(404, 'UNKNOWN_ROBOT', 'robot is not on the roster')
        report = robot.get('candidates')
        if not report:
            return _refuse(409, 'NO_CANDIDATES', 'the robot is not reporting candidates')
        index = body.get('candidate_id')
        if index is None:  # exact pose as reported
            index = next((i for i, c in enumerate(report['candidates']) if all(abs(c[k] - body.get(k, 1e9)) < 1e-9 for k in ('x', 'y', 'yaw'))), -1)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(report['candidates']):
            return _refuse(404, 'CANDIDATE_NOT_REPORTED',
                           'only a candidate the robot reported can be confirmed')
        if robot.pop('stale_next', False):  # CORE's open request moved on since the report the operator saw
            return _refuse(409, 'STALE_REQUEST', f"request {report['request_id']} is not the open one", robot_id=robot_id)
        robot['phase'] = 'checking'
        robot['localization'] = _status('CANDIDATES', 'odom', reason='checking',
                                        request_id=report['request_id'])
        robot['ladder'] = {**(robot.get('ladder') or _ladder()),
                           'last_decision': {'request_id': report['request_id'],
                                             'candidate_index': index, 'cues': [], 'result': 'sent'}}
        return reply(self._sample(robot_id=robot_id, candidate_index=index,
                                  core={'request_id': report['request_id']}))

    def advance(self, event):
        robot = self.robots[LIVE_ID]
        phase = robot['phase']
        if event == 'relocalize' and phase in ('unknown', 'failed'):
            robot.update(phase='rotating', localization=_status('UNKNOWN', 'odom'), candidates=None,
                         ladder=_ladder(last_mission=dict(ROTATE_MISSION)),
                         motion={'allowed': True, 'last_operator_request': {
                             'by': 'sample', 'at': NOW_S, 'expires_in_s': MOTION_ALLOW_S}})
        elif event == 'candidates' and phase == 'rotating':
            report = self._report()
            robot.update(phase='candidates', candidates=report,
                         localization=_status('CANDIDATES', 'odom', request_id=report['request_id']),
                         ladder=_ladder(candidates_for_s=0.0, last_mission=dict(ROTATE_MISSION)),
                         motion=_revoked('mission_done'))  # the one rotation ended, so the gate closed
        elif event == 'obstacle' and phase == 'rotating':
            robot.update(phase='failed', localization=None, candidates=None,
                         ladder=_ladder(last_mission=dict(FAILED_MISSION)), motion=_revoked('mission_obstacle'))
        elif event == 'expire' and phase == 'candidates':  # the next confirm gets CORE's STALE_REQUEST once
            robot['stale_next'] = True
        elif event == 'confirm' and phase == 'candidates':
            robot['phase'] = 'checking'
            robot['localization']['reason'] = 'checking'
            robot['ladder']['last_decision'] = {'request_id': robot['candidates']['request_id'],
                                                'candidate_index': 0, 'cues': [], 'result': 'sent'}
        elif event == 'localized' and phase == 'checking':
            robot.update(phase='localized', candidates=None, ladder=None,
                         localization=_status('LOCALIZED', 'map', confidence=0.91,
                                              request_id=robot['candidates']['request_id'],
                                              age_s=0.0, objects_stamp=NOW_S))
        elif event == 'stop' and phase in ('rotating', 'candidates', 'checking'):
            robot.update(phase='failed', localization=None, candidates=None,
                         ladder=_ladder(last_mission=dict(FAILED_MISSION)))
            if (robot.get('motion') or {}).get('allowed'):  # an e-stop closes an open gate; a closed one stays as it was
                robot['motion'] = _revoked('estop')
        else:
            raise ValueError('localization transition rejected')
        self.sequence += 1
        report = robot.get('candidates')
        if report:  # every advance moves the request cycle on, so a held report goes stale
            report['request_id'] = f'req-{LIVE_ID}-{self.sequence}'
            robot['localization']['request_id'] = report['request_id']
