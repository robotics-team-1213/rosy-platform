"""Build resource ownership and cleanup, with no mounts or physical disks."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from test_ab_image_layout import IMAGE


def module():
    spec = importlib.util.spec_from_file_location("assemble_ab_test", IMAGE / "assemble-ab-image.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_loop_is_bound_to_the_new_regular_file_and_closes_after_mounts(tmp_path, monkeypatch):
    m = module()
    image = tmp_path / "new.img"
    image.write_bytes(b"fixture")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["losetup", "--find"]:
            return SimpleNamespace(stdout="/dev/loop17\n")
        if "--json" in command:
            return SimpleNamespace(stdout=json.dumps({"loopdevices": [{"name": "/dev/loop17", "back-file": str(image)}]}))
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(m, "_run", run)
    resources = m.ImageResources()
    loop = resources.loop(image, readonly=True)
    resources.mount(loop + "p2", tmp_path / "mounted", readonly=True, filesystem="ext4")
    resources.close()
    assert "--read-only" in calls[0]
    assert calls.index(["umount", "--", str(tmp_path / "mounted")]) < calls.index(["losetup", "--detach", loop])
    assert "ro,noload" in next(command for command in calls if command[0] == "mount")


def test_failed_unmount_never_detaches_the_loop_or_reports_clean(tmp_path, monkeypatch):
    m = module()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "umount":
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(m, "_run", run)
    resources = m.ImageResources()
    resources.loops = ["/dev/loop17"]
    resources.mounts = [tmp_path / "still-mounted"]
    with pytest.raises(OSError, match="unmount"):
        resources.close()
    assert resources.mounts == [tmp_path / "still-mounted"]
    assert resources.loops == ["/dev/loop17"]
    assert not any(command[0] == "losetup" for command in calls)


def test_failed_detach_remains_owned_for_recovery(tmp_path, monkeypatch):
    m = module()
    image = tmp_path / "owned.img"
    image.write_bytes(b"fixture")

    def run(command, **kwargs):
        if "--json" in command:
            return SimpleNamespace(stdout=json.dumps({"loopdevices": [{"name": "/dev/loop17", "back-file": str(image)}]}))
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(m, "_run", run)
    resources = m.ImageResources()
    resources.loops = ["/dev/loop17"]
    resources.images = {"/dev/loop17": image}
    with pytest.raises(OSError, match="detach"):
        resources.close()
    assert resources.loops == ["/dev/loop17"]


@pytest.mark.parametrize("case", ["source_symlink", "existing_output", "existing_metadata", "source_writable"])
def test_input_rejection_preserves_source_and_existing_outputs(tmp_path, case):
    m = module()
    source, output = tmp_path / "source.img", tmp_path / "output.img"
    source.write_bytes(b"source must stay intact")
    source.chmod(0o644)
    if case == "source_symlink":
        alias = tmp_path / "alias.img"
        alias.symlink_to(source)
        source = alias
    elif case == "existing_output":
        output.write_bytes(b"existing output")
    elif case == "existing_metadata":
        output.with_suffix(".layout.json").write_text("existing layout")
    else:
        source.chmod(0o666)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    with pytest.raises(ValueError):
        m.checked_inputs(source, output, tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_non_native_builder_is_rejected_before_creating_output(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    monkeypatch.setattr(m.platform, "machine", lambda: "x86_64")
    with pytest.raises(ValueError, match="native arm64"):
        m.assemble(tmp_path / "source.img", tmp_path / "out.img", tmp_path, "2026.10.26-001")
    assert not list(tmp_path.iterdir())


def test_mismatched_loop_backing_is_not_detached_by_cleanup(tmp_path, monkeypatch):
    m = module()
    image, foreign = tmp_path / "owned.img", tmp_path / "foreign.img"
    image.write_bytes(b"owned")
    foreign.write_bytes(b"do not touch")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "--find" in command:
            return SimpleNamespace(stdout="/dev/loop17\n")
        if "--json" in command:
            return SimpleNamespace(stdout=json.dumps({"loopdevices": [{"name": "/dev/loop17", "back-file": str(foreign)}]}))
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(m, "_run", run)
    resources = m.ImageResources()
    with pytest.raises(ValueError, match="bound"):
        resources.loop(image)
    with pytest.raises(OSError, match="detach"):
        resources.close()
    assert not any("--detach" in command for command in calls)


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_failed_assembly_only_removes_workspace_after_resources_close(tmp_path, monkeypatch, cleanup_fails):
    m = module()
    source, output = tmp_path / "source.img", tmp_path / "output.img"
    source.write_bytes(b"fixture source")
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    monkeypatch.setattr(m.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(m, "checked_inputs", lambda *args: (source, output, tmp_path))
    monkeypatch.setattr(m.shutil, "which", lambda *args: "/fixture/tool")

    class Resources:
        def loop(self, *args, **kwargs):
            return "/dev/loop17"

        def mount(self, *args, **kwargs):
            raise RuntimeError("injected mount failure")

        def close(self):
            if cleanup_fails:
                raise OSError("injected detach failure")

    monkeypatch.setattr(m, "ImageResources", Resources)
    monkeypatch.setattr(m, "_run", lambda command, **kwargs: SimpleNamespace(
        stdout="vfat" if command[-1].endswith("p1") else "ext4"))
    with pytest.raises(OSError if cleanup_fails else RuntimeError, match="injected"):
        m.assemble(source, output, tmp_path, "2026.10.26-001")
    assert bool(list(tmp_path.glob("rosy-ab-image.*"))) is cleanup_fails
    assert bool(list(tmp_path.glob("output.img.part.*"))) is cleanup_fails
    assert not output.exists()
    assert source.read_bytes() == b"fixture source"


@pytest.mark.skipif(shutil.which("sfdisk") is None, reason="sfdisk constructs the real GPT table")
def test_orchestration_executes_real_slot_configurers_before_publishing(tmp_path, monkeypatch):
    """Loop/mount/fsck/rsync are models; GPT and installed configurers are real."""
    from test_os_factory_release import _factory, _keys, FACTORY_ID
    from test_os_frozen_firstboot import _prefix, _stage

    m = module()
    source_root, source_boot = tmp_path / "root-tree", tmp_path / "boot-tree"
    source_root.mkdir()
    source_boot.mkdir()
    private, public = _keys(tmp_path / "offline", "fixture")
    _factory(source_root, FACTORY_ID, private, public)
    _stage(_prefix(source_root))
    (source_root / "etc/fstab").write_text(
        "LABEL=writable / ext4 defaults 0 1\nLABEL=system-boot /boot/firmware vfat defaults 0 1\n")
    users = [("rosy-core", 960), ("rosy-io", 961), ("rosy-display", 962), ("rosy-camera", 963), ("rosy", 1001)]
    (source_root / "etc/passwd").write_text("".join(
        f"{name}:x:{uid}:{uid}::{('/home/rosy' if name == 'rosy' else '/nonexistent')}:"
        f"{('/bin/bash' if name == 'rosy' else '/usr/sbin/nologin')}\n" for name, uid in users))
    (source_root / "etc/group").write_text("".join(f"{name}:x:{uid}:\n" for name, uid in users)
                                            + "rosy-calib:x:964:\n")
    (source_boot / "cmdline.txt").write_text("root=LABEL=writable rootwait\n")
    (source_boot / "config.txt").write_text("# model boot assets\n")
    source, output = tmp_path / "source.img", tmp_path / "assembled.img"
    source.write_bytes(b"model source disk")
    captures, commands = {}, []

    class Resources:
        def loop(self, image, **kwargs):
            return "/dev/loop17" if image == source else "/dev/loop18"

        def mount(self, device, target, **kwargs):
            target.mkdir()
            tree = source_root if device == "/dev/loop17p2" else source_boot if device == "/dev/loop17p1" else None
            if tree:
                shutil.copytree(tree, target, dirs_exist_ok=True, symlinks=True)
            captures[target.name] = target

        def unmount_all(self):
            for slot in ("a", "b"):
                root = captures["root_" + slot]
                captures["descriptor_" + slot] = json.loads((root / "etc/rosy/os-slot.json").read_text())
                captures["factory_" + slot] = json.loads((root / "etc/rosy/os-factory-release.json").read_text())
                captures["ssh_" + slot] = (root / "etc/systemd/system/rosy-os-storage.service.d/10-rosy-os.conf").read_text()

        def close(self):
            pass

    actual_run = m._run

    def run(command, **kwargs):
        commands.append(command)
        if command[0] in ("sfdisk", "du", m.sys.executable):
            return actual_run(command, **kwargs)
        if command[0] == "blkid":
            return SimpleNamespace(stdout="vfat" if command[-1].endswith("p1") else "ext4")
        if command[0] == "rsync":
            shutil.copytree(Path(command[-2]), Path(command[-1]), dirs_exist_ok=True, symlinks=True)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(m, "_require_native", lambda: None)
    monkeypatch.setattr(m, "ImageResources", Resources)
    monkeypatch.setattr(m, "_run", run)
    monkeypatch.setattr(m.shutil, "which", lambda command: "/fixture/tool")
    monkeypatch.setattr(m.ab.os, "chown", lambda *args: None)
    result = m.assemble(source, output, tmp_path, FACTORY_ID)
    layout = json.loads(Path(result["layout"]).read_text())
    assert m.ab.filesystem_plan(output, layout)[-1] == (6, "ext4")
    assert captures["descriptor_a"]["root_partuuid"] != captures["descriptor_b"]["root_partuuid"]
    assert captures["descriptor_a"]["data_partuuid"] == captures["descriptor_b"]["data_partuuid"]
    assert captures["factory_a"] == captures["factory_b"]
    assert "os_ssh_hostkeys.py" in captures["ssh_a"] and "os_ssh_hostkeys.py" in captures["ssh_b"]
    assert sum(command[0] == "fsck.vfat" for command in commands) == 3
    assert sum(command[0] == "e2fsck" for command in commands) == 3
    assert source.read_bytes() == b"model source disk"
    assert not list(tmp_path.glob("rosy-ab-image.*"))
