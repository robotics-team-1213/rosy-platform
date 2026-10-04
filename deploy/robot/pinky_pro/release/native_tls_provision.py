"""Operator-only paired LAN TLS provisioning. Never stops or starts runtime.

Run the signed installed helper with isolated system Python as root, after the
operator has claimed maintenance and stopped runtime. Public output is metadata
only. An uncertain transaction remains stopped for operator recovery.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import fcntl
import grp
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import time

CONFIG = 'var/lib/rosy/core/.rosy/rosy.yaml'
ENV = 'etc/rosy/runtime.env'
TLS = 'etc/rosy/tls'
FILES = ('ca.pem', 'ca.key', 'leaf.pem', 'leaf.key', 'fullchain.pem', 'managed.json')
UNITS = ('rosy-runtime.target', 'rosy-core.service', 'rosy-io.service',
         'rosy-camera.service', 'rosy-host-agent.service', 'rosy-ssh-pairing.service',
         'rosy-navigation.service')
ENV_KEYS = ('ROSY_API_TLS', 'ROSY_API_TLS_HOST', 'ROSY_API_TLS_CA_FILE')
RELEASE_METADATA_LIMIT = 4 * 1024 * 1024


class Hold(RuntimeError):
    """A fail-closed metadata-only refusal."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def hostname(value):
    value = value.lower()
    if value.endswith('.local'):
        value = value[:-6]
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', value):
        raise Hold('HOSTNAME_INVALID')
    return value + '.local'


def command(args, *, timeout=5):
    result = subprocess.run(args, capture_output=True, timeout=timeout,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C',
                                 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    if result.returncode or len(result.stdout) + len(result.stderr) > 131072:
        raise Hold('COMMAND_FAILED')
    return result.stdout


def metadata(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid,
            stat.S_IMODE(info.st_mode), info.st_nlink)


class Store:
    """Every traversal is anchored at a nofollow directory descriptor."""
    def __init__(self, root, uid, gid):
        self.root, self.uid, self.gid = Path(root), uid, gid

    def check(self, info, *, directory=False, core_owned=False):
        valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        owners = (0, self.uid) if core_owned else (0,)
        if (not valid or info.st_uid not in owners or info.st_mode & 0o022
                or (not directory and info.st_nlink != 1)):
            raise Hold('PATH_UNSAFE')

    @contextlib.contextmanager
    def parent(self, relative):
        parts = Path(relative).parts
        if not parts or Path(relative).is_absolute() or '..' in parts:
            raise Hold('PATH_INVALID')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self.check(os.fstat(fd), directory=True)
            for index, name in enumerate(parts[:-1]):
                following = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = following
                prefix = '/'.join(parts[:index + 1])
                self.check(os.fstat(fd), directory=True,
                           core_owned=prefix == 'var/lib/rosy/core'
                           or prefix.startswith('var/lib/rosy/core/'))
            yield fd, parts[-1]
        finally:
            os.close(fd)

    def read(self, relative, *, max_bytes=131072):
        if not isinstance(max_bytes, int) or not 0 < max_bytes <= RELEASE_METADATA_LIMIT:
            raise Hold('READ_LIMIT_INVALID')
        with self.parent(relative) as (parent, name):
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                return None
            try:
                info = os.fstat(fd)
                self.check(info, core_owned=relative.startswith('var/lib/rosy/core/'))
                if info.st_size > max_bytes:
                    raise Hold('FILE_TOO_LARGE')
                data = b''
                while len(data) <= max_bytes:
                    block = os.read(fd, max_bytes + 1 - len(data))
                    if not block:
                        break
                    data += block
                if len(data) > max_bytes or metadata(os.fstat(fd)) != metadata(info):
                    raise Hold('FILE_CHANGED')
                return data, metadata(info)
            finally:
                os.close(fd)

    def atomic(self, relative, data, uid, gid, mode):
        with self.parent(relative) as (parent, name):
            temporary = '.tls-' + secrets.token_hex(12)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            try:
                os.fchown(fd, uid, gid)
                os.fchmod(fd, mode)
                with os.fdopen(fd, 'wb', closefd=False) as output:
                    output.write(data)
                    output.flush()
                os.fsync(fd)
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                os.close(fd)
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def remove(self, relative):
        with self.parent(relative) as (parent, name):
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)

    @contextlib.contextmanager
    def lock(self, relative, uid=0, gid=0):
        with self.parent(relative) as (parent, name):
            created = False
            try:
                fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
                created = True
            except FileExistsError:
                fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=parent)
            try:
                if created:
                    os.fchown(fd, uid, gid)
                    os.fchmod(fd, 0o600)
                info = os.fstat(fd)
                self.check(info, core_owned=relative.startswith('var/lib/rosy/core/'))
                if (info.st_uid != uid or
                        (relative == CONFIG + '.lock' and stat.S_IMODE(info.st_mode) != 0o600)):
                    raise Hold('LOCK_OWNER_INVALID')
                identity = metadata(os.fstat(fd))
                deadline = time.monotonic() + 2
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise Hold('LOCK_BUSY') from None
                        time.sleep(0.02)

                def unchanged():
                    self.check(os.fstat(fd), core_owned=relative.startswith('var/lib/rosy/core/'))
                    if (metadata(os.fstat(fd)) != identity or
                            metadata(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity):
                        raise Hold('LOCK_CHANGED')

                unchanged()
                yield unchanged
                unchanged()
            finally:
                os.close(fd)

    def ensure_tls_directory(self):
        with self.parent(TLS) as (parent, name):
            try:
                os.mkdir(name, 0o750, dir_fd=parent)
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    os.fchown(fd, 0, self.gid)
                    os.fchmod(fd, 0o750)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                os.fsync(parent)
            except FileExistsError:
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                        or stat.S_IMODE(info.st_mode) != 0o750 or info.st_gid != self.gid):
                    raise Hold('TLS_DIRECTORY_UNSAFE')


