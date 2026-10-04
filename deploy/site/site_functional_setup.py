"""Provision least-privilege site functional verification without changing enrollment."""
from __future__ import annotations

import copy
import re
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

PRINCIPAL = 'site-update-health'


def build_plan(users, config, robots, sources, digest, token_file):
    """Return independent documents, refusing credential or local-policy collisions."""
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('invalid credential digest')
    next_users, next_config = copy.deepcopy(users), copy.deepcopy(config)
    expected = {'principal_id': PRINCIPAL, 'role': 'viewer', 'token_sha256': digest}
    for entry in next_users['users']:
        if entry['principal_id'] == PRINCIPAL and entry != expected:
            raise ValueError('existing verification principal differs')
        if entry['token_sha256'] == digest and entry != expected:
            raise ValueError('verification credential belongs to another principal')
    if expected not in next_users['users']:
        next_users['users'].append(expected)
    checks = []
    for path, ids in [('/api/fleet/state', robots), ('/api/fleet/vision/sources', sources)]:
        if not ids or any(not isinstance(value, str) or not value.strip() for value in ids):
            raise ValueError('functional verification requires explicit nonempty IDs')
        checks.append({'path': path, 'token_file': token_file, 'required_ids': sorted(set(ids))})
    if config.get('functional_checks') and config['functional_checks'] != checks:
        raise ValueError('existing functional verification policy differs')
    next_config['functional_checks'] = checks
    return next_users, next_config


