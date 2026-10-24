"""Device-bound committed Wi-Fi evidence for interrupted first boot."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from network_transaction import _read, _secure_dir, _write, change_lock

SCHEMA = 1
OVERRIDE = 'var/lib/rosy/network/first-boot-override.json'


def write_override(root, *, device_uid, hardware_serial, bundle_checksum, transaction):
    if not all(isinstance(value, str) and value for value in (device_uid, hardware_serial, bundle_checksum)):
        raise ValueError('network_handoff_identity_invalid')
    _secure_dir(root, 'var/lib/rosy/network')
    _write(Path(root) / OVERRIDE, {
        'schema': SCHEMA, 'device_uid': device_uid, 'hardware_serial': hardware_serial,
        'bundle_checksum': bundle_checksum, 'request_id': transaction['request_id'],
        'profile_uuid': transaction['profile_uuid'], 'ssid': transaction['ssid'],
    })


def resolve_override(root, *, device_uid, hardware_serial, bundle_checksum, inspect_profile):
    _secure_dir(root, 'var/lib/rosy/network')
    record = _read(Path(root) / OVERRIDE)
    if record is None:
        return None
    expected = {'schema': SCHEMA, 'device_uid': device_uid,
                'hardware_serial': hardware_serial, 'bundle_checksum': bundle_checksum}
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError('network_handoff_identity_mismatch')
    key = record.get('request_id')
    from network_transaction import REQUEST_ID
    if not isinstance(key, str) or not REQUEST_ID.fullmatch(key):
        raise ValueError('network_handoff_job_invalid')
    current = _read(Path(root) / 'var/lib/rosy/network/transaction.json')
    if not current or current.get('request_id') != key:
        current = _read(Path(root) / 'var/lib/rosy/network/jobs' / (key + '.json'))
    if (not current or current.get('state') != 'committed'
            or any(current.get(name) != record.get(name) for name in ('request_id', 'profile_uuid', 'ssid'))):
        raise ValueError('network_handoff_not_committed')
    observed = inspect_profile(record['profile_uuid'])
    if (not isinstance(observed, dict) or observed.get('active') is not True
            or observed.get('uuid') != record['profile_uuid'] or observed.get('ssid') != record['ssid']
            or not observed.get('ipv4')):
        raise ValueError('network_handoff_not_observed')
    return record


def consume_override(root):
    path = Path(root) / OVERRIDE
    if path.is_symlink():
        raise ValueError('network_handoff_unsafe_path')
    path.unlink(missing_ok=True)


@contextmanager
def first_boot_network(root):
    """Use the same claim→radio-lock order as maintenance and the updater."""
    import rosy_claim
    _secure_dir(root, 'run/rosy-network')
    import secrets
    holder = 'first-boot-network:' + secrets.token_hex(12)
    try:
        rosy_claim.acquire(Path(root), holder, 'first boot network handoff', 300, lock_wait_s=0)
    except rosy_claim.ClaimBusy:
        raise ValueError('network_change_in_progress') from None
    try:
        with change_lock(root, blocking=False) as acquired:
            if not acquired:
                raise ValueError('network_change_in_progress')
            yield
    finally:
        rosy_claim.release(Path(root), holder)
