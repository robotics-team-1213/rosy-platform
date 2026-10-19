"""D-804 device-pulled SIM lease; Fleet delivery markers remain server observations."""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
import time
from urllib.parse import quote, urlsplit

from rosy.contracts.skill import AttemptIdentity
from .omx_policy import PolicyLease

MAX_LEASE_DURATION_NS = 1_000_000_000
MAX_HTTP_TIMEOUT_S = .25


@dataclass(frozen=True)
class LeaseScope:
    identity: AttemptIdentity
    episode_id: str
    policy_revision: str
    owner_session_id: str
    window_id: str
    rig_revision: str
    calibration_revision: str
    approval_scope: str

    def __post_init__(self):
        if not isinstance(self.identity, AttemptIdentity):
            raise ValueError('trusted local SIM attempt identity required')
        for name in ('episode_id', 'policy_revision', 'owner_session_id', 'window_id',
                     'rig_revision', 'calibration_revision', 'approval_scope'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError('explicit pinned SIM lease scope required')


_HTTP_EXCHANGE = '''
import json, sys
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None
opener = build_opener(ProxyHandler({}), NoRedirect())
print('READY', flush=True)
for line in sys.stdin:
    try:
        call = json.loads(line)
        payload = None if call['body'] is None else json.dumps(call['body'], allow_nan=False).encode()
        request = Request(call['url'], payload, method=call['method'],
            headers={'Authorization': 'Bearer '+call['token'], 'Content-Type': 'application/json'})
        with opener.open(request, timeout=call['timeout']) as response:
            raw = response.read(1024*1024+1)
            if response.status != 200 or len(raw) > 1024*1024: raise ValueError()
            value = json.loads(raw)
            if not isinstance(value, dict): raise ValueError()
        print(json.dumps({'id':call['id'], 'value':value}, allow_nan=False), flush=True)
    except Exception:
        sys.exit(1)
'''


class FleetPolicyHttp:
    """POSIX device context; prepare stdlib before leases, bound each HTTP exchange."""
    def __init__(self, origin, token_file, *, loopback_sim=False, timeout_s=.2):
        parsed = urlsplit(origin)
        loopback = parsed.hostname in ('localhost', '127.0.0.1', '::1')
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                or (parsed.scheme == 'http' and not (loopback_sim is True and loopback))
                or type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
                or not 0 < timeout_s <= MAX_HTTP_TIMEOUT_S):
            raise ValueError('fixed authenticated TLS origin or explicit loopback SIM required')
        parsed.port  # Validate the port before using any credential.
        self.origin, self.token_file = origin.rstrip('/'), Path(token_file)
        self.timeout_s = timeout_s
        self._process, self._closed = None, False
        self._io_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._sequence = 0

    def __enter__(self):
        with self._io_lock:
            try:
                with self._state_lock:
                    if os.name != 'posix' or self._closed or self._process is not None:
                        raise PermissionError('one prepared POSIX transport context required')
                    self._process = subprocess.Popen([sys.executable, '-I', '-S', '-c', _HTTP_EXCHANGE],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
                for pipe in (self._process.stdin, self._process.stdout):
                    os.set_blocking(pipe.fileno(), False)
                if self._line(time.monotonic()+2) != b'READY':
                    raise ValueError('invalid helper preparation')
                with self._state_lock:
                    if self._closed:
                        raise PermissionError('Fleet transport closed during preparation')
                    return self
            except Exception:
                self.close()
                raise PermissionError('Fleet transport preparation failed') from None

    def _line(self, deadline, payload=b''):
        result = bytearray()
        child = self._process
        with selectors.DefaultSelector() as selector:
            if payload:
                selector.register(child.stdin, selectors.EVENT_WRITE)
                while payload:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError('Fleet exchange deadline')
                    try:
                        written = os.write(child.stdin.fileno(), payload)
                    except BlockingIOError:
                        continue
                    if written <= 0:
                        raise OSError('Fleet helper closed')
                    payload = payload[written:]
                selector.unregister(child.stdin)
            selector.register(child.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline-time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError('Fleet exchange deadline')
                try:
                    chunk = os.read(child.stdout.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    raise OSError('Fleet helper closed')
                result.extend(chunk)
                if len(result) > 6*1024*1024+1024:
                    raise ValueError('oversized helper framing')
                if b'\n' in result:
                    line, _, extra = result.partition(b'\n')
                    if extra:
                        raise ValueError('unexpected helper output')
                    return bytes(line)

    def close(self):
        with self._state_lock:
            self._closed = True
            child = self._process
            if child is not None:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=.5)
        # Reap first to interrupt I/O; retain descriptors until its owner drains.
        with self._io_lock:
            if child is not None:
                child.stdin.close()
                child.stdout.close()

    def __exit__(self, *args):
        self.close()

    def __call__(self, method, path, body=None):
        if method not in ('GET', 'POST') or not path.startswith('/api/fleet/workcells/'):
            raise ValueError('Fleet policy operation required')
        if self._closed or self._process is None or not self._io_lock.acquire(blocking=False):
            raise PermissionError('prepared exclusive Fleet transport required')
        try:
            with self._state_lock:
                if self._closed:
                    raise PermissionError('Fleet transport closed')
            deadline = time.monotonic()+self.timeout_s
            token = self.token_file.read_text(encoding='ascii').strip()
            if not token or len(token) > 8192 or any(c.isspace() for c in token):
                raise ValueError('invalid credential file')
            self._sequence += 1
            call = dict(id=self._sequence,url=self.origin+path,method=method,body=body,
                        token=token,timeout=self.timeout_s)
            payload = json.dumps(call, allow_nan=False).encode()+b'\n'
            reply = json.loads(self._line(deadline, payload))
            if (not isinstance(reply, dict) or set(reply) != {'id','value'}
                    or type(reply['id']) is not int or reply['id'] != self._sequence
                    or not isinstance(reply['value'], dict) or time.monotonic() >= deadline):
                raise ValueError('Fleet object response required')
            with self._state_lock:
                if self._closed:
                    raise PermissionError('Fleet transport closed')
                return reply['value']
        except Exception:
            self.close()
            raise PermissionError('Fleet policy transport refused or unavailable') from None
        finally:
            self._io_lock.release()


class FleetLeaseConsumer:
    """One scoped SIM lease, no retries/rearm; ROS authority reads memory only."""
    def __init__(self, scope, *, request, monotonic, max_duration_ns=MAX_LEASE_DURATION_NS):
        if (not isinstance(scope, LeaseScope) or not callable(request) or not callable(monotonic)
                or type(max_duration_ns) is not int or not 0 < max_duration_ns <= MAX_LEASE_DURATION_NS
                or max_duration_ns % 1_000_000):
            raise ValueError('trusted scope, transport, clock and bounded lease budget required')
        self.scope, self.request, self.monotonic = scope, request, monotonic
        self.max_duration_ns = max_duration_ns
        self._lock, self._refresh_lock = threading.RLock(), threading.Lock()
        self._current = self._pending = self._wire = None
        self._last_now = None
        self._closed = False
        self.path = '/api/fleet/workcells/'+quote(scope.identity.workcell_id, safe='')+'/policy'

    def _now(self):
        value = self.monotonic()
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value < 2**63/1e9:
            raise PermissionError('invalid local monotonic clock')
        return int(value*1e9)

    def close(self):
        with self._lock:
            self._closed = True
            self._pending = None

    def _open(self):
        now = self._now()
        if self._closed or (self._last_now is not None and now < self._last_now):
            self._closed = True
            raise PermissionError('SIM lease authority is permanently closed')
        self._last_now = now
        return now

    def authority(self, lease):
        with self._lock:
            try:
                now = self._open()
                if self._current is None or not self._current.issued_at_ns <= now < self._current.expires_at_ns:
                    self.close()
                    return False
                return ((lease == self._current or lease == self._pending)
                        and lease.issued_at_ns <= now < lease.expires_at_ns)
            except Exception:
                self.close()
                return False

    def _approval(self, state):
        scope = self.scope
        windows = [w for w in state['windows'] if w['window_id'] == scope.window_id]
        stages = [p for p in state['policies'] if p['policy_revision'] == scope.policy_revision]
        if state['workcell_id'] != scope.identity.workcell_id or len(windows) != 1 or len(stages) != 1:
            raise PermissionError('Fleet approval scope differs')
        window, stage = windows[0], stages[0]
        if (window['active'] is not True or not window['approved_by'] or window['closed_ns'] is not None
                or window['policy_revision'] != scope.policy_revision or window['scope'] != scope.approval_scope
                or window['kind'] not in ('supervised', 'limited')
                or stage['stage'] not in (('L3', 'LIMITED') if window['kind'] == 'supervised' else ('LIMITED',))
                or stage['rig_revision'] != scope.rig_revision
                or stage['calibration_revision'] != scope.calibration_revision
                or type(state['now_ns']) is not int or type(window['expires_ns']) is not int
                or window['expires_ns'] <= state['now_ns']
                or any(row['resolution'] is None for row in state['confirmations'])
                or any(row['cleared_ns'] is None for row in state['incidents'])):
            raise PermissionError('Fleet approval or installed SIM scope differs')
        return window

    def _fetch(self, old):
        with self._lock:
            started = self._open()
            if old is not self._current or (old is not None and not self.authority(old)):
                raise PermissionError('current scoped lease required')
        scope = self.scope
        before = self.request('GET', self.path)
        self._approval(before)
        body = dict(episode_id=scope.episode_id, owner_session_id=scope.owner_session_id,
                    duration_ms=self.max_duration_ns//1_000_000)
        if old is not None:
            body['lease_id'] = old.lease_id
        wire = self.request('POST', self.path+'/lease', body)
        after = self.request('GET', self.path)
        window = self._approval(after)
        expected = dict(workcell_id=scope.identity.workcell_id, window_id=scope.window_id,
            policy_revision=scope.policy_revision, episode_id=scope.episode_id,
            owner_session_id=scope.owner_session_id, clock='fleet_wall_ns')
        issued, expires = wire['issued_ns'], wire['expires_ns']
        if (any(wire.get(k) != v for k, v in expected.items())
                or not isinstance(wire['lease_id'], str) or not wire['lease_id'].strip()
                or type(issued) is not int or type(expires) is not int
                or not 0 <= issued < expires < 2**63 or expires > window['expires_ns']
                or not before['now_ns'] <= issued <= after['now_ns'] < expires
                or not 0 < expires-issued <= self.max_duration_ns
                or (old is not None and (wire['lease_id'] != old.lease_id
                    or issued <= self._wire[0] or expires <= self._wire[1]))):
            raise PermissionError('Fleet lease scope, duration or renewal sequence differs')
        lease = PolicyLease(wire['lease_id'], scope.episode_id, scope.policy_revision, scope.identity,
            started, started+expires-issued, scope.owner_session_id)
        with self._lock:
            if self._open() >= lease.expires_at_ns or (old is not None and not self.authority(old)):
                raise PermissionError('lease expired during authenticated round trip')
        return lease, (issued, expires)

    def acquire(self):
        with self._refresh_lock:
            try:
                with self._lock:
                    if self._current is not None:
                        raise PermissionError('SIM lease already acquired')
                lease, stamp = self._fetch(None)
                with self._lock:
                    self._open()
                    self._current, self._wire = lease, stamp
                return lease
            except Exception:
                self.close()
                raise PermissionError('SIM lease acquisition failed closed') from None

    def renew(self, session):
        with self._refresh_lock:
            try:
                old = session.lease
                lease, stamp = self._fetch(old)
                with self._lock:
                    self._open()
                    self._pending = lease
                # Session validates BOTH old and new leases, without holding our lock.
                session.renew(lease)
                with self._lock:
                    self._open()
                    self._current, self._pending, self._wire = lease, None, stamp
                return lease
            except Exception:
                self.close()
                raise PermissionError('SIM lease renewal failed closed') from None