def assert_claim(store, holder):
    claim = store.read('run/rosy-claim/claim.json')
    boot = store.read('proc/sys/kernel/random/boot_id')
    if claim is None or boot is None:
        raise Hold('CLAIM_MISSING')
    try:
        data = json.loads(claim[0])
        expiry = dt.datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
        valid = (data['holder'] == holder and data['purpose'] == 'tls-maintenance'
                 and data['boot_id'] == boot[0].decode().strip()
                 and expiry.tzinfo is not None and expiry > dt.datetime.now(dt.timezone.utc))
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise Hold('CLAIM_INVALID')


def assert_quiescent(store, run=command):
    for unit in UNITS:
        required = {'ActiveState', 'Job'} if unit.endswith('.target') else {
            'ActiveState', 'MainPID', 'ControlPID', 'Job', 'ControlGroup'}
        output = run(['/usr/bin/systemctl', 'show', unit, '--no-pager',
                      '--property=' + ','.join(sorted(required))]).decode()
        fields = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        if (not required.issubset(fields)
                or fields['ActiveState'] not in ('inactive', 'failed')
                or (not unit.endswith('.target') and
                    (fields['MainPID'] != '0' or fields['ControlPID'] != '0'))
                or fields['Job'] not in ('', '0')):
            raise Hold('RUNTIME_NOT_QUIESCENT')
        group = fields.get('ControlGroup', '')
        if group:
            if not group.startswith('/') or '..' in Path(group).parts:
                raise Hold('CGROUP_INVALID')
            directory = store.root / 'sys/fs/cgroup' / group.lstrip('/')
            # The kernel owns this hierarchy; a vanished group is already empty.
            if directory.exists():
                if directory.is_symlink() or not (directory / 'cgroup.procs').is_file():
                    raise Hold('CGROUP_INVALID')
                for count, (parent, children, _) in enumerate(os.walk(directory, followlinks=False)):
                    procs = Path(parent) / 'cgroup.procs'
                    if (count >= 256 or any((Path(parent) / child).is_symlink() for child in children)
                            or procs.is_symlink() or not procs.is_file()):
                        raise Hold('CGROUP_INVALID')
                    with procs.open('r') as process_file:
                        content = process_file.read(65537)
                    if len(content) > 65536:
                        raise Hold('CGROUP_INVALID')
                    if content.strip():
                        raise Hold('RUNTIME_CHILD_REMAINS')


def yaml_module():
    # Isolated system Python must not load a writable service-home dependency.
    spec = importlib.util.find_spec('yaml')
    if spec is None or not spec.origin:
        raise Hold('YAML_IMPORT_UNAVAILABLE')
    path = Path(spec.origin)
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Hold('YAML_IMPORT_UNTRUSTED')
    for count, member in enumerate(path.parent.rglob('*')):
        info = member.lstat()
        if count > 256 or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Hold('YAML_IMPORT_UNTRUSTED')
    import yaml
    return yaml


