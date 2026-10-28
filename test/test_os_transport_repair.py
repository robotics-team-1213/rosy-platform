"""Signed transport-only maintenance with real files, signatures and modeled hardware observations."""
import hashlib
import importlib
import json
from pathlib import Path
import struct
import subprocess

import pytest

from signing import sign_checksums
from test_factory_release_signature import _keys
from test_os_update_controller import _source

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'deploy/robot/pinky_pro/native'


@pytest.fixture
def repair(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(NATIVE))
    m = importlib.import_module('os_transport_repair')
    controller, state, boot, root, journal, _, _, _, _, _, config_dir = _source(tmp_path, monkeypatch)
    current = state.read_state(root)
    current['committed']['release_id'] = '2026.10.28-172'
    journal.write_text(json.dumps(current))
    hostname = root / 'etc/hostname'
    hostname.write_text('rosy-pinky-geg6\n')
    prefix = root / m.PREFIX
    prefix.mkdir(parents=True)
    for name in m.FILES[:2]:
        (prefix / name).write_bytes(('old ' + name).encode())
    private, public = _keys(tmp_path / 'keys', 'repair')
    authority = root / m.PUBLIC_KEY
    authority.parent.mkdir(parents=True, exist_ok=True)
    authority.write_bytes(public.read_bytes())
    package = tmp_path / 'package'
    package.mkdir()
    installer = package / 'os_transport_repair.py'
    installer.write_bytes((NATIVE / installer.name).read_bytes())
    records = {}
    for name in m.FILES:
        content = ('# new ' + name + '\n').encode()
        (package / name).write_bytes(content)
        old = prefix / name
        records[name] = dict(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                             preimage_sha256=hashlib.sha256(old.read_bytes()).hexdigest() if old.exists() else None)
    manifest = dict(schema_version=1, kind='os-transport-repair', base_release_id='2026.10.28-172',
                    base_source_revision=m.BASE_SOURCE, source_revision='a' * 40,
                    canary=['rosy-pinky-geg6'], installer_sha256=hashlib.sha256(installer.read_bytes()).hexdigest(),
                    files=records)

    def seal():
        raw = json.dumps(manifest, sort_keys=True).encode()
        (package / 'transport-repair.json').write_bytes(raw)
        (package / 'transport-repair.json.sig').write_text(sign_checksums(raw, private))
    seal()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, 'ActiveState=inactive\nMainPID=0\nControlPID=0\n', '')
    return m, root, package, prefix, config_dir / 'config.json', manifest, seal, calls, run, controller, journal


def test_signed_three_file_repair_preserves_policy_and_frozen_owner(repair):
    m, root, package, prefix, config, _, _, calls, run, _, _ = repair
    original = config.read_bytes()
    result = m.apply(root, package, run=run)
    assert result['phase'] == 'COMPLETE'
    assert config.read_bytes() == original
    for name in m.FILES:
        assert (prefix / name).read_bytes() == (package / name).read_bytes()
    assert not any(any(word in command for word in ('start', 'stop', 'restart', 'reboot')) for command in calls)
    assert m.apply(root, package, run=run)['phase'] == 'COMPLETE'


def test_initial_disabled_policy_stays_disabled(repair):
    m, root, package, _, config, _, _, _, run, _, _ = repair
    config.write_bytes(b'{"enabled":false,"repo":"robotics-team-1213/rosy-platform"}\n')
    original = config.read_bytes()
    m.apply(root, package, run=run)
    assert config.read_bytes() == original


