"""Real signatures and four-file writes; mounts/block identity/fsck are explicit kernel models."""
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
import uuid

import pytest

from test_factory_release_signature import _keys, FACTORY_ID
from test_os_factory_release import _factory
from test_os_bootloader import _boot, _permit
from test_os_update_state import TRANSACTION


def _installer(tmp_path, monkeypatch, fault=None):
    boot, state, root, journal, config = _boot(tmp_path / "card", monkeypatch, "INSTALLING")
    _permit(boot, state, root)
    import os_motion_guard
    os_motion_guard.reconcile(root)
    module = importlib.import_module("os_update_install")
    parent = root / Path(module.WORK).parent
    parent.mkdir(parents=True, mode=0o700)
    parent.chmod(0o700)
    media = importlib.import_module("os_media").capture(root)
    private, public = _keys(tmp_path / "offline", "fixture")
    key = root / "etc/rosy/trusted-release-keys" / public.name
    key.parent.mkdir(parents=True)
    key.write_bytes(public.read_bytes())
    candidate = tmp_path / "factory"
    release, _ = _factory(candidate, FACTORY_ID, private, public, signed=True)
    boot_files = tmp_path / "boot-files"
    boot_files.mkdir()
    layout = copy.deepcopy(media["layout"])
    layout["disk_guid"] = str(uuid.uuid4())
    for part in layout["partitions"]: part["unique_guid"] = str(uuid.uuid4())
    from os_slot_metadata import render_files
    original = render_files(layout, "a", "root=LABEL=writable rootwait")
    for name, text in original.items():
        path = boot_files / name if name == "cmdline.txt" else candidate / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    value = json.loads(journal.read_text())
    descriptor = json.loads((candidate / "etc/rosy/os-factory-release.json").read_text())
    value["pending"]["verified"]["metadata"]["native_factory"] = {k: descriptor[k] for k in ("release_id", "checksums_sha256")}
    nodes = {}
    for role, field, data in (("root_b", "rootfs", b"r" * 1024), ("boot_b", "boot", b"b" * 512)):
        node = root / media["partitions"][role]["path"].lstrip("/")
        node.write_bytes(data)
        nodes[str(node)] = media["partitions"][role]["device"]
        value["pending"]["verified"]["images"][field]["sha256"] = hashlib.sha256(data).hexdigest()
    journal.write_text(json.dumps(value))
    for process, namespace in (("self", "2"), ("1", "1")):
        path = root / f"proc/{process}/ns/mnt"
        path.parent.mkdir(parents=True)
        path.symlink_to(f"mnt:[{namespace}]")
    calls, mounted = [], {}
    actual_stat, actual_fstat = os.stat, os.fstat
    work = root / module.WORK
    sources = {"root": candidate, "boot": boot_files}
    def changed(info, **values):
        return SimpleNamespace(**{**{n: getattr(info, n) for n in dir(info) if n.startswith("st_")}, **values})
    def observed_stat(path, *args, **kwargs):
        info = actual_stat(path, *args, **kwargs)
        if str(path) in mounted:
            return changed(info, st_dev=os.makedev(*map(int, mounted[str(path)]["device"].split(":"))))
        return info
    def observed_fstat(fd):
        info = actual_fstat(fd)
        path = os.readlink(f"/proc/self/fd/{fd}")
        if path in nodes:
            return changed(info, st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(*map(int, nodes[path].split(":"))))
        return info
    monkeypatch.setattr(os, "stat", observed_stat)
    monkeypatch.setattr(os, "fstat", observed_fstat)
    mountinfo = root / "proc/self/mountinfo"
    initial_mounts = mountinfo.read_text()
    writes = []
    real_write = module._write_atomic
    def write(path, content, mode):
        if path.is_relative_to(work):
            owner = next((row for target, row in mounted.items() if path.is_relative_to(target)), None)
            assert owner and owner["rw"], "metadata writes require admitted rw mount"
            writes.append(path.relative_to(work).as_posix())
            if fault == "write" and len(writes) == 2: raise OSError("modeled write loss")
        real_write(path, content, mode)
    monkeypatch.setattr(module, "_write_atomic", write)
    rounds = {"root": 0, "boot": 0}
    def run(argv, timeout=300):
        calls.append(argv)
        if argv[:2] == ["/usr/bin/mount", "--make-rprivate"]:
            assert argv == ["/usr/bin/mount", "--make-rprivate", "/"]
        elif argv[0] == "/usr/bin/mount":
            device, target = argv[-2:]
            name = Path(target).name
            assert device in nodes and target == str(work / name)
            filesystem = "ext4" if name == "root" else "vfat"
            assert argv[argv.index("-t") + 1] == filesystem
            options = argv[argv.index("-o") + 1].split(",")
            assert {"nodev", "nosuid", "noexec"} <= set(options)
            Path(target).rmdir()
            sources[name].rename(target)
            rounds[name] += 1
            if fault == "readback" and name == "root" and rounds[name] == 3:
                (Path(target) / "etc/fstab").write_text("corrupt after flush")
            mounted[target] = dict(device=nodes[device], rw="rw" in options, name=name)
        elif argv[0] == "/usr/bin/umount":
            target = argv[-1]
            if fault == "unmount": return subprocess.CompletedProcess(argv, 1, "", "modeled unmount failure")
            row = mounted.pop(target)
            Path(target).rename(sources[row["name"]])
            Path(target).mkdir(mode=0o700)
        elif argv[0] in ("/usr/sbin/e2fsck", "/usr/sbin/fsck.fat", "/usr/sbin/blockdev"):
            assert argv[-1] in nodes and not mounted, "never fsck or flush a mounted target"
        else:
            assert argv[:2] == ["/usr/bin/sync", "-f"]
            assert argv[-1] in mounted and mounted[argv[-1]]["rw"]
        rows = [f"{20+i} 0 {row['device']} / /{Path(target).relative_to(root).as_posix()} "
                f"{'rw' if row['rw'] else 'ro'},nodev,nosuid,noexec - {'ext4' if row['name']=='root' else 'vfat'} "
                f"/dev/block/{row['device']} {'rw' if row['rw'] else 'ro'}\n" for i, (target, row) in enumerate(mounted.items())]
        mountinfo.write_text(initial_mounts + "".join(rows))
        return subprocess.CompletedProcess(argv, 0, "", "")
    return module, root, journal, config, sources, release, original, calls, writes, run, nodes


