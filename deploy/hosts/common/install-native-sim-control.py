#!/usr/bin/python3 -I
"""Explicit one-time administrator provisioning for the D-786 narrow helper."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile

HELPER = Path('/usr/local/sbin/rosy-native-sim-control')
CONFIG = Path('/etc/rosy/native-sim-control.json')
SUDOERS = Path('/etc/sudoers.d/rosy-native-sim-control')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'HOME': '/root'}


def build_plan(role, account, *, approved, site):
    if not approved or site:
        raise PermissionError('explicit native simulation approval on a non-site host is required')
    name = account.pw_name
    if role not in ('ai', 'model') or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', name) or name == 'root':
        raise ValueError('unsupported role or unprivileged account')
    if any(type(value) is not int or value <= 0 for value in (account.pw_uid, account.pw_gid)):
        raise ValueError('account must have nonzero uid and gid')
    if account.pw_dir != '/home/' + name:
        raise ValueError('account must use its fixed /home directory')
    config = dict(schema='rosy.native-sim-control/1', role=role, account=name,
                  uid=account.pw_uid, gid=account.pw_gid, home=account.pw_dir,
                  state_root='/var/lib/rosy-native-sim/' + str(account.pw_uid))
    return {'status': 'PLAN', 'helper': str(HELPER), 'config': config,
            'sudoers': (f'{name} ALL=(root) NOPASSWD: '
                        f'{HELPER}\n')}


def entry(path, uid=0, directory=True):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if info.st_uid != uid or not expected(info.st_mode) or info.st_mode & 0o022:
        raise PermissionError('unsafe installation entry: ' + str(path))


def preflight_path(path, *, owner=0, directory=True):
    for parent in reversed(path.parents):
        if parent.exists() or parent.is_symlink():
            entry(parent)
    if path.exists() or path.is_symlink():
        entry(path, uid=owner, directory=directory)


def check_host(config):
    role = Path('/etc/rosy/host-control/role')
    if role.exists() or role.is_symlink():
        preflight_path(role, directory=False)
        if role.read_text().strip() != config['role']:
            raise PermissionError('requested role differs from root-owned host role')
    for marker in (Path('/etc/rosy/site'), Path(config['home']) / 'rosy-jobs/site'):
        if marker.exists() or marker.is_symlink():
            raise PermissionError('site/Fleet marker forbids native simulation provisioning')


def preflight(plan):
    config = plan['config']
    root = Path(config['state_root'])
    # Inspect every existing ancestor/leaf before ANY privileged mkdir/chown.
    for path in (HELPER, CONFIG, SUDOERS):
        preflight_path(path, directory=False)
    for path in (root, root / 'start-intents'):
        preflight_path(path)
    for leaf in ('releases', 'state'):
        preflight_path(root / leaf, owner=config['uid'])
    check_host(config)
    if CONFIG.exists() and json.loads(CONFIG.read_text()) != config:
        raise PermissionError('existing helper configuration differs; decommission it explicitly')
    if SUDOERS.exists() and SUDOERS.read_text() != plan['sudoers']:
        raise PermissionError('existing sudoers entry differs; refusing to broaden it')


def mkdir_root(path):
    if path.exists():
        entry(path)
        return
    mkdir_root(path.parent)
    path.mkdir(mode=0o755)
    os.chown(path, 0, 0)


def atomic_file(path, content, mode):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), 0, 0)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def install(plan):
    preflight(plan)
    config = plan['config']
    source = Path(__file__).with_name('rosy-native-sim-control')
    payload = source.read_bytes()
    if not payload.startswith(b'#!/usr/bin/python3 -I\n'):
        raise ValueError('helper must use isolated Python')
    # Validate the exact proposed sudoers bytes before replacing any configuration.
    with tempfile.NamedTemporaryFile(mode='w', prefix='rosy-native-sudoers-', delete=False) as stream:
        candidate = Path(stream.name)
        stream.write(plan['sudoers'])
        stream.flush()
        os.fsync(stream.fileno())
    try:
        result = subprocess.run(['/usr/sbin/visudo', '-cf', str(candidate)],
                                env=ENV, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            raise PermissionError('visudo rejected helper-specific rule: ' + result.stderr)
        # All paths were checked; root-owned anchors prevent user leaf replacement.
        for path in (HELPER.parent, CONFIG.parent, SUDOERS.parent, Path(config['state_root'])):
            mkdir_root(path)
        root = Path(config['state_root'])
        mkdir_root(root / 'start-intents')
        os.chmod(root / 'start-intents', 0o700)
        for leaf, mode in (('releases', 0o755), ('state', 0o700)):
            path = root / leaf
            if not path.exists():
                path.mkdir(mode=mode)
                os.chown(path, config['uid'], config['gid'])
        atomic_file(HELPER, payload, 0o755)
        atomic_file(CONFIG, (json.dumps(config, sort_keys=True) + '\n').encode(), 0o600)
        # Installing the sudo authorization last makes partial provisioning fail closed.
        atomic_file(SUDOERS, plan['sudoers'].encode(), 0o440)
    finally:
        candidate.unlink(missing_ok=True)
    return dict(plan, status='PROVISIONED')


def main(args):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', required=True, choices=('ai', 'model'))
    parser.add_argument('--account', required=True)
    parser.add_argument('--approve-native-sim', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    options = parser.parse_args(args)
    os.environ.clear()
    os.environ.update(ENV)
    account = pwd.getpwnam(options.account)
    plan = build_plan(options.role, account, approved=options.approve_native_sim, site=False)
    check_host(plan['config'])
    if options.dry_run:
        # No root operation; root-only existing config inspection belongs to install.
        return plan
    if os.geteuid() != 0:
        return dict(plan, status='NEEDS_PROVISIONING', reason='administrator provisioning requires root')
    return install(plan)


if __name__ == '__main__':
    try:
        result = main(sys.argv[1:])
        print(json.dumps(result, sort_keys=True))
        sys.exit(0 if result['status'] != 'NEEDS_PROVISIONING' else 3)
    except (ValueError, PermissionError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'REFUSED', 'error': str(exc)}, sort_keys=True))
        sys.exit(1)
