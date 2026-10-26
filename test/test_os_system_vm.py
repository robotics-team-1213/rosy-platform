"""Opt-in disposable guest verification; never a release-image builder or a host installer."""
import hashlib
import importlib
import os
from pathlib import Path

import pytest


def module():
    return importlib.import_module("os_system_vm")


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


def test_qemu_command_has_only_owned_images_and_loopback_ssh(tmp_path):
    m = module()
    vm = m.Guest(tmp_path)
    argv = vm.command(22022, 22023)
    assert "-accel" in argv and argv[argv.index("-accel") + 1] == "tcg"
    assert "hostfwd=tcp:127.0.0.1:22022-:22" in " ".join(argv)
    assert "-enable-kvm" not in argv and "/dev/" not in " ".join(argv)
    assert all(str(tmp_path) in value for key, value in zip(argv, argv[1:]) if key in {"-kernel", "-initrd", "-bios"})


@pytest.mark.skipif(os.environ.get("ROSY_RUN_OS_SYSTEM_TESTS") != "1", reason="explicit disposable SYSTEM guest opt-in")
def test_actual_guest_runs_pid1_without_host_privileges(tmp_path):
    m = module()
    with m.Guest(tmp_path) as guest:
        facts = guest.run("cat /proc/1/comm; systemctl --version | head -1; id -u; uname -m")
        assert facts.splitlines()[0] == "systemd"
        assert "systemd 255" in facts and "\n0\n" in facts and "x86_64" in facts
        # These block devices are guest-local virtual devices, never host hardware.
        assert "virtio" in guest.run("readlink -f /sys/class/block/vdb/device")