def snapshot(path):
    """Reject symlinks and preserve exact bytes and ownership for recovery."""
    if path.is_symlink():
        raise ValueError('configuration symlink requires operator review')
    if not path.exists():
        return None
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('configuration must be a regular file')
    data = path.read_bytes()
    return {'data': base64.b64encode(data).decode('ascii'), 'sha256': hashlib.sha256(data).hexdigest(),
            'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}


def document(data, mode=0o600):
    return {'data': base64.b64encode(data).decode('ascii'), 'sha256': hashlib.sha256(data).hexdigest(),
            'mode': mode, 'uid': 0, 'gid': 0}


def protected(entry, name):
    forbidden = {'config': 0o022, 'users': 0o027, 'token': 0o077}[name]
    return entry['uid'] == 0 and not entry['mode'] & forbidden


def updated(data, original):
    result = document(data, original['mode'])
    result.update(uid=original['uid'], gid=original['gid'])
    return result


def sync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def replace(path, entry):
    """Atomic protected write; backups remain in the durable root-only journal."""
    if entry is None:
        path.unlink(missing_ok=True)
        sync_directory(path.parent)
        return
    data = base64.b64decode(entry['data'], validate=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.site-health-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            if os.name != 'nt':
                os.fchmod(stream.fileno(), entry['mode'])
                os.fchown(stream.fileno(), entry['uid'], entry['gid'])
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Transaction:
    """Recover config-only changes; refuse to overwrite any unknown concurrent edit."""

    def __init__(self, journal, targets, host):
        self.journal, self.targets, self.host = journal, targets, host

    def recover(self):
        if not self.journal.exists():
            return
        pending = json.loads(self.journal.read_bytes())
        if set(pending['files']) != set(self.targets):
            raise ValueError('recovery target set differs')
        timer = pending['timer']
        if set(timer) != {'enabled', 'active'} or any(type(v) is not bool for v in timer.values()):
            raise ValueError('recovery timer state is malformed')
        # Validate every backup and target before restoring any file.
        for name, pair in pending['files'].items():
            for entry in pair:
                if entry is not None:
                    data = base64.b64decode(entry['data'], validate=True)
                    if hashlib.sha256(data).hexdigest() != entry['sha256']:
                        raise ValueError('recovery backup checksum differs')
                    if not protected(entry, name):
                        raise ValueError('recovery configuration is not protected')
            if snapshot(self.targets[name]) not in pair:
                raise ValueError('unknown local edit; recovery requires operator review')
        self.host.signed()
        self.host.stop_timer()
        for name, pair in pending['files'].items():
            replace(self.targets[name], pair[0])
        self.host.guard()
        self.host.restart()
        self.host.verify()
        self.host.restore_timer(pending['timer'])
        self.journal.unlink()
        sync_directory(self.journal.parent)

    def apply(self, originals, proposed):
        if originals == proposed:
            self.host.verify()
            return
        pending = {'timer': self.host.timer(),
                   'files': {key: [originals[key], proposed[key]] for key in self.targets}}
        # Refuse before writing the journal or touching timer/configuration.
        if any(snapshot(path) != originals[key] for key, path in self.targets.items()):
            raise ValueError('configuration changed since preflight')
        replace(self.journal, document(json.dumps(pending).encode()))
        try:
            self.host.guard()
            self.host.stop_timer()
            for key, path in self.targets.items():
                if snapshot(path) != originals[key]:
                    raise ValueError('configuration changed during setup')
                replace(path, proposed[key])
            self.host.guard()
            self.host.restart()
            self.host.verify()
            self.host.restore_timer(pending['timer'])
            self.journal.unlink()
            sync_directory(self.journal.parent)
        except BaseException:
            self.recover()
            raise


class Host:
    """Fixed host ports: no robot commands, no enrollment changes, no image replacement."""

    unit = 'rosy-site-autoupdate.timer'

    def __init__(self, config, token_file):
        from site_update_io import Http
        self.config, self.token_file, self.http = config, token_file, Http()

    @staticmethod
    def command(argv, **kwargs):
        result = subprocess.run(argv, capture_output=True, timeout=120, **kwargs)
        if result.returncode:
            # stderr can contain credential/config values; never echo it.
            raise RuntimeError('host command failed: ' + argv[0])
        return result.stdout

    def get(self, path, token_file):
        origin = urlsplit(self.config['health_url'])
        return self.http.functional(f'https://{origin.netloc}{path}',
                                    self.config.get('health_ca'), token_file)

    def timer(self):
        def status(verb):
            result = subprocess.run(['systemctl', verb, self.unit], capture_output=True, timeout=15)
            return result.stdout.decode().strip()
        enabled, active = status('is-enabled'), status('is-active')
        if enabled not in {'enabled', 'disabled'} or active not in {'active', 'inactive'}:
            raise ValueError('timer state needs operator review')
        return {'enabled': enabled == 'enabled', 'active': active == 'active'}

    def stop_timer(self):
        self.command(['systemctl', 'disable', '--now', self.unit])

    def restore_timer(self, state):
        self.command(['systemctl', 'enable' if state['enabled'] else 'disable', self.unit])
        self.command(['systemctl', 'start' if state['active'] else 'stop', self.unit])

    def restart(self):
        self.command(['docker', 'restart', 'rosy-site-fleet-1'])

    def guard(self):
        operator = Path('/etc/rosy/site/secrets/operator.token')
        control = self.get('/api/fleet/dispatch-control', operator)
        if control.get('queued_tasks') != 0 or control.get('unresolved_actions') != 0:
            raise ValueError('site has queued or unresolved work; setup deferred')
        rows = self.get('/api/fleet/state', operator)['robots']
        if any(r.get('goal') or r.get('queued') or r.get('held') or r.get('yielding') for r in rows):
            raise ValueError('site has active robot work; setup deferred')

    def signed(self):
        """Bind the current containers to signed images/config even if APIs are unavailable."""
        from site_update_io import Paths, SERVICES, read_env, runtime_reason
        from rosy_site_autoupdate import SiteUpdater
        paths = Paths()
        config = dict(self.config)
        config['public_key'] = Path(config['public_key'])
        self.updater = SiteUpdater(config, paths=paths)
        folder = paths.link.resolve(strict=True)
        self.commit, self.env = folder.name, read_env(paths.site_env)
        if self.env.get('ROSY_SITE_IMAGE_TAG') != self.commit:
            raise ValueError('running environment differs from current signed candidate')
        self.updater._verify(folder, loaded=True)
        output = self.updater._compose(self.env, 'ps', '--all', '--format', 'json').stdout.strip()
        rows = json.loads(output) if output.startswith('[') else [json.loads(line) for line in output.splitlines()]
        accepted = self.updater._accepted_images[self.commit]
        for service in SERVICES:
            matches = [row for row in rows if row.get('Service') == service]
            if len(matches) != 1 or matches[0].get('Image') != f'rosy-site-{service}:{self.commit}':
                raise ValueError('running container differs from signed candidate')
            identity = self.updater._run(['docker', 'container', 'inspect', '--format',
                                          '{{.Image}}', matches[0]['ID']]).stdout.strip()
            if identity not in accepted.get(service, ()):
                raise ValueError('running image identity differs from signed candidate')
        output = self.updater._compose(self.env, 'config', '--hash', '*', tag=self.commit).stdout
        hashes = dict(line.split() for line in output.splitlines() if line.strip())
        if runtime_reason(rows, hashes, self.updater._run):
            raise ValueError('running container configuration differs')

    def verify(self):
        from site_update_io import functional_reason, load_config
        self.config = load_config(Path('/etc/rosy/site/autoupdate.conf'))
        # Recovery can run before main's normal preflight has constructed an updater.
        if not hasattr(self, 'updater'):
            self.signed()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if (self.http.status(self.config['health_url'], self.config['health_ca']) == 200
                    and not functional_reason(self.config, self.http)
                    and not self.updater._containers_reason(self.env, self.commit)):
                return
            time.sleep(3)
        raise RuntimeError('functional verification did not become healthy')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='apply or recover an interrupted setup')
    args = parser.parse_args(argv)
    if os.name == 'nt' or os.geteuid() != 0:
        raise ValueError('run in the site operator sudo terminal')
    # Import installed reviewed tools, never candidate-folder or current-directory code.
    sys.path.insert(0, '/usr/local/lib/rosy-site')
    from site_update_io import Paths, load_config, read_env, run_lock
    from rosy_site_autoupdate import SiteUpdater
    paths = Paths()
    targets = {'token': Path('/etc/rosy/site/secrets/site-update-viewer.token'),
               'users': Path('/etc/rosy/site/site-users.yaml'), 'config': paths.config}
    journal = Path('/var/lib/rosy/site-functional-setup.json')
    receipt = Path('/var/lib/rosy/site-functional-setup-receipt.json')
    with run_lock(paths.lock):
        if journal.exists() and not protected(snapshot(journal), 'token'):
            raise ValueError('setup recovery journal must be root-only')
        # During interrupted rollback the new config may refer to an already removed
        # token. Validate journal files first; defer strict token-file validation.
        bootstrap = (json.loads(paths.config.read_bytes()) if journal.exists()
                     else load_config(paths.config))
        host = Host(bootstrap, targets['token'])
        transaction = Transaction(journal, targets, host)
        if journal.exists():
            if not args.apply:
                raise ValueError('interrupted setup needs --apply recovery')
            transaction.recover()
            host.config = load_config(paths.config)
        updater = SiteUpdater(host.config, paths=paths)
        state = updater.load_state()
        if state.get('switch') or state.get('hold'):
            raise ValueError('update switch or maintenance hold requires operator review')
        current = paths.link.resolve(strict=True)
        updater._verify(current, loaded=True)
        env = read_env(paths.site_env)
        host.updater, host.env, host.commit = updater, env, current.name
        if updater._containers_reason(env, current.name):
            raise ValueError('deployed signed stack differs or is unhealthy')
        originals = {key: snapshot(path) for key, path in targets.items()}
        for key, entry in originals.items():
            if entry and not protected(entry, key):
                raise ValueError('configuration must be root-only')
        raw_users = base64.b64decode(originals['users']['data'])
        code = 'import sys,json,yaml;print(json.dumps(yaml.safe_load(sys.stdin.buffer.read())))'
        users = json.loads(host.command(['docker', 'exec', '-i', '--user', '0:0',
                                        'rosy-site-fleet-1', 'python3', '-I', '-c', code], input=raw_users))
        operator = Path('/etc/rosy/site/secrets/operator.token')
        token_entry = snapshot(operator)
        if not token_entry or token_entry['uid'] != 0 or token_entry['mode'] & 0o077:
            raise ValueError('setup operator credential must be root-only')
        digest = hashlib.sha256(operator.read_text().strip().encode()).hexdigest()
        if not any(u['token_sha256'] == digest and u['role'] == 'operator' for u in users['users']):
            raise ValueError('setup credential is not an existing named operator')
        enrollment = host.get('/api/fleet/enrollment/robots', operator)
        robots = [r['robot_id'] for r in enrollment['robots'] if r['state'] == 'active']
        sources = host.get('/api/fleet/vision/sources', operator)['sources']
        host.guard()
        token = (targets['token'].read_text().strip() if originals['token']
                 else secrets.token_urlsafe(48))
        users, config = build_plan(users, json.loads(paths.config.read_bytes()), robots, sources,
                                   hashlib.sha256(token.encode()).hexdigest(), str(targets['token']))
        proposed = {'token': document((token + '\n').encode()),
                    'users': updated((json.dumps(users, indent=2) + '\n').encode(), originals['users']),
                    'config': updated((json.dumps(config, indent=2) + '\n').encode(), originals['config'])}
        if not args.apply:
            print(json.dumps({'result': 'ready', 'role': 'viewer', 'checks': 2,
                              'robot_count': len(robots), 'source_count': len(sources)}))
            return 0
        transaction.apply(originals, proposed)
        replace(receipt, document(json.dumps({'result': 'installed', 'role': 'viewer',
                                             'checks': 2, 'commit': current.name}).encode()))
        print('Functional verification installed and verified; robot motion not tested.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        # Deliberately exclude command output, credentials, and exception values.
        print('Functional setup stopped: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
