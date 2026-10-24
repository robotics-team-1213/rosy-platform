"""HTTP-only robot I/O for LeRobot; CORE retains source identity and admission."""
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a robot credential to a redirected endpoint.


urlopen = build_opener(ProxyHandler({}), _NoRedirect()).open


class CoreArmError(RuntimeError):
    def __init__(self, code, status):
        super().__init__(f'CORE arm request refused: {code} ({status})')
        self.code, self.status = code, status


def _camera_layout(cameras):
    return [(c['name'], c['shape']) for c in cameras]


class CoreArmClient:
    def __init__(self, url, *, token, policy_revision, timeout=2.0):
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                or not token or '\n' in token or '\r' in token
                or not re.fullmatch(r'[0-9a-f]{64}', policy_revision)
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError('CORE origin, credential, pinned policy revision and positive timeout required')
        self.url, self._token = url.rstrip('/'), token
        self.policy_revision, self.timeout = policy_revision, timeout
        self.info, self._observation_id = None, None

    def _request(self, method, path, body=None):
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = Request(self.url + '/api/v1/arm/' + path, data=data, method=method,
                          headers={'Authorization': 'Bearer ' + self._token, 'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            with exc:
                try:
                    code = json.load(exc).get('error', {}).get('code', 'HTTP_ERROR')
                except (ValueError, AttributeError):
                    code = 'HTTP_ERROR'
            raise CoreArmError(code, exc.code) from None

    @property
    def is_connected(self):
        return self.info is not None

    def connect(self):
        if self.is_connected:
            raise RuntimeError('CORE arm is already connected')
        info = self._request('GET', 'policy')
        if (info.get('policy_revision') != self.policy_revision or info.get('simulation') is not True
                or info.get('units') != 'rad'):
            raise ValueError('CORE installed policy pin or supported units differ')
        if not info.get('cameras'):  # A D-800 CORE reports only the single ``camera``.
            info = dict(info, cameras=[info['camera']])
        self.info = info

    def _stop_best_effort(self):
        try:
            self._request('POST', 'stop')
        except Exception:
            pass  # The independent owner watchdog remains responsible when CORE is unreachable.

    def get_observation(self):
        if not self.is_connected:
            raise RuntimeError('connect to CORE before reading an observation')
        self._observation_id = None
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    source = self._request('POST', 'observations', {'policy_revision': self.policy_revision})
                    break
                except CoreArmError as exc:
                    if exc.code != 'ARM_POLICY_BUSY' or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            if (source['policy_revision'] != self.policy_revision
                    or set(source['positions']) != set(self.info['joint_names'])
                    or _camera_layout(source.get('cameras') or [source['camera']])
                    != _camera_layout(self.info['cameras'])):
                raise ValueError('CORE observation differs from installed policy')
            self._observation_id = source['observation_id']
            return dict(source, cameras=source.get('cameras') or [source['camera']])
        except Exception:
            self._stop_best_effort()
            raise

    def send_action(self, positions):
        if not self.is_connected or self._observation_id is None:
            raise RuntimeError('a fresh CORE observation is required for each action')
        source, self._observation_id = self._observation_id, None
        try:
            result = self._request('POST', 'actions', dict(policy_revision=self.policy_revision,
                observation_id=source, positions=positions))
            if result.get('accepted') is not True:
                raise RuntimeError('CORE did not admit the arm action')
            return dict(positions)
        except Exception:
            self._stop_best_effort()
            raise

    def disconnect(self):
        if not self.is_connected:
            return
        self.info, self._observation_id = None, None
        self._request('POST', 'stop')
