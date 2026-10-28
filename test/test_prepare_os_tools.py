"""Public Windows tools bootstrap: no installer actions, keys, or network in tests."""
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from urllib.error import URLError

import pytest


@pytest.fixture
def bootstrap(monkeypatch):
    module = importlib.import_module('tools.release.prepare_os_tools')
    monkeypatch.setattr(module.vm, '_windows_private', lambda path: None)
    return module


def pin(data, algorithm='sha256', filename='public.bin'):
    return dict(filename=filename, url='https://example.invalid/public.bin',
                size_bytes=len(data), **{algorithm: hashlib.new(algorithm, data).hexdigest()})


def test_existing_private_directory_is_checked_without_acl_changes(bootstrap, tmp_path, monkeypatch):
    checked = []
    monkeypatch.setattr(bootstrap.vm, '_windows_private', checked.append)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('changed an existing ACL'))
    bootstrap._ensure_directory(tmp_path)
    assert checked == [tmp_path]


def test_existing_untrusted_directory_is_never_repaired(bootstrap, tmp_path, monkeypatch):
    def refuse(_path):
        raise ValueError('not private')
    monkeypatch.setattr(bootstrap.vm, '_windows_private', refuse)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('repaired an existing ACL'))
    with pytest.raises(ValueError, match='private'):
        bootstrap._ensure_directory(tmp_path)
    assert tmp_path.is_dir()


def test_new_cache_gets_private_acl_before_use(bootstrap, tmp_path, monkeypatch):
    destination = tmp_path / 'new-cache'
    calls = []
    def run(command, **kwargs):
        assert destination.is_dir()
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
    monkeypatch.setattr(subprocess, 'run', run)
    checked = []
    monkeypatch.setattr(bootstrap.vm, '_windows_private', checked.append)
    bootstrap._ensure_directory(destination)
    assert len(calls) == 1 and Path(calls[0][0][0]).name.lower() == 'powershell.exe'
    assert calls[0][1]['creationflags'] & 0x08000000
    assert checked == [destination]


@pytest.mark.parametrize('algorithm', ['sha256', 'sha512'])
def test_existing_verified_input_is_not_downloaded_or_rewritten(bootstrap, tmp_path, monkeypatch, algorithm):
    data = b'public fixture archive'
    target = tmp_path / 'public.bin'
    target.write_bytes(data)
    before = target.stat().st_mtime_ns
    monkeypatch.setattr(bootstrap.vm, 'download', lambda *a: pytest.fail('redownloaded verified input'))
    monkeypatch.setattr(bootstrap, 'urlopen', lambda *a, **k: pytest.fail('redownloaded verified input'), raising=False)
    bootstrap._ensure_input(pin(data, algorithm), target)
    assert target.read_bytes() == data and target.stat().st_mtime_ns == before


@pytest.mark.parametrize('kind', ['changed', 'symlink', 'hardlink'])
def test_existing_untrusted_input_is_preserved_and_refused(bootstrap, tmp_path, kind):
    source, target = tmp_path / 'source', tmp_path / 'public.bin'
    source.write_bytes(b'public fixture archive')
    if kind == 'symlink':
        target.symlink_to(source)
    elif kind == 'hardlink':
        os.link(source, target)
    else:
        target.write_bytes(b'changed input')
    original = target.read_bytes()
    with pytest.raises(ValueError):
        bootstrap._ensure_input(pin(source.read_bytes()), target)
    assert target.read_bytes() == original


@pytest.mark.parametrize('algorithm', ['sha256', 'sha512'])
@pytest.mark.parametrize('defect', [None, 'digest', 'oversize'])
def test_download_is_size_and_digest_bound(bootstrap, tmp_path, monkeypatch, algorithm, defect):
    expected = b'bounded public input'
    data = expected if defect is None else (b'x' * len(expected) if defect == 'digest' else expected + b'x')
    monkeypatch.setattr(bootstrap.vm, 'urlopen', lambda *a, **k: io.BytesIO(data))
    monkeypatch.setattr(bootstrap, 'urlopen', lambda *a, **k: io.BytesIO(data), raising=False)
    target = tmp_path / 'public.bin'
    if defect:
        with pytest.raises(ValueError):
            bootstrap._ensure_input(pin(expected, algorithm), target)
        assert not target.exists()
    else:
        bootstrap._ensure_input(pin(expected, algorithm), target)
        assert target.read_bytes() == expected


