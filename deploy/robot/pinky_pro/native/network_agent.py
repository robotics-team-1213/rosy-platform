"""Network-only authority: prepare a job, then start after the HTTP reply."""
from __future__ import annotations

from contextvars import ContextVar
import json
from pathlib import Path
import threading

from host_agent import HostAgent, MAX_REQUEST_BYTES
from network_transaction import REQUEST_ID, _read, _secure_dir, _write, validate_request

_request_id = ContextVar('network_request_id', default=None)
_status_id = ContextVar('network_status_id', default=None)
COMMANDS = ('network.status', 'network.connect', 'network.start')


def _background(work):
    threading.Thread(target=work, daemon=True, name='rosy-network-change').start()


class NetworkCommands:
    def __init__(self, transaction, *, root=Path('/'), submit=_background, recovery_state=None):
        self.transaction = transaction
        self.root = Path(root)
        self.submit = submit
        self.recovery_state = recovery_state
        self._pending = {}
        self._running = set()
        self._guard = threading.RLock()

    def _queue(self):
        return _secure_dir(self.root, 'var/lib/rosy/network') / 'queue.json'

    def connect_wifi(self, ssid, psk):
        key = _request_id.get()
        validate_request(ssid, psk, key)
        with self._guard:
            old = _read(self._queue())
            if old and old.get('request_id') != key and (self._pending or self._running):
                return {'state': 'busy', 'code': 'network_busy'}
            if old and old.get('request_id') == key and old.get('ssid') != ssid:
                raise ValueError('request_identity_conflict')
            previous = self._pending.get(key)
            if previous is not None and previous != (ssid, psk):
                raise ValueError('request_identity_conflict')
            status = self.transaction.status(key)
            if status.get('state') in {'committed', 'rolled_back', 'rejected'}:
                return status
            self._pending[key] = (ssid, psk)
            prepared = {'state': 'prepared', 'job_id': key, 'request_id': key, 'ssid': ssid}
            _write(self._queue(), prepared)
            return prepared

    def start_network(self, request_id):
        # Only an authenticated caller may acknowledge; never restart a lost PSK.
        with self._guard:
            if request_id in self._running:
                return {'state': 'running', 'request_id': request_id}
            values = self._pending.pop(request_id, None)
            if values is None:
                known = self.transaction.status(request_id)
                if known.get('state') in {'committed', 'rolled_back', 'rejected'}:
                    return known
                return {'state': 'needs_resubmit', 'request_id': request_id}
            self._running.add(request_id)

            def work():
                try:
                    result = self.transaction.connect(*values, request_id=request_id)
                    with self._guard:
                        blocked = result.get('request_id')
                        queued = {**result, 'request_id': request_id, 'job_id': request_id}
                        if blocked and blocked != request_id:
                            queued['blocked_request_id'] = blocked
                        _write(self._queue(), queued)
                finally:
                    with self._guard:
                        self._running.discard(request_id)

            try:
                self.submit(work)
            except Exception:
                self._running.discard(request_id)
                raise RuntimeError('network_job_start_failed') from None
            return {'state': 'running', 'request_id': request_id}

    def network_status(self):
        with self._guard:
            queued = _read(self._queue())
            key = _status_id.get() or (queued.get('request_id') if queued else None)
            current = self.transaction.status(key) if key else self.transaction.status()
            if queued and key == queued.get('request_id') and current.get('state') in {'idle', 'unknown'}:
                state = queued.get('state')
                if state == 'prepared' and key not in self._pending:
                    state = 'needs_resubmit'
                current = {**queued, 'state': state}
            if self.recovery_state is not None:
                current = {**current, 'recovery': self.recovery_state()}
            return current


class _NetworkAgent(HostAgent):
    def handle(self, raw):
        envelope = raw
        if isinstance(raw, (str, bytes)) and len(raw) <= MAX_REQUEST_BYTES:
            try:
                envelope = json.loads(raw)
            except (ValueError, UnicodeError):
                envelope = None
        status_key = None
        if isinstance(envelope, dict) and envelope.get('command') == 'network.status':
            params = envelope.get('params')
            if isinstance(params, dict) and set(params) == {'request_id'}:
                candidate = params['request_id']
                if isinstance(candidate, str) and REQUEST_ID.fullmatch(candidate):
                    status_key = candidate
                    raw = {**envelope, 'params': {}}
        key = (envelope.get('idempotency_key') or envelope.get('request_id')) if isinstance(envelope, dict) else None
        # Transaction identity is durable; recheck authorization on every retry.
        if isinstance(envelope, dict):
            raw = dict(raw if isinstance(raw, dict) else envelope)
            raw.pop('idempotency_key', None)
        token = _request_id.set(key)
        status_token = _status_id.set(status_key)
        try:
            return super().handle(raw)
        finally:
            _request_id.reset(token)
            _status_id.reset(status_token)


def make_agent(commands, *, audit=None):
    return _NetworkAgent(commands, allowed_profiles=(), allowed_units=(),
                         allowed_commands=COMMANDS, audit=audit)