def test_finalize_reads_back_inactive_images_and_rebases_only_four_files_then_reports(tmp_path, monkeypatch):
    m, root, journal, config, sources, release, original, calls, writes, run, _ = _installer(tmp_path, monkeypatch)
    signature = (release / "SHA256SUMS.sig").read_bytes()
    before = config.read_bytes(), journal.read_bytes()
    result = m.finalize(root, run=run)
    assert result == m.read_report(root)
    assert result["transaction_id"] == TRANSACTION and result["target_slot"] == "b"
    assert json.loads((sources["root"] / "etc/rosy/os-slot.json").read_text())["slot"] == "b"
    assert len(writes) == 4 and set(writes) == {"root/etc/fstab", "root/etc/rosy/os-slot.json", "root/etc/rosy/os-media.json", "boot/cmdline.txt"}
    assert (release / "SHA256SUMS.sig").read_bytes() == signature
    assert (config.read_bytes(), journal.read_bytes()) == before
    assert not (root / m.WORK).exists()
    assert all(not any("tryboot" in str(arg) for arg in argv) for argv in calls)


@pytest.mark.parametrize("fault", ["root_hash", "boot_hash", "namespace", "write", "unmount", "readback", "foreign"])
def test_failure_never_reports_or_changes_default_or_phase(tmp_path, monkeypatch, fault):
    m, root, journal, config, _, _, _, calls, writes, run, nodes = _installer(tmp_path, monkeypatch, fault)
    if fault in ("root_hash", "boot_hash"):
        path = next(path for path, device in nodes.items() if device == ("8:5" if fault == "root_hash" else "8:3"))
        Path(path).write_bytes(b"wrong")
    elif fault == "namespace":
        path = root / "proc/self/ns/mnt"
        path.unlink()
        path.symlink_to("mnt:[1]")
    elif fault == "foreign":
        work = root / m.WORK
        work.mkdir(parents=True, mode=0o700)
        (work / "keep").write_text("unknown")
    before = config.read_bytes(), journal.read_bytes()
    with pytest.raises((ValueError, OSError)):
        m.finalize(root, run=run)
    assert (config.read_bytes(), journal.read_bytes()) == before
    assert not m.report_path(root).exists()
    if fault in ("root_hash", "boot_hash", "namespace", "foreign"): assert writes == []
    if fault == "foreign": assert (root / m.WORK / "keep").read_text() == "unknown"


def test_fixture_root_never_runs_host_mount_or_fsck(tmp_path, monkeypatch):
    m, root, *_ = _installer(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="real root"):
        m.finalize(root)


def test_receipt_nested_schema_bool_is_not_an_integer(tmp_path, monkeypatch):
    m, root, *rest = _installer(tmp_path, monkeypatch)
    m.finalize(root, run=rest[-2])
    path = m.report_path(root)
    value = json.loads(path.read_text())
    value["native_factory"]["schema_version"] = True
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.read_report(root)


def test_frozen_finalizer_entrypoint_and_receipt_reader_need_no_mutable_sdk(tmp_path, monkeypatch):
    import sys
    from test_os_frozen_firstboot import _prefix, _stage
    m, root, *rest = _installer(tmp_path / "device", monkeypatch)
    m.finalize(root, run=rest[-2])
    prefix = _prefix(tmp_path / "installed")
    _stage(prefix)
    for folder in (prefix / "native-runtime", prefix / "deploy/sd"):
        for path in folder.glob("*.py"):
            path.write_text("raise RuntimeError('mutable SDK imported')\n")
    frozen = prefix / "os-bootstrap/native-runtime"
    entry = frozen / "rosy-os-finalize"
    assert os.access(entry, os.X_OK)
    result = subprocess.run([str(entry), "--help"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    code = """
import sys
from pathlib import Path
frozen=Path(sys.argv[1]);sys.path[:0]=[str(frozen),str(frozen.parent.parent/'native-runtime')]
import os_update_state,os_update_install
os_update_state.mount_facts=lambda *args: []
assert os_update_install.read_report(Path(sys.argv[2]))['transaction_id']==sys.argv[3]
for name in ('os_update_install','os_installed_factory','native_release','signing','os_slot_metadata','os_bootloader'):
    assert Path(sys.modules[name].__file__).is_relative_to(frozen)
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(frozen), str(root), TRANSACTION],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
