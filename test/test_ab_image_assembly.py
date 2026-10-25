"""Build resource ownership and cleanup, with no mounts or physical disks."""
import importlib.util
import json
from pathlib import Path
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
    assert calls[-2:] == [["umount", "--", str(tmp_path / "mounted")], ["losetup", "--detach", loop]]
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


def test_failed_detach_remains_owned_for_recovery(monkeypatch):
    m = module()
    monkeypatch.setattr(m, "_run", lambda command, **kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, command)))
    resources = m.ImageResources()
    resources.loops = ["/dev/loop17"]
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
