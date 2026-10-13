"""Real OpenSSL/rename/flock tests; DrvFS mode adapter is explicitly limited."""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest
import yaml

# CI runs as root in its container; a non-root POSIX host (the shared test PCs) cannot.
# Windows keeps its existing behaviour.
REQUIRES_ROOT = pytest.mark.skipif(os.name == "posix" and os.geteuid() != 0,
                                   reason="needs root: the store requires root-owned paths (PATH_UNSAFE as non-root)")

pytest.importorskip('fcntl', reason='Linux operator provisioner requires POSIX descriptor/flock checks')
helper = Path(__file__).with_name('native_tls_provision.py')
if not helper.is_file():
    helper = Path(__file__).resolve().parents[1] / 'deploy/robot/pinky_pro/release/native_tls_provision.py'
spec = importlib.util.spec_from_file_location('native_tls_provision', helper)
tls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tls)


@pytest.fixture
def store(tmp_path):
    root = tmp_path / 'device'
    root.mkdir(mode=0o700)
    for name in ['etc/rosy', 'var/lib/rosy/core/.rosy', 'var/lib/rosy/releases',
                 'run/rosy-claim', 'proc/sys/kernel/random', 'sys/fs/cgroup']:
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / tls.CONFIG).write_bytes(b'robot:\n  id: retained-id\nauth:\n  token_hash: retained-hash\n')
    (root / tls.ENV).write_bytes(b'ROSY_DEPLOYMENT=device\nROSY_RUNTIME_MODE=core\nKEEP=literal\n')
    for name in [tls.CONFIG, tls.ENV]:
        (root / name).chmod(0o600)
    drvfs = stat.S_IMODE((root / tls.CONFIG).stat().st_mode) != 0o600

    class FixtureStore(tls.Store):
        # DrvFS has fixed0777. Only permission/owner metadata is adapted; real
        # descriptor traversal, flock, read, rename/fsync and OpenSSL still run.
        modes = {tls.CONFIG: 0o600, tls.ENV: 0o600}

        def check(self, info, *, directory=False, core_owned=False):
            if not drvfs:
                return super().check(info, directory=directory, core_owned=core_owned)
            valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
            if not valid or (not directory and info.st_nlink != 1):
                raise tls.Hold('PATH_UNSAFE')

        def read(self, relative, **kwargs):
            result = super().read(relative, **kwargs)
            if drvfs and result is not None and relative in self.modes:
                data, meta = result
                result = data, (*meta[:4], self.modes[relative], meta[-1])
            return result

        def atomic(self, relative, data, uid, gid, mode):
            super().atomic(relative, data, uid, gid, mode)
            self.modes[relative] = mode

        def ensure_tls_directory(self):
            if drvfs:
                (self.root / tls.TLS).mkdir(exist_ok=True)
            else:
                super().ensure_tls_directory()

        def lock(self, relative, uid=0, gid=0):
            if drvfs and relative == tls.CONFIG + '.lock':
                # Existing production strict0600 guard is tested separately.
                return super().lock('run/fixture-config.lock')
            return super().lock(relative, uid, gid)

    result = FixtureStore(root, os.getuid(), os.getgid())
    result.drvfs_adapter = drvfs
    return result


def apply(store, **kwargs):
    return tls.provision(store, 'fixture', 'robot-test.local', yaml, fence=lambda: None,
                         stage_parent=store.root.parent, **kwargs)


@REQUIRES_ROOT
def test_release_metadata_size_does_not_expand_configuration_read_limit(store):
    # Native release 037 contains a 520894-byte manifest and 383685-byte sums.
    for name, size in [('manifest.json', 520894), ('SHA256SUMS', 383685)]:
        data = b'x' * size
        (store.root / name).write_bytes(data)
        with pytest.raises(tls.Hold, match='FILE_TOO_LARGE'):
            store.read(name)
        assert store.read(name, max_bytes=tls.RELEASE_METADATA_LIMIT)[0] == data
    (store.root / tls.CONFIG).write_bytes(b'x' * 131073)
    with pytest.raises(tls.Hold, match='FILE_TOO_LARGE'):
        store.read(tls.CONFIG)


