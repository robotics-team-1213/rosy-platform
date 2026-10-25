"""The real configuration owner must retain SSH readability and never follow home links."""
import base64
import json
import os
from pathlib import Path
import struct

import pytest

from test_os_first_boot_state import SERIAL, _provision_a
from test_os_shared_configuration import _card
from test_rosy_config_apply import _device, _module


def _key():
    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + b"\x06" * 32
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + " fixture-operator"


def test_config_key_is_installed_for_the_shared_operator_owner_and_survives_b(tmp_path, monkeypatch):
    first, root_a, root_b, common, bundle = _provision_a(tmp_path, monkeypatch)
    key = _key()
    _card(root_a, f"operator_ssh_keys:\n  - {key}\n")
    ownership = []

    def owned(descriptor, uid, gid):
        target = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        assert target.parent == common / "operator-ssh"
        ownership.append((uid, gid))

    monkeypatch.setattr(os, "fchown", owned)
    assert _module().apply(root_a, lambda _: "")["state"] == "applied"
    assert ownership == [(1001, 1001)], "sshd reads this 0600 file as the operator"
    assert first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    target = root_b / "home/rosy/.ssh/authorized_keys"
    assert key in target.read_text()
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("component", ["directory", "file"])
def test_config_does_not_follow_an_operator_key_symlink(tmp_path, component):
    module = _module()
    root = _device(tmp_path, f"schema_version: 1\noperator_ssh_keys:\n  - {_key()}\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "authorized_keys"
    external.write_text("original external data\n", encoding="ascii")
    directory = root / "home/rosy/.ssh"
    if component == "directory":
        directory.rmdir()
        directory.symlink_to(outside, target_is_directory=True)
    else:
        (directory / "authorized_keys").symlink_to(external)
    with pytest.raises(ValueError, match="operator key"):
        module.apply(root, lambda _: "")
    assert external.read_text() == "original external data\n"


def test_removed_card_key_is_not_restored_by_b_or_return_to_a(tmp_path, monkeypatch):
    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    _card(root_a, f"operator_ssh_keys:\n  - {_key()}\n")
    monkeypatch.setattr(os, "fchown", lambda *_: None)
    assert _module().apply(root_a, lambda _: "")["state"] == "applied"
    (root_a / "home/rosy/.ssh/authorized_keys").write_text("", encoding="utf-8")
    for root in (root_b, root_a):
        assert first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
        assert _module().apply(root, lambda _: "")["state"] == "unchanged"
        assert (root / "home/rosy/.ssh/authorized_keys").read_text() == ""


def test_managed_ssh_revoke_survives_b_and_return_to_a(tmp_path, monkeypatch):
    from test_ssh_access import FakeSystem, _run, ssh

    first, root_a, root_b, common, bundle = _provision_a(tmp_path, monkeypatch)
    request = {"public_key": _key(), "label": "fixture", "expires_days": 30}
    assert _run(root_a, FakeSystem(root_a), "add", **request)["status"] == 201
    assert _key() in (common / "ssh/authorized_keys").read_text()
    assert first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    assert len(ssh.load_keys(FakeSystem(root_b))) == 1
    assert _run(root_b, FakeSystem(root_b), "revoke", label="fixture")["status"] == 204
    for root in (root_a, root_b):
        assert first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
        assert ssh.prune_keys(FakeSystem(root)) == []
        assert (root / ssh.AUTHORIZED).read_text() == ""
    assert json.loads((common / "ssh/history.jsonl").read_text().splitlines()[-1])["event"] == "revoke"