def config_bytes(before, tls, yaml):
    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        output = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in output:
                raise Hold('CONFIG_DUPLICATE_KEY')
            output[key] = loader.construct_object(value_node, deep=deep)
        return output

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    old = yaml.load(before, Loader=UniqueLoader) or {}
    if not isinstance(old, dict) or not isinstance(old.get('network', {}), dict):
        raise Hold('CONFIG_INVALID')
    network = old.get('network', {})
    if network.get('connection_mode', 'paired') != 'paired':
        raise Hold('PAIRED_MODE_REQUIRED')
    if network.get('tls') not in (None, tls):
        raise Hold('FOREIGN_TLS_CONFIG')
    new = copy.deepcopy(old)
    new.setdefault('network', {})['tls'] = tls
    encoded = yaml.safe_dump(new, allow_unicode=True, sort_keys=False).encode()
    loaded = yaml.safe_load(encoded)
    if loaded != new:
        raise Hold('CONFIG_ROUNDTRIP_FAILED')
    return encoded


def env_bytes(before, host):
    lines = before.decode().splitlines(keepends=True)
    values = dict(zip(ENV_KEYS, ('required', host, '/etc/rosy/tls/ca.pem')))
    seen = set()
    output = []
    for line in lines:
        key = line.split('=', 1)[0]
        if key in values:
            if key in seen:
                raise Hold('ENV_DUPLICATE')
            seen.add(key)
            output.append(key + '=' + values[key] + '\n')
        else:
            output.append(line)
    if output and not output[-1].endswith('\n'):
        output[-1] += '\n'
    output.extend(key + '=' + value + '\n' for key, value in values.items() if key not in seen)
    return ''.join(output).encode()


def openssl(args):
    return command(['/usr/bin/openssl', *map(str, args)])


def verify_trust(directory, host):
    ca, leaf = directory / 'ca.pem', directory / 'leaf.pem'
    for cert in (ca, leaf):
        openssl(['x509', '-in', cert, '-checkend', '0', '-noout'])
    if b'CA:TRUE' not in openssl(['x509', '-in', ca, '-noout', '-ext', 'basicConstraints']):
        raise Hold('CA_INVALID')
    for stem in ('ca', 'leaf'):
        cert = openssl(['x509', '-in', directory / (stem + '.pem'), '-pubkey', '-noout'])
        key = openssl(['pkey', '-in', directory / (stem + '.key'), '-pubout'])
        if cert != key:
            raise Hold('KEY_MISMATCH')
    sans = openssl(['x509', '-in', leaf, '-noout', '-ext', 'subjectAltName']).decode()
    if re.findall(r'DNS:([^,\s]+)', sans) != [host] or 'IP Address:' in sans:
        raise Hold('SAN_INVALID')
    openssl(['verify', '-purpose', 'sslserver', '-verify_hostname', host, '-CAfile', ca, leaf])
    if (directory / 'fullchain.pem').read_bytes() != leaf.read_bytes() + ca.read_bytes():
        raise Hold('CHAIN_INVALID')


