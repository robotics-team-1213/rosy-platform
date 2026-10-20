"""Backend-free sample provider. Unsupported requests fail visibly instead of succeeding."""
import json
from threading import RLock
from urllib.parse import urlsplit

from response import error
from sample.sessions import Sessions
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
            self.epoch += 1
            self.scenario_id = scenario_id
            self.sessions = Sessions(self.epoch, 'viewer' if scenario_id == 'viewer' else 'operator')
            self.work = Work()
            self.unhandled = []

    def advance(self, flow_id, event):
        with self.lock:
            if flow_id != 'work':
                raise ValueError('unknown sample flow')
            self.work.advance(event)

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
        if method != 'GET' and self.sessions.role == 'viewer':
            return error(403, 'FORBIDDEN')
        response = self.work.handle(method, path, payload)
        if response is not None:
            return response
        self.unhandled.append((method, target))
        return error(501, 'SAMPLE_REQUEST_NOT_IMPLEMENTED', f'{method} {path}')
