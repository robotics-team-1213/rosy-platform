"""Real OpenSSH keys, modeled A/B mounts; no SSH daemon or device is started."""
import importlib.util
from pathlib import Path

import pytest

from os_state_boot_fakes import shared_roots
from test_os_first_boot_state import _provision_a


NATIVE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"


def _module():
    spec = importlib.util.spec_from_file_location("os_ssh_keys_test", NATIVE / "os_ssh_hostkeys.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_same_regular_host_key_survives_root_switch_and_stale_root_copy(tmp_path, monkeypatch):
    root, other, common, _ = shared_roots(tmp_path, monkeypatch)
    helper = _module()
    helper.prepare(root)
    private = (root / "etc/ssh/ssh_host_ed25519_key").read_bytes()
    public = (root / "etc/ssh/ssh_host_ed25519_key.pub").read_bytes()
    helper.prepare(other)
    for slot in (root, other):
        path = slot / "etc/ssh/ssh_host_ed25519_key"
        assert path.read_bytes() == private and not path.is_symlink()
        assert path.stat().st_mode & 0o7777 == 0o600
        assert path.with_suffix(".pub").read_bytes() == public
    (root / "etc/ssh/ssh_host_ed25519_key.pub").write_text("stale root copy\n")
    helper.prepare(root)
    assert (root / "etc/ssh/ssh_host_ed25519_key.pub").read_bytes() == public
    assert (common / "ssh-hostkeys/ssh_host_ed25519_key").read_bytes() == private


@pytest.mark.parametrize("case", ["private_mode", "public_mismatch", "hardlink", "symlink", "extra"])
def test_corrupt_common_keys_hold_without_overwriting_the_other_root(tmp_path, monkeypatch, case):
    root, other, common, _ = shared_roots(tmp_path, monkeypatch)
    helper = _module()
    helper.prepare(root)
    keys = common / "ssh-hostkeys"
    private, public = keys / "ssh_host_ed25519_key", keys / "ssh_host_ed25519_key.pub"
    if case == "private_mode":
        private.chmod(0o644)
    elif case == "public_mismatch":
        public.write_text("ssh-ed25519 invalid\n")
    elif case == "hardlink":
        (common / "alias").hardlink_to(private)
    elif case == "symlink":
        private.rename(common / "outside")
        private.symlink_to(common / "outside")
    else:
        (keys / "unexpected").write_text("unowned")
    with pytest.raises(ValueError):
        helper.prepare(other)
    assert not (other / "etc/ssh/ssh_host_ed25519_key").exists()


def test_missing_keys_on_committed_device_do_not_silently_rotate_identity(tmp_path, monkeypatch):
    _, root, _, common, _ = _provision_a(tmp_path, monkeypatch)
    assert not (common / "ssh-hostkeys").exists()
    with pytest.raises(ValueError, match="missing"):
        _module().prepare(root)
    assert not (common / "ssh-hostkeys").exists()


def test_legacy_root_is_not_modified(tmp_path):
    assert _module().prepare(tmp_path) == "LEGACY"
    assert not list(tmp_path.iterdir())
