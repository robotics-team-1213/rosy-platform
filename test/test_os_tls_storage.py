"""TLS storage is shared live state; an invalid bind must stop initial mutation."""
import json
import os
from types import SimpleNamespace

import pytest

from os_state_boot_fakes import shared_roots
from test_first_boot_provisioning import _bundle, _module
from test_os_first_boot_state import SERIAL, _provision_a


@pytest.mark.parametrize("change", ["missing", "wrong-subpath", "read-only"])
def test_tls_bind_is_required_before_firstboot_mutation(tmp_path, monkeypatch, change):
    root, _, common, _ = shared_roots(tmp_path, monkeypatch)
    for relative in ("proc/1/mountinfo", "proc/self/mountinfo"):
        path = root / relative
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if " /etc/rosy/tls " in line:
                if change == "missing":
                    lines[index] = ""
                elif change == "wrong-subpath":
                    lines[index] = line.replace("8:6 /tls ", "8:6 /old-tls ")
                else:
                    lines[index] = line.replace("/etc/rosy/tls rw", "/etc/rosy/tls ro")
        path.write_text("\n".join(line for line in lines if line) + "\n")
    bundle = root / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()))
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module().FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)
    assert not (root / "etc/rosy/device-identity.json").exists()
    assert not (common / "state/current.json").exists()
    assert bundle.exists()


@pytest.mark.parametrize("change", ["owner", "group", "permissions"])
def test_foreign_tls_directory_is_not_reowned_or_used(tmp_path, monkeypatch, change):
    root, _, common, _ = shared_roots(tmp_path, monkeypatch)
    original_stat = os.stat

    def changed(path, *args, **kwargs):
        info = original_stat(path, *args, **kwargs)
        if os.fspath(path) == str(root / "etc/rosy/tls"):
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            fields[{"owner": "st_uid", "group": "st_gid", "permissions": "st_mode"}[change]] = {
                "owner": 4242, "group": 4242, "permissions": info.st_mode | 0o002}[change]
            return SimpleNamespace(**fields)
        return info

    monkeypatch.setattr(os, "stat", changed)
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module().FirstBootProvisioner(root=root).apply(
            bundle=root / "run/rosy-provision-boot/rosy-provision/provision.json", hardware_serial=SERIAL)
    assert not (common / "state/current.json").exists()
    assert not (root / "etc/rosy/device-identity.json").exists()


def test_tls_rotation_and_removed_key_survive_b_and_return_to_a(tmp_path, monkeypatch):
    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    for relative, data in (("ca.pem", b"fixture retained CA"), ("leaf.key", b"fixture old key")):
        (root_a / "etc/rosy/tls" / relative).write_bytes(data)
    assert first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    assert (root_b / "etc/rosy/tls/ca.pem").read_bytes() == b"fixture retained CA"
    (root_b / "etc/rosy/tls/leaf.key").unlink()
    (root_b / "etc/rosy/tls/ca.pem").write_bytes(b"fixture rotated CA")
    for root in (root_a, root_b):
        assert first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
        assert not (root / "etc/rosy/tls/leaf.key").exists()
        assert (root / "etc/rosy/tls/ca.pem").read_bytes() == b"fixture rotated CA"
