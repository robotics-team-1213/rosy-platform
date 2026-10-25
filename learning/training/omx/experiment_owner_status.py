"""Read-only Fleet owner observations; no control, feedback-freshness or stop proof."""
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
import re
import socket
import threading
import time
import urllib.parse
import uuid


class OwnerStatus:
    def __init__(self, config):
        self.targets = {}
        if config is None:
            return
        if not isinstance(config, dict) or set(config) != {'origin', 'token_env', 'targets', 'timeout_s'}:
            raise ValueError('explicit read-only owner status configuration required')
        if not isinstance(config['origin'], str):
            raise ValueError('numeric HTTP loopback Fleet tunnel origin required')
        url = urllib.parse.urlsplit(config['origin'])
        if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', '::1') or not url.port
                or url.username is not None or url.password is not None
                or url.path not in ('', '/') or url.query or url.fragment):
            raise ValueError('numeric HTTP loopback Fleet tunnel origin required')
        if (not isinstance(config['token_env'], str)
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', config['token_env'])):
            raise ValueError('viewer token environment variable name required')
        timeout = config['timeout_s']
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3:
            raise ValueError('owner query timeout must be finite and within 3 seconds')
        targets = config['targets']
        if not isinstance(targets, dict) or not 1 <= len(targets) <= 32:
            raise ValueError('one to 32 configured owner targets required')
        for workcell, instance in targets.items():
            if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}', v)
                   for v in (workcell, instance)):
                raise ValueError('explicit plain workcell/instance identifiers required')
        if len(set(targets.values())) != len(targets):
            raise ValueError('owner target instances must be distinct')
        self.targets = dict(targets)
        self.host, self.port, self.token_env, self.timeout = url.hostname, url.port, config['token_env'], timeout

    def _fetch(self, workcell_id, token, started):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        timer = None
        try:
            connection.connect()
            transport = connection.sock
            remaining = self.timeout-(time.monotonic()-started)
            if remaining <= 0:
                raise TimeoutError('owner query deadline exceeded')
            transport.settimeout(remaining)
            def expire():
                # shutdown interrupts response makefile reads even after HTTPConnection drops its socket reference.
                try:
                    transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            timer = threading.Timer(remaining, expire)
            timer.daemon = True
            timer.start()
            connection.request('GET', '/api/fleet/workcells/' + workcell_id + '/owner',
                headers={'Authorization': 'Bearer ' + token, 'Cache-Control': 'no-cache'})
            with connection.getresponse() as response:
                if response.status != 200:
                    raise ValueError('owner query unavailable')
                return response.read(65537)
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()
            if timer is not None:
                timer.join()

    def describe(self):
        return {'configured': bool(self.targets), 'physical_control_available': False,
                'targets': [{'workcell_id': cell, 'instance_id': arm} for cell, arm in self.targets.items()]}

    def read(self, workcell_id):
        if workcell_id not in self.targets:
            raise ValueError('configured owner target required')
        result = dict(workcell_id=workcell_id, instance_id=self.targets[workcell_id],
                      source='fleet_owner_state', query_id=str(uuid.uuid4()),
                      physical_control_available=False, feedback_freshness_verified=False)
        try:
            token = os.environ.get(self.token_env, '')
            if not token or len(token) > 16384 or any(ord(c) <= 32 or ord(c) >= 127 for c in token):
                return dict(result, status='unavailable', reason='VIEWER_CREDENTIAL_UNAVAILABLE')
            started = time.monotonic()
            raw = self._fetch(workcell_id, token, started)
            elapsed = time.monotonic()-started
            if elapsed < 0 or elapsed > self.timeout or len(raw) > 65536:
                raise ValueError('bounded timely owner readback required')
            payload = json.loads(raw)
            if (not isinstance(payload, dict) or set(payload) != {'version', 'status', 'workcell_id', 'instance_id', 'owner'}
                    or type(payload['version']) is not int or payload['version'] != 1
                    or type(payload['status']) is not int or payload['status'] != 200
                    or payload['workcell_id'] != workcell_id or payload['instance_id'] != self.targets[workcell_id]):
                raise ValueError('owner reply identity/schema differs')
            owner = payload['owner']
            if (not isinstance(owner, dict) or set(owner) != {'state', 'reason', 'observed_sequence'}
                    or owner['state'] not in ('disabled', 'ready', 'active', 'hold')
                    or owner['reason'] is not None and (not isinstance(owner['reason'], str)
                        or len(owner['reason']) > 256 or any(ord(c) < 32 for c in owner['reason']))
                    or owner['observed_sequence'] is not None and (
                        type(owner['observed_sequence']) is not int or not 0 <= owner['observed_sequence'] <= 2**63-1)):
                raise ValueError('owner readback fields invalid')
            return dict(result, status='observed', owner=owner,
                        received_at=datetime.now(timezone.utc).isoformat(), elapsed_ms=elapsed*1000,
                        response_sha256=hashlib.sha256(raw).hexdigest())
        except (OSError, ValueError, http.client.HTTPException):
            return dict(result, status='unavailable', reason='OWNER_READBACK_UNAVAILABLE')