def trust_files(directory, host, existing):
    present = [key for key, value in existing.items() if value is not None]
    if present and len(present) != len(FILES):
        raise Hold('TLS_PARTIAL_OR_FOREIGN')
    if present:
        for name, record in existing.items():
            (directory / name).write_bytes(record[0])
        try:
            marker = json.loads(existing['managed.json'][0])
        except (TypeError, ValueError):
            raise Hold('TLS_MANIFEST_INVALID') from None
        hashes = {name: digest(existing[name][0]) for name in FILES if name != 'managed.json'}
        if marker != {'version': 1, 'hostname': host, 'files': hashes}:
            raise Hold('TLS_MANIFEST_INVALID')
    else:
        openssl(['genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
                 '-out', directory / 'ca.key'])
        openssl(['req', '-new', '-x509', '-key', directory / 'ca.key', '-out', directory / 'ca.pem',
                 '-days', '3650', '-subj', '/CN=ROSY device LAN CA',
                 '-addext', 'basicConstraints=critical,CA:TRUE',
                 '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
                 '-addext', 'subjectKeyIdentifier=hash',
                 '-addext', 'authorityKeyIdentifier=keyid:always'])
        openssl(['genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
                 '-out', directory / 'leaf.key'])
        openssl(['req', '-new', '-key', directory / 'leaf.key', '-out', directory / 'leaf.csr',
                 '-subj', '/CN=' + host])
        extension = directory / 'extensions'
        extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n'
                             'extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\n'
                             'authorityKeyIdentifier=keyid:always\nsubjectAltName=DNS:' + host + '\n')
        openssl(['x509', '-req', '-in', directory / 'leaf.csr', '-CA', directory / 'ca.pem',
                 '-CAkey', directory / 'ca.key', '-set_serial', str(secrets.randbits(128) or 1),
                 '-days', '365', '-extfile', extension, '-out', directory / 'leaf.pem'])
        chain = (directory / 'leaf.pem').read_bytes() + (directory / 'ca.pem').read_bytes()
        (directory / 'fullchain.pem').write_bytes(chain)
    verify_trust(directory, host)
    values = {name: (directory / name).read_bytes() for name in FILES if name != 'managed.json'}
    marker = {'version': 1, 'hostname': host, 'files': {k: digest(v) for k, v in values.items()}}
    values['managed.json'] = json.dumps(marker, sort_keys=True).encode()
    if present:
        values['managed.json'] = existing['managed.json'][0]
    return values


def provision(store, holder, host, yaml, *, fence=None, stage_parent=None):
    authority = fence or (lambda: (assert_claim(store, holder), assert_quiescent(store)))
    with store.lock('run/rosy-claim.lock') as claim_lock, \
            store.lock('var/lib/rosy/releases/native-release.lock') as release_lock, \
            store.lock(CONFIG + '.lock', store.uid, store.gid) as config_lock:
        def fence():
            claim_lock()
            release_lock()
            config_lock()
            authority()

        fence()
        before_config, before_env = store.read(CONFIG), store.read(ENV)
        if before_config is None or before_env is None:
            raise Hold('CONFIG_MISSING')
        # Reject mode/config before creating trust material.
        tls = {'cert_file': '/etc/rosy/tls/fullchain.pem', 'key_file': '/etc/rosy/tls/leaf.key',
               'ca_file': '/etc/rosy/tls/ca.pem'}
        proposed_config = config_bytes(before_config[0], tls, yaml)
        proposed_env = env_bytes(before_env[0], host)
        store.ensure_tls_directory()
        existing = {name: store.read(TLS + '/' + name) for name in FILES}
        for name, record in existing.items():
            if record is not None:
                mode = 0o600 if name == 'ca.key' else 0o640 if name == 'leaf.key' else 0o644
                if record[1][2:] != (0, store.gid if name == 'leaf.key' else 0, mode, 1):
                    raise Hold('TLS_FILE_MODE_INVALID')
        stage_parent = stage_parent or store.root / TLS
        with tempfile.TemporaryDirectory(prefix='.stage-', dir=stage_parent) as stage:
            directory = Path(stage)
            os.chmod(directory, 0o700)
            values = trust_files(directory, host, existing)
        targets = {}
        for name, data in values.items():
            mode = 0o600 if name == 'ca.key' else 0o640 if name == 'leaf.key' else 0o644
            targets[TLS + '/' + name] = (data, 0, store.gid if name == 'leaf.key' else 0, mode)
        targets[CONFIG] = (proposed_config, *before_config[1][2:5])
        targets[ENV] = (proposed_env, *before_env[1][2:5])
        originals = {path: store.read(path) for path in targets}
        attempted = []
        try:
            for path, (data, uid, gid, mode) in targets.items():
                fence()
                if store.read(path) != originals[path]:
                    raise Hold('TARGET_CHANGED')
                if originals[path] is not None and originals[path][0] == data:
                    continue
                attempted.append(path)
                store.atomic(path, data, uid, gid, mode)
            fence()
            for path, (data, uid, gid, mode) in targets.items():
                current = store.read(path)
                if current is None or current[0] != data or current[1][2:] != (uid, gid, mode, 1):
                    raise Hold('READBACK_FAILED')
            return {'ok': True, 'status': 'TLS_STAGED_RUNTIME_STOPPED', 'files': len(FILES),
                    'existing_ca_retained': existing['ca.pem'] is not None}
        except BaseException as original_error:
            try:
                # No restoration while runtime might still read changing files.
                fence()
                for path in reversed(attempted):
                    before = originals[path]
                    current = store.read(path)
                    allowed = [targets[path][0]] + ([before[0]] if before is not None else [])
                    if current is not None and current[0] not in allowed:
                        raise Hold('ROLLBACK_FOREIGN_TARGET')
                    if before is None:
                        if current is not None:
                            store.remove(path)
                    else:
                        store.atomic(path, before[0], *before[1][2:5])
                fence()
                for path, before in originals.items():
                    current = store.read(path)
                    if ((before is None and current is not None) or
                            (before is not None and (current is None or current[0] != before[0]
                             or current[1][2:] != before[1][2:]))):
                        raise Hold('ROLLBACK_READBACK_FAILED')
            except BaseException:
                raise Hold('ROLLBACK_UNVERIFIED_KEEP_STOPPED') from None
            raise original_error