def test_download_errors_never_disclose_remote_url(bootstrap, tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise URLError('https://example.invalid/archive?fixture-query=do-not-print')
    monkeypatch.setattr(bootstrap.vm, 'urlopen', fail)
    monkeypatch.setattr(bootstrap, 'urlopen', fail, raising=False)
    with pytest.raises(ValueError) as error:
        bootstrap._ensure_input(pin(b'public'), tmp_path / 'public.bin')
    assert 'do-not-print' not in str(error.value) and 'https://' not in str(error.value)


def extractor_fixture(bootstrap, tmp_path, monkeypatch):
    package = b'verified MSI fixture'
    monkeypatch.setattr(bootstrap, 'MSI', pin(package, filename='7z2605-x64.msi'))
    (tmp_path / '7z2605-x64.msi').write_bytes(package)
    components = {'7z.exe': b'fixture executable', '7z.dll': b'fixture DLL'}
    monkeypatch.setattr(bootstrap.vm, 'WINDOWS_7ZIP', {
        name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in components.items()})
    return components


def test_msi_is_read_as_data_and_only_verified_cab_components_are_published(bootstrap, tmp_path, monkeypatch):
    components = extractor_fixture(bootstrap, tmp_path, monkeypatch)
    calls = []
    def cabinet(package, destination):
        assert package.name == '7z2605-x64.msi'
        destination.write_bytes(b'bounded CAB fixture')
    monkeypatch.setattr(bootstrap, '_msi_cab', cabinet)
    def run(command, **kwargs):
        calls.append(command)
        assert Path(command[0]).name.lower() == 'tar.exe'
        assert kwargs['creationflags'] & 0x08000000
        output = Path(command[command.index('-C') + 1])
        for name, data in components.items():
            (output / ('_' + name)).write_bytes(data)
        return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
    monkeypatch.setattr(subprocess, 'run', run)
    bootstrap._extract_7zip(tmp_path)
    assert len(calls) == 1
    assert {p.name: p.read_bytes() for p in (tmp_path / '7zip-26.05').iterdir()} == components


def test_changed_extracted_component_is_not_published(bootstrap, tmp_path, monkeypatch):
    components = extractor_fixture(bootstrap, tmp_path, monkeypatch)
    monkeypatch.setattr(bootstrap, '_msi_cab', lambda _p, dest: dest.write_bytes(b'CAB'))
    def run(command, **kwargs):
        output = Path(command[command.index('-C') + 1])
        for name, data in components.items():
            (output / ('_' + name)).write_bytes(data + b'changed')
        return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(ValueError):
        bootstrap._extract_7zip(tmp_path)
    assert not (tmp_path / '7zip-26.05').exists()


def test_existing_extractor_is_verified_and_reused_without_execution(bootstrap, tmp_path, monkeypatch):
    components = extractor_fixture(bootstrap, tmp_path, monkeypatch)
    folder = tmp_path / '7zip-26.05'
    folder.mkdir()
    for name, data in components.items():
        (folder / name).write_bytes(data)
    monkeypatch.setattr(bootstrap, '_msi_cab', lambda *a: pytest.fail('re-extracted valid tools'))
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('executed cached tools'))
    bootstrap._extract_7zip(tmp_path)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == components


def test_default_bootstrap_prepares_only_pinned_public_inputs(bootstrap, tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(bootstrap, '_require_windows', lambda: None)
    directory, inputs, extraction = [], [], []
    monkeypatch.setattr(bootstrap, '_ensure_directory', directory.append)
    monkeypatch.setattr(bootstrap, '_ensure_input', lambda expected, target: inputs.append((expected, target)))
    monkeypatch.setattr(bootstrap, '_extract_7zip', extraction.append)
    expected = tmp_path / 'Rosy/os-tools'
    assert bootstrap.prepare() == expected
    assert directory == [expected] and extraction == [expected]
    assert {target.name for _, target in inputs} == {
        '7z2605-x64.msi', 'qemu-w64-setup-20260811.exe', 'guest.qcow2', 'vmlinuz', 'initrd'}
    assert all(target.parent == expected for _, target in inputs)
    cloud = json.loads(bootstrap.vm.PINS.read_bytes())
    for local, (name, size, digest) in cloud['cloud'].items():
        actual = next(value for value, target in inputs if target.name == local)
        assert (actual['url'], actual['size_bytes'], actual['sha256']) == (cloud['cloud_base'] + name, size, digest)