@REQUIRES_ROOT
def test_release_metadata_still_has_a_finite_read_boundary(store):
    path = store.root / 'manifest.json'
    path.write_bytes(b'x' * tls.RELEASE_METADATA_LIMIT)
    assert len(store.read('manifest.json', max_bytes=tls.RELEASE_METADATA_LIMIT)[0]) == tls.RELEASE_METADATA_LIMIT
    with path.open('ab') as output:
        output.write(b'x')
    with pytest.raises(tls.Hold, match='FILE_TOO_LARGE'):
        store.read('manifest.json', max_bytes=tls.RELEASE_METADATA_LIMIT)
    for invalid in [0, -1, tls.RELEASE_METADATA_LIMIT + 1, 'unbounded']:
        with pytest.raises(tls.Hold, match='READ_LIMIT_INVALID'):
            store.read('manifest.json', max_bytes=invalid)


@REQUIRES_ROOT
def test_real_openssl_chain_hostname_keys_and_idempotent_ca(store):
    first = apply(store)
    assert first == {'ok': True, 'status': 'TLS_STAGED_RUNTIME_STOPPED', 'files': 6,
                     'existing_ca_retained': False}
    before = {name: store.read(tls.TLS + '/' + name) for name in tls.FILES}
    # Transaction preserves semantic non-TLS settings and all unrelated env bytes.
    config = yaml.safe_load(store.read(tls.CONFIG)[0])
    assert config['robot']['id'] == 'retained-id'
    assert config['auth']['token_hash'] == 'retained-hash'
    assert b'KEEP=literal\n' in store.read(tls.ENV)[0]
    assert b'ROSY_DEPLOYMENT=device\n' in store.read(tls.ENV)[0]
    assert apply(store)['existing_ca_retained']
    assert {name: store.read(tls.TLS + '/' + name) for name in tls.FILES} == before
    tls.verify_trust(store.root / tls.TLS, 'robot-test.local')
    with pytest.raises(tls.Hold):
        tls.verify_trust(store.root / tls.TLS, 'different.local')


@REQUIRES_ROOT
@pytest.mark.parametrize('kind', ['partial', 'foreign_manifest', 'foreign_config', 'development'])
def test_foreign_and_nonpaired_inputs_do_not_mutate_config(store, kind):
    if kind in ('partial', 'foreign_manifest'):
        apply(store)
        if kind == 'partial':
            store.remove(tls.TLS + '/ca.key')
        else:
            store.atomic(tls.TLS + '/managed.json', b'{}', 0, 0, 0o644)
    else:
        value = {'network': {'tls': {'cert_file': '/foreign', 'key_file': '/foreign'}}} \
            if kind == 'foreign_config' else {'network': {'connection_mode': 'development'}}
        store.atomic(tls.CONFIG, yaml.safe_dump(value).encode(), os.getuid(), os.getgid(), 0o600)
    before = store.read(tls.CONFIG)
    with pytest.raises(tls.Hold):
        apply(store)
    assert store.read(tls.CONFIG) == before


@REQUIRES_ROOT
@pytest.mark.parametrize('path', ['etc/rosy/tls/ca.pem', 'etc/rosy/tls/leaf.key', tls.CONFIG, tls.ENV])
def test_partial_rename_then_fsync_failure_restores_original_set(store, monkeypatch, path):
    before_config, before_env = store.read(tls.CONFIG), store.read(tls.ENV)
    atomic = store.atomic
    triggered = False

    def fail_once(relative, *args):
        nonlocal triggered
        atomic(relative, *args)
        if relative == path and not triggered:
            triggered = True
            raise OSError('injected after real rename and fsync')

    monkeypatch.setattr(store, 'atomic', fail_once)
    with pytest.raises(OSError):
        apply(store)
    assert triggered
    assert store.read(tls.CONFIG)[0] == before_config[0]
    assert store.read(tls.ENV)[0] == before_env[0]
    assert all(store.read(tls.TLS + '/' + name) is None for name in tls.FILES)


