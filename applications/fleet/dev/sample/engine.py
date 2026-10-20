"""Backend-free sample provider. Unsupported requests fail visibly instead of succeeding."""
import json
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

from response import error, reply
from sample.sessions import Sessions
from sample.spatial import Spatial
from sample.governance import Governance
from sample.assistant import Assistant
from sample.vision import Vision
from sample.cell import Cell
from sample.installation import Installation
from sample.pairing import Pairing
from sample.calibration import Calibration
from sample.work import Work


class SampleEngine:
    def __init__(self, scenario_id='normal'):
        self.lock = RLock()
        self.epoch = 0
        self.reset(scenario_id)

    def reset(self, scenario_id='normal'):
        if scenario_id not in ('normal', 'viewer'):
            raise ValueError('unknown sample scenario')
        with self.lock:
            previous = getattr(self, 'sessions', None)
            self.epoch = max(self.epoch, previous.epoch if previous else 0) + 1
            self.scenario_id = scenario_id
            self.sessions = Sessions(self.epoch, 'viewer' if scenario_id == 'viewer' else 'operator')
            self.work = Work()
            self.spatial = Spatial()
            self.governance = Governance()
            self.assistant = Assistant()
            self.vision = Vision()
            self.cell = Cell(self.work.dispatch)
            self.installation = Installation()
            self.pairing = Pairing()
            self.calibration = Calibration()
            self.reads = json.loads((Path(__file__).parent / 'fixtures/normal.json').read_text(encoding='utf-8'))
            self.unhandled = []

    def advance(self, flow_id, event):
        with self.lock:
            if flow_id == 'monitoring':
                self.work.advance_task(event)
                return
            feature = {'work': self.work, 'assistant': self.assistant, 'cell_jobs': self.cell}.get(flow_id)
            if feature is None:
                raise ValueError('unknown sample flow')
            feature.advance(event)

    def handle(self, method, target, headers, body):
        with self.lock:
            return self._handle(method, target, {k.lower(): v for k, v in headers.items()}, body)

    def _handle(self, method, target, headers, body):
        path = urlsplit(target).path
        if not path.startswith('/api/fleet/'):
            return error(501, 'SAMPLE_REQUEST_NOT_IMPLEMENTED')
        path = path.removeprefix('/api/fleet')
        try:
            payload = json.loads(body) if body else {}
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            return error(422, 'INVALID_REQUEST')
        response = self.sessions.handle(method, path, payload, headers)
        if response is not None:
            return response
        if self.sessions.role == 'viewer' and path.startswith('/assistant/'):
            return error(403, 'FORBIDDEN')
        response = self.vision.handle(method, path, payload)
        if response is not None:
            return response
        if method != 'GET' and self.sessions.role == 'viewer':
            return error(403, 'FORBIDDEN')
        response = self.work.handle(method, path, payload, headers, ['sample-robot', *self.installation.robots])
        if response is not None:
            return response
        for feature in (self.spatial, self.governance, self.assistant, self.cell,
                        self.installation, self.pairing, self.calibration):
            response = feature.handle(method, path, payload)
            if response is not None:
                return response
        if (method, path) == ('GET', '/state'):
            robot = {'robot_id': 'sample-robot', 'online': True, 'state_age_s': 0, 'error': None,
                     'goal': None, 'queued': None, 'held': None, 'yielding': None,
                     'capabilities': {'navigation': {'goal_navigation': True}, 'swarm': {'lead': True, 'follow': True}},
                     'state': {'robot_id': 'sample-robot', 'mode': 'IDLE', 'map_id': 'sample-site',
                               'safety': {'estop': not self.work.dispatch['dispatch_enabled']},
                               'pose': {'x': 1, 'y': 1, 'yaw': 0}, 'battery': {'percent': 83},
                               'localization': {'state': 'LOCALIZED', 'pose_frame': 'map'}},
                     'localization': {'state': 'LOCALIZED', 'source': 'robot'}}
            robots = [robot]
            for identifier in self.installation.robots:
                from copy import deepcopy
                added = deepcopy(robot)
                added['robot_id'] = added['state']['robot_id'] = identifier
                robots.append(added)
            return reply({'fleet': {'name': '샘플 현장', 'online': len(robots), 'total': len(robots)},
                          'robots': robots, 'signals': {}, 'alarms': [], 'ts': 1792454400})
        if method == 'GET' and f'GET {path}' in self.reads:
            return reply(self.reads[f'GET {path}'])
        self.unhandled.append((method, target))
        return error(501, 'SAMPLE_REQUEST_NOT_IMPLEMENTED', f'{method} {path}')
