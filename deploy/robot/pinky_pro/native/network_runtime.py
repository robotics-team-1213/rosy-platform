"""Installed, read-only evidence and narrow transport for network maintenance."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import secrets
import socket
import stat
import subprocess
import time

import rosy_claim
from network_handoff import write_override
from network_recovery import RecoveryState

UNITS = ('rosy-core.service', 'rosy-io.service', 'rosy-navigation.service')
RECOVERY_SOCKET = '/run/rosy-network-agent/recovery.sock'


def read_text(root, relative, limit=65536):
    """Fixed installed paths: no symlink component or unbounded file reads."""
    parts = Path(relative).parts
    if not parts or any(part in ('..', '/', '') for part in parts):
        return ''
    descriptor = None
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
        with os.fdopen(file_descriptor, 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return ''
            raw = handle.read(limit + 1)
        return raw.decode('utf-8') if len(raw) <= limit else ''
    except (OSError, UnicodeError):
        return ''
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_json(root, relative):
    try:
        value = json.loads(read_text(root, relative))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=4, **kwargs)


def unit_states(run=_run):
    try:
        result = run(['systemctl', 'show', '--property=Id,ActiveState', *UNITS])
        if result.returncode != 0:
            return {}
        values = {}
        for block in result.stdout.strip().split('\n\n'):
            fields = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            if fields.get('Id') in UNITS:
                values[fields['Id']] = fields.get('ActiveState')
        return values
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _idle_sample(root, now):
    data = read_json(root, 'run/rosy/status-inputs.json')
    try:
        written = datetime.fromisoformat(data['written_at'])
        if written.tzinfo is None or not -1 <= (now() - written).total_seconds() <= 15:
            return None
        required = {'robot_mode': 'IDLE', 'line_follow_mode': 'OFF', 'line_follow_state': 'OFF',
                    'swarm_active': False, 'estop': False, 'activity_kind': None}
        if any(key not in data or data[key] != value or (value is False and data[key] is not False)
               for key, value in required.items()):
            return None
        if data.get('swarm_role') not in (None, 'none') or data.get('nav_state') not in {'IDLE', 'ARRIVED', 'CANCELED', 'FAILED'}:
            return None
        if data.get('docking_state') not in {'UNDOCKED', 'DOCKED', 'CHARGING', None}:
            return None
        for field, bound in (('velocity_linear', .01), ('velocity_angular', .02)):
            value = data[field]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or abs(value) >= bound:
                return None
        return written
    except (KeyError, ValueError, TypeError):
        return None


def maintenance_ready(root=Path('/'), *, run=_run, sleep=time.sleep, now=lambda: datetime.now(timezone.utc)):
    env = dict(line.split('=', 1) for line in read_text(root, 'etc/rosy/runtime.env').splitlines()
               if '=' in line and not line.lstrip().startswith('#'))
    if env.get('ROSY_RUNTIME_MODE') != 'core' or env.get('ROSY_IO_DRIVE_ENABLED', 'false') != 'false':
        return False
    states = unit_states(run)
    if any(states.get(name) != 'inactive' for name in UNITS[1:]):
        return False
    if states.get(UNITS[0]) == 'inactive':
        return str(read_json(root, 'run/rosy-boot/boot-status.json').get('stage', '')).startswith('FAILED')
    if states.get(UNITS[0]) != 'active':
        return False
    first = _idle_sample(root, now)
    if first is None:
        return False
    sleep(10)
    second = _idle_sample(root, now)
    return bool(second and second > first and unit_states(run) == states)


@contextmanager
def maintenance_claim(root=Path('/')):
    holder = 'network-maintenance:' + secrets.token_hex(12)
    rosy_claim.acquire(Path(root), holder, 'authenticated network maintenance', 300, lock_wait_s=0)

    class Lease:
        def refresh(self):
            if not rosy_claim.refresh(Path(root), holder, 300):
                raise RuntimeError('claim_lost')

    try:
        yield Lease()
    finally:
        rosy_claim.release(Path(root), holder)


def hardware_serial(root):
    serial = read_text(root, 'sys/firmware/devicetree/base/serial-number').replace('\0', '').strip().lower()
    if not serial:
        serial = next((line.partition(':')[2].strip().lower()
                       for line in read_text(root, 'proc/cpuinfo').splitlines()
                       if line.lower().startswith('serial')), '')
    return serial


def recovery_state(root=Path('/'), *, run=_run):
    identity = read_json(root, 'etc/rosy/device-identity.json')
    binding = read_json(root, 'var/lib/rosy/provisioning/hardware-binding.json')
    network = read_json(root, 'run/rosy-boot/network.json')
    boot = read_json(root, 'run/rosy-boot/boot-status.json')
    provisioning = read_json(root, 'var/lib/rosy/provisioning/state.json')
    state = provisioning.get('reason') or provisioning.get('state', '')
    if str(boot.get('stage', '')).startswith('FAILED'):
        state = 'FAILED'
    if read_json(root, 'var/lib/rosy/provisioning/new-device-setup.json'):
        state = 'SETUP'
    serial = binding.get('hardware_serial', '') if binding.get('device_uid') == identity.get('device_uid') else ''
    supported = ('NETWORK_HANDOFF_SCHEMA = 1' in read_text(root, 'opt/rosy/first-boot/rosy-first-boot.py')
                 and bool(read_text(root, 'opt/rosy/native-runtime/network_handoff.py')))
    states = unit_states(run)
    return RecoveryState(
        boot_id=read_text(root, 'proc/sys/kernel/random/boot_id', 128).strip(),
        ap_epoch=str(network.get('epoch', '')) if network.get('mode') == 'ap' else '',
        ap_address=network.get('address', '') if network.get('mode') == 'ap' else '',
        device_uid=identity.get('device_uid', ''), identity_serial=serial,
        hardware_serial=hardware_serial(root), firstboot_state=state,
        core_healthy=states.get(UNITS[0]) == 'active' and boot.get('stage') == 'CORE_READY',
        handoff_supported=supported)


def commit_handoff(root, record):
    payload = read_json(root, 'boot/firmware/rosy-provision/provision.json')
    if not payload:
        # Already-personalized devices need no one-time-bundle handoff.
        if read_json(root, 'var/lib/rosy/provisioning/complete.json'):
            return
        raise ValueError('network_handoff_bundle_unavailable')
    identity = read_json(root, 'etc/rosy/device-identity.json')
    binding = read_json(root, 'var/lib/rosy/provisioning/hardware-binding.json')
    if (payload.get('device_identity', {}).get('device_uid') != identity.get('device_uid')
            or binding.get('device_uid') != identity.get('device_uid')
            or binding.get('hardware_serial') != hardware_serial(root)):
        raise ValueError('network_handoff_identity_mismatch')
    write_override(root, device_uid=identity['device_uid'], hardware_serial=binding['hardware_serial'],
                   bundle_checksum=payload.get('payload_checksum'), transaction=record)


def network_request(command, params=None, *, socket_path=RECOVERY_SOCKET):
    if command not in {'network.status', 'network.connect', 'network.start'}:
        raise ValueError('network_command_refused')
    params = dict(params or {})
    key = params.get('request_id') or secrets.token_hex(16)
    wire_params = dict(params)
    if command == 'network.connect':
        wire_params.pop('request_id', None)
    request = {'schema_version': 1, 'request_id': secrets.token_hex(16), 'command': command,
               'idempotency_key': key if command == 'network.connect' else command + '.' + secrets.token_hex(8),
               'actor': {'user_id': 'local-network-recovery', 'role': 'administrator'},
               'confirmed': True, **({'params': wire_params} if wire_params else {})}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(str(socket_path))
        connection.sendall(json.dumps(request).encode() + b'\n')
        reply = b''
        while b'\n' not in reply and len(reply) <= 65536:
            chunk = connection.recv(4096)
            if not chunk:
                break
            reply += chunk
    if len(reply) > 65536 or not reply.endswith(b'\n'):
        raise RuntimeError('network_response_invalid')
    response = json.loads(reply)
    if (not isinstance(response, dict) or response.get('ok') is not True
            or response.get('request_id') != request['request_id']
            or not isinstance(response.get('data'), dict)):
        raise RuntimeError('network_request_refused')
    return response.get('data') or {}


def recovery_snapshot(root=Path('/')):
    return asdict(recovery_state(root))