@REQUIRES_ROOT
def test_failed_rollback_is_explicit_hold_no_restart(store, monkeypatch):
    atomic = store.atomic

    def failure(relative, *args):
        if relative == tls.ENV:
            raise OSError('injected env failure')
        if relative == tls.CONFIG and store.read(tls.TLS + '/ca.pem') is not None:
            atomic(relative, *args)
            raise OSError('injected config commit and rollback failure')
        atomic(relative, *args)

    monkeypatch.setattr(store, 'atomic', failure)
    with pytest.raises(tls.Hold, match='ROLLBACK_UNVERIFIED_KEEP_STOPPED'):
        apply(store)
    # No restart command exists in the production transaction.
    assert 'start' not in tls.provision.__code__.co_consts


@pytest.mark.parametrize('field,value', [
    ('ActiveState', 'active'), ('MainPID', '41'), ('ControlPID', '42'), ('Job', '99'), ('MainPID', None)])
def test_actual_unit_state_missing_or_nonquiescent_refuses(store, field, value):
    fields = {'ActiveState': 'inactive', 'MainPID': '0', 'ControlPID': '0', 'Job': '', 'ControlGroup': ''}
    if value is None:
        fields.pop(field)
    else:
        fields[field] = value

    def run(args):
        return '\n'.join(k + '=' + v for k, v in fields.items()).encode()

    with pytest.raises(tls.Hold):
        tls.assert_quiescent(store, run)


def test_actual_cgroup_child_refuses_even_inactive_unit(store):
    group = store.root / 'sys/fs/cgroup/fixture'
    group.mkdir()
    (group / 'cgroup.procs').write_text('123\n')

    def run(args):
        return b'ActiveState=inactive\nMainPID=0\nControlPID=0\nJob=\nControlGroup=/fixture\n'

    with pytest.raises(tls.Hold, match='RUNTIME_CHILD_REMAINS'):
        tls.assert_quiescent(store, run)


@REQUIRES_ROOT
@pytest.mark.parametrize('kind', ['foreign', 'expired', 'boot'])
def test_real_claim_metadata_refuses_foreign_stale_otherboot(store, kind):
    (store.root / 'proc/sys/kernel/random/boot_id').write_text('fixture-boot')
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5 if kind != 'expired' else -5)
    claim = {'holder': 'other' if kind == 'foreign' else 'fixture', 'purpose': 'tls-maintenance',
             'boot_id': 'old-boot' if kind == 'boot' else 'fixture-boot', 'expires_at': expiry.isoformat()}
    (store.root / 'run/rosy-claim/claim.json').write_text(json.dumps(claim))
    with pytest.raises(tls.Hold, match='CLAIM_INVALID'):
        tls.assert_claim(store, 'fixture')


@REQUIRES_ROOT
def test_real_nofollow_symlink_and_hardlink_refuse(store):
    target = store.root / tls.CONFIG
    target.rename(target.with_name('original'))
    target.symlink_to(target.with_name('original'))
    with pytest.raises(OSError):
        store.read(tls.CONFIG)
    target.unlink()
    os.link(target.with_name('original'), target)
    with pytest.raises(tls.Hold, match='PATH_UNSAFE'):
        store.read(tls.CONFIG)


def test_duplicate_yaml_and_env_keys_refuse():
    with pytest.raises(tls.Hold, match='CONFIG_DUPLICATE_KEY'):
        tls.config_bytes(b'auth: {x: 1}\nauth: {x: 2}\n', {}, yaml)
    with pytest.raises(tls.Hold, match='ENV_DUPLICATE'):
        tls.env_bytes(b'ROSY_API_TLS=none\nROSY_API_TLS=required\n', 'host.local')


def test_actual_os_hostname_boundary():
    assert tls.hostname('device-1.local') == 'device-1.local'
    for invalid in ['device-1.local.', 'a.local.local', 'a.example.com', '127.0.0.1', 'name/DNS:other', '']:
        with pytest.raises(tls.Hold):
            tls.hostname(invalid)


