"""Operator-only signed transport repair; never installs an OS or executes candidate code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys

PREFIX = 'opt/rosy/os-bootstrap/native-runtime'
PUBLIC_KEY = 'etc/rosy/trusted-release-keys/rosy-release-2026-01.pem'
COMMON = 'var/lib/rosy-device'
CONFIG = COMMON + '/policy/updates/config.json'
FILES = ('os_update_feed.py', 'os_update_stage.py', 'os_update_transport.py')
BASE_SOURCE = '28f95ef47e45c6346196dbdf173026954e73c63d'  # Public Git commit of the supported factory image.
BASE_RELEASE = '2026.10.28-172'
MAX_FILE = 1024 * 1024
FIELDS = {'schema_version', 'kind', 'base_release_id', 'base_source_revision', 'source_revision',
          'canary', 'installer_sha256', 'files'}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def pairs(items):
        value = {}
        for name, item in items:
            if name in value: raise ValueError('duplicate repair field')
            value[name] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs)


def _read(path, limit, owner=None):
    for parent in (path, *path.parents):
        if parent.is_symlink(): raise ValueError('symlink in repair path')
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit or info.st_mode & 0o7000
                or owner is not None and (info.st_uid != owner or info.st_mode & 0o022)):
            raise ValueError('unsafe repair file')
        raw = stream.read(limit + 1)
    if len(raw) > limit: raise ValueError('repair file exceeds bound')
    return raw


def validate_package(package, public_key, *, owner=None):
    """Capture authenticated bytes; callers never reopen mutable payload paths to install them."""
    from signing import verify_signature
    package = Path(package).absolute()
    names = {*FILES, 'os_transport_repair.py', 'transport-repair.json', 'transport-repair.json.sig'}
    if package.is_symlink() or not package.is_dir() or {p.name for p in package.iterdir()} != names:
        raise ValueError('repair package must contain exactly the fixed signed set')
    raw = _read(package / 'transport-repair.json', 16384, owner)
    sig = _read(package / 'transport-repair.json.sig', 512, owner).decode('ascii').strip()
    if verify_signature(raw, sig, public_key): raise ValueError('untrusted transport repair')
    value = _json(raw)
    if (not isinstance(value, dict) or set(value) != FIELDS or type(value['schema_version']) is not int
            or value['schema_version'] != 1 or value['kind'] != 'os-transport-repair'
            or value['base_source_revision'] != BASE_SOURCE or value['base_release_id'] != BASE_RELEASE
            or not isinstance(value['source_revision'], str) or not re.fullmatch('[0-9a-f]{40}', value['source_revision'])
            or not isinstance(value['canary'], list) or not 1 <= len(value['canary']) <= 128
            or any(not isinstance(n, str) or not 1 <= len(n) <= 253 or any(
                not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in n.split('.')) for n in value['canary'])
            or len(set(value['canary'])) != len(value['canary'])
            or not isinstance(value['files'], dict) or set(value['files']) != set(FILES)):
        raise ValueError('invalid transport repair manifest')
    installer = _read(package / 'os_transport_repair.py', MAX_FILE, owner)
    if value['installer_sha256'] != _sha(installer): raise ValueError('repair installer digest differs')
    payload = {}
    for name in FILES:
        record = value['files'][name]
        if (not isinstance(record, dict) or set(record) != {'size_bytes', 'sha256', 'preimage_sha256'}
                or type(record['size_bytes']) is not int or not 0 < record['size_bytes'] <= MAX_FILE
                or not isinstance(record['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', record['sha256'])
                or (record['preimage_sha256'] is None) != (name == FILES[-1])
                or record['preimage_sha256'] is not None and not re.fullmatch('[0-9a-f]{64}', str(record['preimage_sha256']))):
            raise ValueError('invalid fixed repair file binding')
        content = _read(package / name, MAX_FILE, owner)
        if len(content) != record['size_bytes'] or _sha(content) != record['sha256']:
            raise ValueError('repair payload differs from signature')
        payload[name] = content
    return value, raw, payload


def _atomic(path, raw, mode):
    from os_state_io import _write_atomic
    _write_atomic(path, raw, mode)


def _save(path, value):
    _atomic(path, (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode(), 0o600)


def _run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)


def _admit(root, value, run):
    import os_update_controller as controller
    facts, state, _ = controller._snapshot(root)
    if (state['pending'] is not None or facts['tryboot'] != 0
            or state['committed']['release_id'] != value['base_release_id']
            or facts['slot'] != state['committed']['slot'] or socket.gethostname() not in value['canary']):
        raise ValueError('transport repair requires the named stable factory boot')
    observed = run(['/usr/bin/systemctl', 'show', 'rosy-os-update.service',
                    '-p', 'ActiveState', '-p', 'MainPID', '-p', 'ControlPID'])
    if observed.returncode != 0: raise ValueError('cannot observe OS update service')
    fields = dict(line.split('=', 1) for line in observed.stdout.strip().splitlines())
    if (set(fields) != {'ActiveState', 'MainPID', 'ControlPID'} or fields['ActiveState'] not in ('inactive', 'failed')
            or fields['MainPID'] != '0' or fields['ControlPID'] != '0'):
        raise ValueError('OS update service is not idle')
    layout = controller._layout(root)[0]
    return layout['root_partuuid']


def _current(root, path):
    from os_state_layout import _path
    path = _path(root, path.relative_to(root).as_posix())
    return _sha(_read(path, MAX_FILE, root.stat().st_uid)) if path.exists() else None


def _record(root, directory, raw, identity):
    path = directory / 'journal.json'
    if not path.exists(): return None
    data = _json(_read(path, 65536, root.stat().st_uid))
    if (not isinstance(data, dict) or set(data) != {'schema_version', 'manifest_sha256', 'root_partuuid', 'phase',
            'policy_sha256', 'disabled_sha256', 'policy_mode', 'file_modes'} or type(data['schema_version']) is not int or data['schema_version'] != 1
            or data['manifest_sha256'] != _sha(raw) or data['root_partuuid'] != identity
            or data['phase'] not in ('PREPARED', 'COMMIT_INTENT', 'COMPLETE', 'ROLLED_BACK')
            or not isinstance(data['file_modes'], dict) or set(data['file_modes']) != set(FILES)):
        raise ValueError('repair journal differs from the authenticated transaction')
    for mode in [data['policy_mode'], *data['file_modes'].values()]:
        if type(mode) is not int or not 0 <= mode <= 0o777 or mode & 0o022:
            raise ValueError('unsafe repair restoration mode')
    return data


def _policy(root, directory, record):
    original = _read(directory / 'config.backup', 65536, root.stat().st_uid)
    if _sha(original) != record['policy_sha256']: raise ValueError('policy backup changed')
    data = _json(original)
    if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
        raise ValueError('explicit updater policy required')
    disabled = (json.dumps(dict(data, enabled=False), sort_keys=True, separators=(',', ':')) + '\n').encode()
    if _sha(disabled) != record['disabled_sha256']: raise ValueError('disabled policy binding changed')
    current = _read(root / CONFIG, 65536, root.stat().st_uid)
    if current not in (original, disabled): raise ValueError('operator policy changed during repair; HOLD')
    return original, disabled


def _finish(root, directory, record, value):
    for name in FILES:
        if _current(root, root / PREFIX / name) != value['files'][name]['sha256']:
            raise ValueError('committing repair file changed; HOLD')
    original, _ = _policy(root, directory, record)
    _atomic(root / CONFIG, original, record['policy_mode'])
    record['phase'] = 'COMPLETE'
    _save(directory / 'journal.json', record)
    return dict(phase='COMPLETE', source_revision=value['source_revision'])


def _operate(root, package, *, run, recovering):
    root = Path(root).absolute()
    if root != Path('/') and run is _run: raise ValueError('fake root requires an explicit modeled runner')
    from os_state_layout import _path
    import os_update_controller as controller
    import rosy_claim
    authority = _path(root, PUBLIC_KEY)
    _read(authority, 16384, root.stat().st_uid)
    value, raw, payload = validate_package(package, authority, owner=root.stat().st_uid)
    with controller._locks(root):
        identity = _admit(root, value, run)
        prefix = _path(root, PREFIX)
        if not prefix.is_dir(): raise ValueError('frozen runtime directory missing')
        directory = _path(root, COMMON + '/os-update/transport-repair/' + identity)
        if directory.exists() and (not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) != 0o700):
            raise ValueError('repair directory must be private')
        record = _record(root, directory, raw, identity) if directory.exists() else None
        holder = 'os-transport:' + value['source_revision'][:16] + ':' + identity[:8]
        claim = rosy_claim.check(root)
        if claim is not None and claim['holder'] != holder: raise ValueError('another owner holds the device')
        if claim is None: rosy_claim.acquire(root, holder, 'signed OS transport repair', 300)
        elif not rosy_claim.refresh(root, holder, 300): raise ValueError('repair claim expired')
        try:
            if record is not None and record['phase'] == 'COMPLETE':
                for name in FILES:
                    if _current(root, prefix / name) != value['files'][name]['sha256']:
                        raise ValueError('completed repair was changed')
                return dict(phase='COMPLETE', source_revision=value['source_revision'])
            if recovering:
                if record is None: raise ValueError('no signed repair journal to recover')
                original, disabled = _policy(root, directory, record)
                if record['phase'] == 'COMMIT_INTENT': return _finish(root, directory, record, value)
                # Authenticate every rollback input before changing any target.
                backups = {}
                for name in FILES:
                    expected = value['files'][name]
                    if _current(root, prefix / name) not in (expected['preimage_sha256'], expected['sha256']):
                        raise ValueError('unknown target contents during recovery; HOLD')
                    backups[name] = None if expected['preimage_sha256'] is None else _read(directory / (name + '.backup'), MAX_FILE, root.stat().st_uid)
                    if backups[name] is not None and _sha(backups[name]) != expected['preimage_sha256']:
                        raise ValueError('repair backup differs from signed preimage')
                _atomic(root / CONFIG, disabled, record['policy_mode'])
                for name, content in backups.items():
                    target = _path(root, PREFIX + '/' + name)
                    if content is None:
                        target.unlink(missing_ok=True)
                        descriptor = os.open(prefix, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                        try: os.fsync(descriptor)
                        finally: os.close(descriptor)
                    else: _atomic(target, content, record['file_modes'][name])
                record['phase'] = 'ROLLED_BACK'
                _save(directory / 'journal.json', record)
                _atomic(root / CONFIG, original, record['policy_mode'])
                return dict(phase='ROLLED_BACK', source_revision=value['source_revision'])
            if record is not None: raise ValueError('recover the previous repair journal before applying again')
            for name in FILES:
                if _current(root, prefix / name) != value['files'][name]['preimage_sha256']:
                    raise ValueError('installed transport differs from signed preimage')
            config = _path(root, CONFIG)
            original = _read(config, 65536, root.stat().st_uid)
            policy = _json(original)
            if not isinstance(policy, dict) or type(policy.get('enabled')) is not bool:
                raise ValueError('explicit updater policy required')
            disabled = (json.dumps(dict(policy, enabled=False), sort_keys=True, separators=(',', ':')) + '\n').encode()
            directory.mkdir(parents=True, mode=0o700)
            _atomic(directory / 'config.backup', original, 0o600)
            modes = {}
            for name in FILES:
                old = prefix / name
                modes[name] = stat.S_IMODE(old.stat().st_mode) if old.exists() else 0o644
                if old.exists(): _atomic(directory / (name + '.backup'), _read(old, MAX_FILE, root.stat().st_uid), 0o600)
            record = dict(schema_version=1, manifest_sha256=_sha(raw), root_partuuid=identity, phase='PREPARED',
                policy_sha256=_sha(original), disabled_sha256=_sha(disabled), policy_mode=stat.S_IMODE(config.stat().st_mode), file_modes=modes)
            _save(directory / 'journal.json', record)
            _atomic(config, disabled, record['policy_mode'])
            for name, content in payload.items():
                if _current(root, prefix / name) != value['files'][name]['preimage_sha256']:
                    raise ValueError('transport changed during repair; HOLD')
                _atomic(prefix / name, content, 0o644)
            record['phase'] = 'COMMIT_INTENT'
            _save(directory / 'journal.json', record)
            return _finish(root, directory, record, value)
        finally:
            rosy_claim.release(root, holder)


def apply(root, package, *, run=_run):
    return _operate(root, package, run=run, recovering=False)


def recover(root, package, *, run=_run):
    return _operate(root, package, run=run, recovering=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('apply', 'recover'))
    parser.add_argument('--package', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0: raise ValueError('OS repair requires root')
        trusted = Path('/') / PREFIX
        _read(trusted / 'signing.py', MAX_FILE, 0)
        sys.path.insert(0, str(trusted))
        metadata, _, _ = validate_package(args.package, Path('/') / PUBLIC_KEY, owner=0)
        if _sha(_read(Path(__file__), MAX_FILE, 0)) != metadata['installer_sha256']:
            raise ValueError('executing installer differs from signed package')
        print(json.dumps((recover if args.command == 'recover' else apply)(Path('/'), args.package), sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RuntimeError) as exc:
        print('OS_TRANSPORT_REPAIR_HOLD: ' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