def signed_source(store, public_key):
    current = Path('/opt/rosy/current').resolve(strict=True)
    helper = Path(__file__).resolve(strict=True)
    relative = 'deploy/robot/release/native_tls_provision.py'
    if (helper != current / relative or current.parent != Path('/opt/rosy/releases')
            or public_key.parent != Path('/etc/rosy/trusted-release-keys')):
        raise Hold('SIGNED_HELPER_REQUIRED')
    for path in (helper, Path('/opt/rosy/native-runtime/native_release.py'), public_key):
        for parent in (path, *path.parents):
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise Hold('SIGNED_PATH_UNSAFE')
    for count, member in enumerate(Path('/opt/rosy/native-runtime').rglob('*')):
        info = member.lstat()
        if count > 512 or stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Hold('VERIFIER_IMPORT_UNTRUSTED')
    metadata_files = ('manifest.json', 'SHA256SUMS', 'SHA256SUMS.sig')
    before = {name: store.read(str((current / name).relative_to('/')),
                              max_bytes=RELEASE_METADATA_LIMIT) for name in metadata_files}
    if any(value is None for value in before.values()):
        raise Hold('SIGNED_METADATA_MISSING')
    command(['/usr/bin/python3', '-E', '-s', '/opt/rosy/native-runtime/native_release.py',
             '--public-key', str(public_key), 'verify', '--release-id', current.name], timeout=60)
    manifest = json.loads((current / 'manifest.json').read_bytes())
    if any(store.read(str((current / name).relative_to('/')),
                      max_bytes=RELEASE_METADATA_LIMIT) != value
           for name, value in before.items()):
        raise Hold('SIGNED_METADATA_CHANGED')
    entries = [e for e in manifest['files'] if e['path'] == relative]
    if len(entries) != 1 or entries[0]['sha256'] != digest(helper.read_bytes()):
        raise Hold('SIGNED_HELPER_DIGEST_MISMATCH')
    if Path('/opt/rosy/current').resolve(strict=True) != current:
        raise Hold('CURRENT_RELEASE_CHANGED')
    return current, metadata(helper.stat()), digest(helper.read_bytes())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--holder')
    parser.add_argument('--public-key', type=Path,
                        default=Path('/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem'))
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps({'ok': False, 'status': 'NOT_APPLIED',
                          'prerequisites': ['signed installed helper', 'owned tls-maintenance claim',
                                            'verified stopped runtime', 'existing trust preserved']}))
        return 0
    try:
        if os.geteuid() != 0 or not sys.flags.isolated or not args.holder:
            raise Hold('ISOLATED_ROOT_OPERATOR_REQUIRED')
        account = pwd.getpwnam('rosy-core')
        store = Store('/', account.pw_uid, grp.getgrnam('rosy-core').gr_gid)
        source = signed_source(store, args.public_key)

        def fence():
            assert_claim(store, args.holder)
            assert_quiescent(store)
            current, identity, sha = source
            if (Path('/opt/rosy/current').resolve(strict=True) != current
                    or metadata(Path(__file__).stat()) != identity
                    or digest(Path(__file__).read_bytes()) != sha):
                raise Hold('SIGNED_SOURCE_CHANGED')

        result = provision(store, args.holder, hostname(socket.gethostname()), yaml_module(), fence=fence)
    except Exception:
        # Never serialize exception text, command stderr or configuration values.
        result = {'ok': False, 'status': 'HOLD_KEEP_RUNTIME_STOPPED'}
    print(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