def test_default_cli_no_apply_no_key_generation(capsys):
    assert tls.main([]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'NOT_APPLIED'


@REQUIRES_ROOT
def test_real_competing_process_flock_prevents_write(store):
    lock = store.root / 'run/contended.lock'
    child = subprocess.Popen([sys.executable, '-B', '-c',
                              'import fcntl,sys,time;f=open(sys.argv[1],"a+b");'
                              'fcntl.flock(f,fcntl.LOCK_EX);print("ready",flush=True);time.sleep(8)', str(lock)],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        with pytest.raises(tls.Hold, match='LOCK_BUSY'):
            with store.lock('run/contended.lock'):
                raise AssertionError('lock must not be acquired')
    finally:
        child.terminate()
        child.wait(timeout=3)


def test_production_mode_guard_rejects_writable_path(store):
    unsafe = store.root / 'unsafe'
    unsafe.write_text('x')
    unsafe.chmod(0o666)
    with pytest.raises(tls.Hold, match='PATH_UNSAFE'):
        tls.Store(store.root, os.getuid(), os.getgid()).check(unsafe.stat())


@REQUIRES_ROOT
def test_expired_managed_ca_is_not_regenerated(store):
    apply(store)
    ca_key = store.read(tls.TLS + '/ca.key')[0]
    directory = store.root / tls.TLS
    tls.openssl(['x509', '-in', directory / 'ca.pem', '-signkey', directory / 'ca.key',
                 '-days', '-1', '-out', directory / 'expired.pem'])
    store.atomic(tls.TLS + '/ca.pem', (directory / 'expired.pem').read_bytes(), 0, 0, 0o644)
    store.atomic(tls.TLS + '/fullchain.pem', (directory / 'leaf.pem').read_bytes()
                 + (directory / 'ca.pem').read_bytes(), 0, 0, 0o644)
    hashes = {n: tls.digest(store.read(tls.TLS + '/' + n)[0]) for n in tls.FILES if n != 'managed.json'}
    marker = {'version': 1, 'hostname': 'robot-test.local', 'files': hashes}
    store.atomic(tls.TLS + '/managed.json', json.dumps(marker).encode(), 0, 0, 0o644)
    before = store.read(tls.CONFIG)[0]
    with pytest.raises(tls.Hold):
        apply(store)
    assert store.read(tls.TLS + '/ca.key')[0] == ca_key
    assert store.read(tls.CONFIG)[0] == before


@REQUIRES_ROOT
def test_runtime_becomes_active_after_commit_no_unsafe_rollback(store, monkeypatch):
    before = store.read(tls.CONFIG)[0]
    atomic = store.atomic
    active = False

    def write(relative, *args):
        nonlocal active
        atomic(relative, *args)
        active = True

    def fence():
        if active:
            raise tls.Hold('RUNTIME_NOT_QUIESCENT')

    monkeypatch.setattr(store, 'atomic', write)
    with pytest.raises(tls.Hold, match='ROLLBACK_UNVERIFIED_KEEP_STOPPED'):
        tls.provision(store, 'fixture', 'robot-test.local', yaml, fence=fence,
                      stage_parent=store.root.parent)
    assert store.read(tls.CONFIG)[0] == before


@pytest.mark.parametrize('kind', ['missing_procs', 'symlink_group'])
def test_cgroup_missing_or_redirected_state_is_not_empty_proof(store, kind):
    group = store.root / 'sys/fs/cgroup/fixture'
    if kind == 'missing_procs':
        group.mkdir()
    else:
        group.symlink_to(store.root / 'etc')

    def run(args):
        return b'ActiveState=inactive\nMainPID=0\nControlPID=0\nJob=\nControlGroup=/fixture\n'

    with pytest.raises(tls.Hold, match='CGROUP_INVALID'):
        tls.assert_quiescent(store, run)


def test_target_has_no_service_pid_properties(store):
    calls = []

    def run(args):
        calls.append(args)
        if args[2].endswith('.target'):
            return b'ActiveState=inactive\nJob=\n'
        return b'ActiveState=inactive\nMainPID=0\nControlPID=0\nJob=\nControlGroup=\n'

    tls.assert_quiescent(store, run)
    assert len(calls) == len(tls.UNITS)


@REQUIRES_ROOT
def test_linux_mode_permissions_positive_or_explicit_drvfs_skip(store):
    if store.drvfs_adapter:
        pytest.skip('DrvFS0777: genuine POSIX ownership/mode positive required in LinuxCI')
    apply(store)
    private = (store.root / tls.TLS / 'ca.key').stat()
    leaf = (store.root / tls.TLS / 'leaf.key').stat()
    assert private.st_uid == 0 and stat.S_IMODE(private.st_mode) == 0o600
    assert leaf.st_uid == 0 and stat.S_IMODE(leaf.st_mode) == 0o640