@pytest.mark.parametrize('fault', ['signature', 'payload', 'installer', 'preimage', 'symlink', 'hostname', 'fields'])
def test_bad_authority_or_target_never_disables_policy_or_changes_other_files(repair, fault):
    m, root, package, prefix, config, manifest, seal, _, run, _, _ = repair
    if fault == 'signature':
        (package / 'transport-repair.json.sig').write_text('invalid')
    elif fault == 'payload':
        (package / m.FILES[0]).write_bytes(b'changed')
    elif fault == 'installer':
        (package / 'os_transport_repair.py').write_bytes(b'changed')
    elif fault == 'preimage':
        (prefix / m.FILES[0]).write_bytes(b'unexpected operator contents')
    elif fault == 'symlink':
        target = prefix / m.FILES[0]
        target.rename(prefix / 'outside')
        target.symlink_to(prefix / 'outside')
    elif fault == 'hostname':
        (root / 'etc/hostname').write_text('another-robot\n')
    else:
        manifest['files']['os_update_controller.py'] = manifest['files'][m.FILES[0]]
        seal()
    original = config.read_bytes()
    before = (prefix / m.FILES[1]).read_bytes()
    with pytest.raises((ValueError, OSError)):
        m.apply(root, package, run=run)
    assert config.read_bytes() == original
    assert (prefix / m.FILES[1]).read_bytes() == before


@pytest.mark.parametrize('fault', ['pending', 'tryboot', 'service'])
def test_live_os_operation_cannot_be_repaired(repair, monkeypatch, fault):
    m, root, package, _, config, _, _, _, run, controller, _ = repair
    snapshot = controller._snapshot

    def changed(r):
        facts, state, other = snapshot(r)
        if fault == 'pending': state = dict(state, pending={'transaction_id': 'modeled'})
        if fault == 'tryboot': facts = dict(facts, tryboot=1)
        return facts, state, other
    monkeypatch.setattr(controller, '_snapshot', changed)
    if fault == 'service':
        run = lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, 'ActiveState=active\nMainPID=42\nControlPID=0\n', '')
    original = config.read_bytes()
    with pytest.raises(ValueError): m.apply(root, package, run=run)
    assert config.read_bytes() == original


class Crash(BaseException):
    pass


@pytest.mark.parametrize('boundary', ['disabled', 'file0', 'file1', 'file2', 'COMMIT_INTENT', 'restored'])
def test_interrupted_repair_recovers_exact_bytes_without_executing_candidate(repair, monkeypatch, boundary):
    m, root, package, prefix, config, _, _, _, run, _, _ = repair
    original_policy = config.read_bytes()
    old = {name: (prefix / name).read_bytes() if (prefix / name).exists() else None for name in m.FILES}
    atomic = m._atomic
    count = [0]

    def interrupted(path, raw, mode):
        atomic(path, raw, mode)
        hit = path == config and (json.loads(raw)['enabled'] is False if boundary == 'disabled' else raw == original_policy)
        if path.parent == prefix:
            hit = boundary == 'file' + str(count[0])
            count[0] += 1
        if path.name == 'journal.json':
            hit = boundary == json.loads(raw).get('phase')
        if hit and boundary in ('disabled', 'file0', 'file1', 'file2', 'COMMIT_INTENT', 'restored'):
            raise Crash()
    monkeypatch.setattr(m, '_atomic', interrupted)
    with pytest.raises(Crash): m.apply(root, package, run=run)
    monkeypatch.setattr(m, '_atomic', atomic)
    result = m.recover(root, package, run=run)
    assert config.read_bytes() == original_policy
    for name in m.FILES:
        path = prefix / name
        expected = (package / name).read_bytes() if result['phase'] == 'COMPLETE' else old[name]
        assert (path.read_bytes() if path.exists() else None) == expected


def test_unknown_policy_change_is_preserved_during_recovery(repair, monkeypatch):
    m, root, package, _, config, _, _, _, run, _, _ = repair
    atomic = m._atomic
    def fail(path, raw, mode):
        atomic(path, raw, mode)
        if path == config: raise Crash()
    monkeypatch.setattr(m, '_atomic', fail)
    with pytest.raises(Crash): m.apply(root, package, run=run)
    monkeypatch.setattr(m, '_atomic', atomic)
    changed = b'{"enabled":false,"operator_changed":true}'
    config.write_bytes(changed)
    with pytest.raises(ValueError): m.recover(root, package, run=run)
    assert config.read_bytes() == changed
