"""Opt-in disposable guest verification; never a release-image builder or a host installer."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import io
import base64
import shutil
import sys
from types import SimpleNamespace

import pytest


def module():
    return importlib.import_module("os_system_vm")


def windows_guest(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setattr(m, '_windows_private', lambda path: None)
    guest = m.WindowsGuest(tmp_path, cache=tmp_path / 'cache')
    guest.process = SimpleNamespace(poll=lambda: None)
    guest.ssh_port = 34567
    return guest


def console_key(guest, *, duplicate=False):
    blob = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(range(32))
    line = 'ssh-ed25519 ' + base64.b64encode(blob).decode() + ' root@fixture'
    (guest.directory / 'guest-console.log').write_text(
        '-----BEGIN SSH HOST KEY KEYS-----\n' + line + '\n' +
        (line + '\n' if duplicate else '') + '-----END SSH HOST KEY KEYS-----\n')
    return line.split()[1]


def test_windows_guest_uses_private_disks_packaged_bios_and_tcg(tmp_path, monkeypatch):
    guest = windows_guest(tmp_path, monkeypatch)
    command = guest.command(34567, 34568)
    assert command[0] == str(guest.root / 'qemu-system-x86_64.exe')
    assert command[command.index('-accel') + 1] == 'tcg'
    assert command[command.index('-bios') + 1] == str(guest.root / 'share/bios-256k.bin')
    drives = [command[i + 1] for i, value in enumerate(command) if value == '-drive']
    assert drives == [f"file={tmp_path / 'guest.qcow2'},if=virtio,format=qcow2",
                      f"file={tmp_path / 'work.raw'},if=virtio,format=raw"]
    assert guest.work_bytes == 32 * 1024**3


def test_windows_operator_requires_exact_source_before_guest_commands(tmp_path, monkeypatch):
    guest = windows_guest(tmp_path, monkeypatch)
    monkeypatch.setattr(guest, 'run', lambda *a, **k: pytest.fail('uncommitted source reached guest'))
    for revision in (None, 'HEAD', '--help'):
        with pytest.raises(ValueError, match='revision'):
            guest.provision_source(tmp_path, revision=revision)


def test_windows_ssh_waits_for_console_key_without_connecting(tmp_path, monkeypatch):
    guest = windows_guest(tmp_path, monkeypatch)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('SSH before host key'))
    assert guest._ssh('true').returncode == 255
    assert not (tmp_path / 'known-hosts').exists()


def test_windows_ssh_pins_console_key_and_disables_user_configuration(tmp_path, monkeypatch):
    guest = windows_guest(tmp_path, monkeypatch)
    key = console_key(guest)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, b'ok', b'')
    monkeypatch.setattr(subprocess, 'run', run)
    assert guest._ssh('true').stdout == b'ok'
    assert (tmp_path / 'known-hosts').read_text() == f'[127.0.0.1]:34567 ssh-ed25519 {key}\n'
    command, options = calls[0]
    assert command[1:3] == ['-F', 'none']
    for option in ('StrictHostKeyChecking=yes', 'ForwardAgent=no', 'ClearAllForwardings=yes',
                   'IdentitiesOnly=yes', 'HostKeyAlgorithms=ssh-ed25519'):
        assert option in command
    assert 'root@127.0.0.1' in command
    assert options['creationflags'] == 0x08000000


@pytest.mark.parametrize('change', [
    {'remote': '/work/finalized/../private'}, {'remote': '/work/finalized/name with space'},
    {'remote': '/work/finalized/name\n'}, {'remote': '/work/other/file'},
    {'remote': '/work/finalized/-option'}, {'remote': '/work/finalized/name;command'},
    {'remote': None}, {'size_bytes': 0}, {'size_bytes': True}, {'size_bytes': 1.0},
    {'size_bytes': 16 * 1024**3 + 1}, {'sha256': 'A' * 64}, {'sha256': 'a' * 63},
    {'sha256': None},
])
def test_windows_copy_refuses_invalid_request_before_commands(tmp_path, monkeypatch, change):
    guest = windows_guest(tmp_path, monkeypatch)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('invalid copy reached SSH'))
    arguments = dict(remote='/work/finalized/fixture.raucb', target=tmp_path / 'bundle',
                     size_bytes=1, sha256='a' * 64)
    arguments.update(change)
    with pytest.raises(ValueError):
        guest.copy_from(**arguments)
    assert not (tmp_path / 'bundle').exists()


def test_windows_copy_streams_to_exclusive_part_with_console_pinned_authority(tmp_path, monkeypatch):
    guest = windows_guest(tmp_path, monkeypatch)
    key = console_key(guest)
    payload = b'fixture verity bundle'
    target, calls = tmp_path / 'bundle.raucb', []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        part = Path(command[-1])
        assert part.parent == target.parent and part.name.endswith('.part')
        assert part.is_file() and part.read_bytes() == b'' and part != target
        assert not target.exists()
        part.write_bytes(payload)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(subprocess, 'run', run)
    guest.copy_from('/work/finalized/fixture.raucb', target,
                    size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    assert target.read_bytes() == payload
    assert (tmp_path / 'known-hosts').read_text() == f'[127.0.0.1]:34567 ssh-ed25519 {key}\n'
    command, options = calls[0]
    assert Path(command[0]).name == 'scp' and '-q' in command and '-O' not in command
    assert command[command.index('-P') + 1] == '34567'
    assert command[-2] == 'root@127.0.0.1:/work/finalized/fixture.raucb'
    for option in ('StrictHostKeyChecking=yes', 'ForwardAgent=no', 'ClearAllForwardings=yes',
                   'IdentitiesOnly=yes', 'HostKeyAlgorithms=ssh-ed25519', 'ControlMaster=no',
                   'ControlPath=none'):
        assert option in command
    assert command[command.index('-F') + 1] == 'none'
    assert options['creationflags'] == 0x08000000
    assert options['stdout'] == subprocess.DEVNULL and not options.get('capture_output')
    assert options['stdin'] == subprocess.DEVNULL
    assert not list(tmp_path.glob('*.part'))


@pytest.mark.parametrize('fault', ['missing_console', 'duplicate', 'changed_key', 'dead', 'private_parent'])
def test_windows_copy_refuses_unowned_transport_or_destination(tmp_path, monkeypatch, fault):
    guest = windows_guest(tmp_path, monkeypatch)
    if fault != 'missing_console':
        console_key(guest, duplicate=fault == 'duplicate')
    if fault == 'changed_key':
        (tmp_path / 'known-hosts').write_text('different key\n')
    if fault == 'dead':
        guest.process.poll = lambda: 1
    if fault == 'private_parent':
        def refuse(path):
            if Path(path) == tmp_path:
                raise ValueError('not a private parent')
        monkeypatch.setattr(module(), '_windows_private', refuse)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('unowned transfer ran'))
    with pytest.raises(ValueError):
        guest.copy_from('/work/finalized/fixture.raucb', tmp_path / 'bundle',
                        size_bytes=1, sha256='a' * 64)
    assert not (tmp_path / 'bundle').exists() and not list(tmp_path.glob('*.part'))


@pytest.mark.parametrize('fault', ['partial', 'changed', 'failed', 'guest_exit', 'target_race', 'symlink_part'])
def test_windows_copy_preserves_user_data_and_cleans_only_owned_part(tmp_path, monkeypatch, fault):
    guest = windows_guest(tmp_path, monkeypatch)
    console_key(guest)
    target, keep = tmp_path / 'bundle.raucb', tmp_path / 'keep.txt'
    keep.write_bytes(b'user data')
    payload, parts = b'fixture verity bundle', []
    def run(command, **kwargs):
        part = Path(command[-1])
        parts.append(part)
        part.write_bytes(payload[:-1] if fault == 'partial' else
                         b'x' * len(payload) if fault == 'changed' else payload)
        if fault == 'guest_exit':
            guest.process.poll = lambda: 1
        if fault == 'target_race':
            target.write_bytes(b'existing user output')
        if fault == 'symlink_part':
            part.unlink()
            part.symlink_to(keep)
        return subprocess.CompletedProcess(command, 1 if fault == 'failed' else 0)
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises((ValueError, OSError, subprocess.SubprocessError)):
        guest.copy_from('/work/finalized/fixture.raucb', target,
                        size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    assert keep.read_bytes() == b'user data'
    assert all(not part.exists() and not part.is_symlink() for part in parts)
    if fault == 'target_race':
        assert target.read_bytes() == b'existing user output'
    else:
        assert not target.exists()


def test_windows_copy_never_overwrites_existing_output(tmp_path, monkeypatch):
    guest = windows_guest(tmp_path, monkeypatch)
    target = tmp_path / 'bundle'
    target.write_bytes(b'existing user output')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('existing output reached SCP'))
    with pytest.raises((ValueError, FileExistsError)):
        guest.copy_from('/work/finalized/fixture.raucb', target, size_bytes=1, sha256='a' * 64)
    assert target.read_bytes() == b'existing user output'


@pytest.mark.parametrize('fault', ['duplicate', 'changed', 'dead', 'dies_during_command'])
def test_windows_ssh_refuses_ambiguous_or_unowned_endpoint(tmp_path, monkeypatch, fault):
    guest = windows_guest(tmp_path, monkeypatch)
    console_key(guest, duplicate=fault == 'duplicate')
    if fault == 'changed':
        (tmp_path / 'known-hosts').write_text('different key\n')
    if fault == 'dead':
        guest.process.poll = lambda: 1
    def run(command, **kwargs):
        if fault != 'dies_during_command':
            pytest.fail('unsafe endpoint reached SSH')
        guest.process.poll = lambda: 0
        return subprocess.CompletedProcess(command, 0, b'wrong endpoint', b'')
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(ValueError):
        guest._ssh('true')


def test_windows_workspace_refuses_qemu_option_injection(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setattr(m, '_windows_private', lambda path: None)
    directory = tmp_path / 'comma,drive'
    directory.mkdir()
    with pytest.raises(ValueError, match='workspace'):
        m.WindowsGuest(directory, cache=tmp_path / 'cache')


@pytest.mark.parametrize('tamper', [None, '7z.exe', '7z.dll', 'qemu-package'])
def test_windows_extracts_only_captured_authenticated_tools(tmp_path, monkeypatch, tamper):
    m = module()
    guest = windows_guest(tmp_path, monkeypatch)
    extractor = guest.cache / '7zip-26.05'
    extractor.mkdir(parents=True)
    expected = {}
    for name in ('7z.exe', '7z.dll'):
        raw = ('authenticated ' + name).encode()
        (extractor / name).write_bytes(raw)
        expected[name] = (len(raw), hashlib.sha256(raw).hexdigest())
    package = guest.cache / 'qemu-w64-setup-20260811.exe'
    package.write_bytes(b'authenticated package')
    monkeypatch.setattr(m, 'WINDOWS_7ZIP', expected, raising=False)
    monkeypatch.setattr(m, 'WINDOWS_QEMU_PACKAGE',
                        (package.stat().st_size, hashlib.sha512(package.read_bytes()).hexdigest()), raising=False)
    if tamper:
        (package if tamper == 'qemu-package' else extractor / tamper).write_bytes(b'tampered')
    # A cached extracted executable is never an authority, even when it reports the expected version.
    untrusted = guest.cache / 'qemu-20260811'
    untrusted.mkdir()
    (untrusted / 'qemu-system-x86_64.exe').write_bytes(b'untrusted cached executable')
    calls = []
    def run(command, **options):
        assert tamper is None, 'unauthenticated tool reached execution'
        calls.append(command)
        assert Path(command[0]).is_relative_to(guest.directory)
        assert Path(command[2]).is_relative_to(guest.directory)
        assert Path(command[0]).read_bytes() == b'authenticated 7z.exe'
        assert Path(command[2]).read_bytes() == b'authenticated package'
        assert command[3] == '-o' + str(guest.root)
        return subprocess.CompletedProcess(command, 0, b'', b'')
    monkeypatch.setattr(subprocess, 'run', run)
    if tamper:
        with pytest.raises(ValueError, match='digest'):
            guest._extract_tools()
        assert not calls
    else:
        guest._extract_tools()
        assert len(calls) == 1


def test_operator_source_archive_contains_only_committed_allowlisted_inputs(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    subprocess.run(['git', 'init', '-q', str(source)], check=True, capture_output=True)
    trusted = source / 'deploy/robot/pinky_pro/native/trusted.txt'
    trusted.parent.mkdir(parents=True)
    trusted.write_bytes(b'committed preparation code')
    subprocess.run(['git', '-C', str(source), 'add', 'deploy'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=ROSY fixture', '-c', 'user.email=test@example.invalid',
                    '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture', '--no-gpg-sign'],
                   check=True, capture_output=True)
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD']).decode().strip()
    subprocess.run(['git', '-C', str(source), 'config', 'tar.umask', '0000'], check=True, capture_output=True)
    trusted.write_bytes(b'uncommitted replacement')
    (trusted.parent / 'untracked.txt').write_bytes(b'untracked material')
    raw = module().committed_archive(source, revision)
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        assert archive.extractfile('deploy/robot/pinky_pro/native/trusted.txt').read() == b'committed preparation code'
        assert all('untracked' not in name and '.git/' not in name for name in archive.getnames())
        assert all(not member.mode & 0o022 for member in archive.getmembers())


@pytest.mark.parametrize('revision', ['HEAD', '--help', '0' * 39, '0' * 41])
def test_operator_source_archive_requires_an_exact_commit_before_running_git(tmp_path, monkeypatch, revision):
    m = module()
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: pytest.fail('invalid revision reached Git'))
    with pytest.raises(ValueError, match='revision'):
        m.committed_archive(tmp_path, revision)


@pytest.mark.parametrize('include_validator', [False, True])
def test_committed_guest_archive_can_import_keyless_entrypoint_without_checkout(tmp_path, monkeypatch, include_validator):
    m = module()
    original = Path(__file__).resolve().parents[1]
    source = tmp_path / 'source'
    source.mkdir()
    for name in ('deploy/robot/pinky_pro', 'deploy/hosts/common', 'contracts/foundation',
                 'tools/release/external_os_signing.py'):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if (original / name).is_dir():
            shutil.copytree(original / name, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copyfile(original / name, target)
    subprocess.run(['git', 'init', '-q', str(source)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=ROSY fixture', '-c', 'user.email=test@example.invalid',
                    '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture', '--no-gpg-sign'],
                   check=True, capture_output=True)
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD']).decode().strip()
    if not include_validator:
        monkeypatch.setattr(m, 'SOURCE_PATHS', tuple(path for path in m.SOURCE_PATHS
                                                    if path != 'tools/release/external_os_signing.py'))
    exported = tmp_path / 'exported'
    exported.mkdir()
    with tarfile.open(fileobj=io.BytesIO(m.committed_archive(source, revision)), mode='r:gz') as archive:
        archive.extractall(exported, filter='data')
    result = subprocess.run([sys.executable, str(exported / 'deploy/robot/pinky_pro/release/os_bundle_external.py'), '--help'],
                            cwd=exported, env=dict(os.environ, PYTHONPATH=''), capture_output=True, timeout=30)
    if include_validator:
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        assert b'prepare' in result.stdout and b'finalize' in result.stdout
    else:
        assert result.returncode != 0 and b'ModuleNotFoundError' in result.stderr
        assert b'external_os_signing' in result.stderr


def test_operator_source_is_verified_before_guest_disk_or_package_mutation(tmp_path, monkeypatch):
    guest = module().Guest(tmp_path)
    calls = []

    def observe(command, **kwargs):
        calls.append(command)
        assert command == 'cat /var/lib/cloud/data/instance-id', 'unverified source reached guest mutation'
        return guest.instance_id

    monkeypatch.setattr(guest, 'run', observe)
    with pytest.raises(ValueError, match='revision'):
        guest.provision_source(tmp_path, revision='HEAD')
    assert calls == ['cat /var/lib/cloud/data/instance-id']
@pytest.mark.parametrize("change", [None, "boot", "unit", "pid", "kind", "clock", "json"])
def test_pid1_start_evidence_binds_boot_unit_sender_event_and_clock(change):
    boot = "11111111-1111-4111-8111-111111111111"
    event = dict(UNIT="rosy-os-trial-deadline.service", _PID="1", _BOOT_ID=boot.replace("-", ""),
                 MESSAGE_ID="7d4958e842da4a758f6c1cdc7b36dcc5", __MONOTONIC_TIMESTAMP="180000001")
    if change == "boot": event["_BOOT_ID"] = "2" * 32
    if change == "unit": event["UNIT"] = "another.service"
    if change == "pid": event["_PID"] = "42"
    if change == "kind": event["MESSAGE_ID"] = "0" * 32
    if change == "clock": event["__MONOTONIC_TIMESTAMP"] = "179999999"
    raw = b"not json" if change == "json" else json.dumps(event).encode()
    if change is None:
        assert module().pid1_start(raw, "rosy-os-trial-deadline.service", boot, 180_000_000) == event
    else:
        with pytest.raises(ValueError):
            module().pid1_start(raw, "rosy-os-trial-deadline.service", boot, 180_000_000)


@pytest.mark.parametrize("change", [None, "boot", "unit", "pid", "failed", "stopped", "clock", "json"])
def test_completed_pid1_job_is_only_boot_smoke_evidence(change):
    boot = "11111111-1111-4111-8111-111111111111"
    event = dict(UNIT="rosy-os-trial-deadline.service", _PID="1", _BOOT_ID=boot.replace("-", ""),
                 MESSAGE_ID="39f53479d3a045ac8e11786248231fbf", __MONOTONIC_TIMESTAMP="181000001")
    if change == "boot": event["_BOOT_ID"] = "2" * 32
    if change == "unit": event["UNIT"] = "another.service"
    if change == "pid": event["_PID"] = "42"
    if change == "failed": event["MESSAGE_ID"] = "be02cf6855d2428ba40df7e9d022f03d"
    if change == "stopped": event["MESSAGE_ID"] = "9d1aaa27d60140bd96365438aad20286"
    if change == "clock": event["__MONOTONIC_TIMESTAMP"] = "-1"
    raw = b"not json" if change == "json" else json.dumps(event).encode()
    if change is None:
        assert module().pid1_start(raw, event["UNIT"], boot, 0) == event
    else:
        with pytest.raises(ValueError):
            module().pid1_start(raw, "rosy-os-trial-deadline.service", boot, 0)
    # Completion at 181 seconds cannot establish whether the job began before 180 seconds.
    with pytest.raises(ValueError):
        module().pid1_start(raw, "rosy-os-trial-deadline.service", boot, 180_000_000)


@pytest.mark.skipif(os.environ.get("ROSY_RUN_OS_SYSTEM_TESTS") != "1", reason="explicit disposable SYSTEM guest opt-in")
def test_actual_pid1_journal_event_survives_guest_reboot(tmp_path):
    with module().Guest(tmp_path) as guest:
        assert guest.run("cat /var/lib/cloud/data/instance-id").strip() == guest.instance_id
        boot = guest.run("cat /proc/sys/kernel/random/boot_id").strip()
        unit = "rosy-system-journal-proof.service"
        guest.run("systemd-run --unit=rosy-system-journal-proof --on-active=15s "
                  "--timer-property=AccuracySec=1s --property=Type=oneshot "
                  "/usr/bin/systemctl --no-block reboot")
        journal = guest._ssh("stdbuf -oL journalctl --boot --follow --unit=" + unit
                             + " --output=json --no-pager", timeout=180)
        module().pid1_start(journal.stdout, unit, boot, 0)
        assert guest.process.wait(timeout=90) == 0


@pytest.mark.skipif(os.environ.get("ROSY_RUN_OS_SYSTEM_TESTS") != "1", reason="explicit disposable SYSTEM guest opt-in")
def test_actual_private_mount_guard_without_pid1_ptrace_authority(tmp_path):
    with module().Guest(tmp_path) as guest:
        guest.provision_source(Path(__file__).resolve().parents[1])
        guest.run("cd /work/source && python3 -c \"import sys;from pathlib import Path;sys.path.insert(0,'test');"
                  "from test_os_frozen_firstboot import _prefix;_prefix(Path('/work/runtime'))\"")
        imports = ("import sys;from pathlib import Path;"
                   "sys.path.insert(0,'/work/runtime/opt/rosy/native-runtime');"
                   "from os_update_install import _namespace;\n")
        outside = imports + ("try:\n _namespace(Path('/'))\nexcept ValueError:\n print('HOST_REFUSED')\n"
                             "else:\n raise AssertionError('PID1 namespace was accepted')\n")
        command = ["nsenter", "--mount=/proc/1/ns/mnt", "--", "/usr/bin/python3", "-I", "-B", "-c", outside]
        assert guest.run(shlex.join(command)).strip() == "HOST_REFUSED"
        probe = imports + "_namespace(Path('/'));print('PRIVATE_NAMESPACE_OK')"
        command = ["systemd-run", "--wait", "--pipe", "--collect", "--unit=rosy-system-namespace",
                   "--property=PrivateMounts=true", "--property=ProtectSystem=strict",
                   "--property=NoNewPrivileges=true",
                   "--property=CapabilityBoundingSet=CAP_SYS_ADMIN CAP_MKNOD CAP_DAC_OVERRIDE",
                   "/usr/bin/python3", "-I", "-B", "-c", probe]
        assert guest.run(shlex.join(command)).strip() == "PRIVATE_NAMESPACE_OK"


@pytest.mark.skipif(os.environ.get("ROSY_RUN_OS_SYSTEM_TESTS") != "1", reason="explicit disposable SYSTEM guest opt-in")
def test_actual_systemd_device_allow_representation(tmp_path):
    with module().Guest(tmp_path) as guest:
        assert guest.run("cat /var/lib/cloud/data/instance-id").strip() == guest.instance_id
        root = "/dev/block/" + guest.run("cat /sys/class/block/vda/dev").strip()
        work = "/dev/block/" + guest.run("cat /sys/class/block/vdb/dev").strip()
        grants = [(root, "r"), (work, "rw"), ("/dev/loop-control", "rw"), ("block-loop", "rwm"),
                  ("/dev/mapper/control", "rw"), ("block-device-mapper", "rwm")]
        command = ["systemd-run", "--unit=rosy-system-device-grants", "--property=DevicePolicy=closed",
                   "--property=PrivateDevices=false", "--property=ProtectKernelLogs=true",
                   "--property=ProtectClock=true", "--property=ProtectSystem=strict"]
        command.extend("--property=DeviceAllow=" + path + " " + rights for path, rights in grants)
        command.extend(["/usr/bin/sleep", "300"])
        guest.run(shlex.join(command))
        try:
            raw = guest.run("systemctl show --value -p DeviceAllow rosy-system-device-grants.service").strip()
            words = shlex.split(raw)
            actual = list(zip(words[::2], words[1::2]))
            expected = grants + [("char-rtc", "r")]  # ProtectClock's actual systemd 255 implication.
            assert len(words) % 2 == 0 and len(actual) == len(expected) and set(actual) == set(expected), json.dumps(dict(raw=raw, expected=expected))
        finally:
            guest.run("systemctl stop rosy-system-device-grants.service")


def test_guest_download_rejects_hash_or_size_before_publishing(tmp_path):
    m = module()
    source = tmp_path / "upstream"
    source.write_bytes(b"known bytes")
    expected = dict(url=source.as_uri(), size_bytes=11, sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    m.download(expected, tmp_path / "verified")
    assert (tmp_path / "verified").read_bytes() == source.read_bytes()
    for field, value in (("size_bytes", 10), ("sha256", "0" * 64)):
        with pytest.raises(ValueError): m.download({**expected, field: value}, tmp_path / field)
        assert not (tmp_path / field).exists()


def test_cached_public_inputs_are_reverified_and_copied_independently(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "upstream"
    source.write_bytes(b"known bytes")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    expected = dict(url=source.as_uri(), size_bytes=11, sha256=sha)
    m.cached_input(expected, tmp_path / "first")
    (tmp_path / "first").write_bytes(b"guest writes")
    monkeypatch.setattr(m, "urlopen", lambda *a, **k: pytest.fail("verified cache was downloaded again"))
    m.cached_input(expected, tmp_path / "second")
    assert (tmp_path / "second").read_bytes() == b"known bytes"
    cached = tmp_path / "cache/rosy-os-system-inputs" / (sha + ".bin")
    cached.chmod(0o600)
    cached.write_bytes(b"bad cache!!")
    with pytest.raises(ValueError): m.cached_input(expected, tmp_path / "third")
    assert not (tmp_path / "third").exists()


def test_qemu_command_has_only_owned_images_and_loopback_ssh(tmp_path):
    m = module()
    vm = m.Guest(tmp_path)
    argv = vm.command(22022, 22023)
    assert "-accel" in argv and argv[argv.index("-accel") + 1] == "tcg"
    assert "hostfwd=tcp:127.0.0.1:22022-:22" in " ".join(argv)
    assert "-enable-kvm" not in argv
    assert all(value.startswith("file=" + str(tmp_path) + "/") for key, value in zip(argv, argv[1:]) if key == "-drive")
    assert all(str(tmp_path) in value for key, value in zip(argv, argv[1:]) if key in {"-kernel", "-initrd", "-bios"})


def test_early_guest_exit_retains_bounded_console_and_emulator_diagnostics(tmp_path):
    guest = module().Guest(tmp_path)
    guest.process = SimpleNamespace(poll=lambda: 0)
    (tmp_path / "qemu-stderr.log").write_text("emulator exit detail")
    (tmp_path / "guest-console.log").write_bytes(b"discarded-prefix" + b"x" * 6000 + b"guest reboot reason\xff")
    with pytest.raises(ValueError) as failure:
        guest.wait_boot()
    detail = str(failure.value)
    assert "emulator exit detail" in detail and "guest reboot reason" in detail
    assert "discarded-prefix" not in detail and len(detail) < 7500


def test_guest_source_provisioning_refuses_an_unbound_instance(tmp_path, monkeypatch):
    guest = module().Guest(tmp_path)
    calls = []
    def observe(command, **kwargs):
        calls.append(command)
        return "foreign-instance"
    monkeypatch.setattr(guest, "run", observe)
    with pytest.raises(ValueError, match="instance"):
        guest.provision_source(tmp_path)
    assert calls == ["cat /var/lib/cloud/data/instance-id"]


def test_nested_guest_failure_includes_bounded_stdout_diagnostics(tmp_path, monkeypatch):
    from types import SimpleNamespace
    guest = module().Guest(tmp_path)
    monkeypatch.setattr(guest, "_ssh", lambda *a, **k: SimpleNamespace(returncode=1,
        stdout=b"actual guest filesystem counterexample", stderr=b""))
    with pytest.raises(ValueError, match="actual guest filesystem counterexample"):
        guest.run("owned guest check")


@pytest.mark.parametrize("wrong_range", [False, True])
def test_large_guest_input_uses_exact_bounded_http_ranges(tmp_path, monkeypatch, wrong_range):
    import http.server
    import re
    import threading
    m = module()
    monkeypatch.setattr(m, "RANGE_BYTES", 8192, raising=False)
    monkeypatch.setattr(m, "RANGE_THRESHOLD", 8192, raising=False)
    data, requests = b"bounded upstream range data" * 1000, []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
            if not match:
                self.send_error(400)
                return
            start, end = map(int, match.groups())
            requests.append((start, end))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start + int(wrong_range)}-{end}/{len(data)}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.wfile.write(data[start:end + 1])
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    expected = dict(url=f"http://127.0.0.1:{server.server_port}/fixture", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    try:
        if wrong_range:
            with pytest.raises(ValueError): m.download(expected, tmp_path / "image")
            assert not (tmp_path / "image").exists()
        else:
            m.download(expected, tmp_path / "image")
            assert (tmp_path / "image").read_bytes() == data
            assert requests == [(start, min(start + 8191, len(data) - 1)) for start in range(0, len(data), 8192)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(os.environ.get("ROSY_RUN_OS_SYSTEM_TESTS") != "1", reason="explicit disposable SYSTEM guest opt-in")
def test_actual_guest_runs_pid1_without_host_privileges(tmp_path):
    m = module()
    with m.Guest(tmp_path) as guest:
        facts = guest.run("cat /proc/1/comm; systemctl --version | head -1; id -u; uname -m")
        assert facts.splitlines()[0] == "systemd"
        assert "systemd 255" in facts and "\n0\n" in facts and "x86_64" in facts
        # These block devices are guest-local virtual devices, never host hardware.
        assert "virtio" in guest.run("readlink -f /sys/class/block/vdb/device")
        guest.provision_source(Path(__file__).resolve().parents[1])
        report = guest.run("cd /work/source && ROSY_OS_GUEST=1 python3 -m pytest test/test_os_system_root.py -q -rA", timeout=600)
        assert "2 passed" in report and "SYSTEM actual fsck/owned-loop" in report, report
        assert "SYSTEM actual ext4/bind/numeric ownership/calibration approval/pin continuity" in report, report
