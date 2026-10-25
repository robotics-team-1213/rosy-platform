"""Readiness is produced from actual root readback, never a copied receipt."""
import json
import os

import pytest

from test_os_first_boot_state import SERIAL, _provision_a
from test_os_tailnet_state import _serial


def _device(tmp_path, monkeypatch):
    first, root, other, common, bundle = _provision_a(tmp_path, monkeypatch)
    for target in (root, other):
        _serial(target)
        hostname = target / "proc/sys/kernel/hostname"
        hostname.write_text("rosy-pinky-k7m4\n")
    return first, root, other, common, bundle


def test_real_root_projection_produces_receipt_and_each_slot_needs_its_own(tmp_path, monkeypatch):
    first, root, other, _, bundle = _device(tmp_path, monkeypatch)
    ready = first._native_helper("os_state_ready")
    report = ready.publish_ready(root)
    assert report["phase"] == "PROJECTED"
    assert report["slot"] == "a"
    path = root / "run/rosy-os-state/ready.json"
    assert json.loads(path.read_text()) == report
    assert path.stat().st_mode & 0o777 == 0o600
    assert ready.verify_ready(root) == report
    with pytest.raises(ValueError):
        ready.publish_ready(other)
    assert first.FirstBootProvisioner(root=other).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    second = ready.publish_ready(other)
    assert second["slot"] == "b"
    assert second["generation"] == report["generation"]
    assert second["descriptor_sha256"] != report["descriptor_sha256"]
    assert ready.verify_ready(other) == second


@pytest.mark.parametrize("change", ["file_bytes", "file_mode", "file_missing", "hard_link",
    "unexpected_optional", "timezone", "localtime", "hostname", "board", "tls_pending", "setup"])
def test_receipt_cannot_hide_current_root_or_authority_changes(tmp_path, monkeypatch, change):
    first, root, _, common, _ = _device(tmp_path, monkeypatch)
    ready = first._native_helper("os_state_ready")
    ready.publish_ready(root)
    target = root / "etc/rosy/runtime.env"
    if change == "file_bytes":
        target.write_bytes(target.read_bytes() + b"FOREIGN=1\n")
    elif change == "file_mode":
        target.chmod(0o644)
    elif change == "file_missing":
        target.unlink()
    elif change == "hard_link":
        os.link(target, root / "linked-runtime")
    elif change == "unexpected_optional":
        (root / "etc/rosy/login-policy.json").write_text("{}")
    elif change == "timezone":
        (root / "etc/timezone").write_text("Etc/Other\n")
    elif change == "localtime":
        (root / "etc/localtime").unlink()
        (root / "etc/localtime").symlink_to("/usr/share/zoneinfo/Etc/Other")
    elif change == "hostname":
        (root / "proc/sys/kernel/hostname").write_text("old-root-name\n")
    elif change == "board":
        _serial(root, "10000000abcdef02")
    elif change == "tls_pending":
        (common / "state/tls-pending.json").write_text("{}")
    elif change == "setup":
        (root / "var/lib/rosy/provisioning/new-device-setup.json").write_text("{}")
    with pytest.raises(ValueError):
        ready.verify_ready(root)
    with pytest.raises(ValueError):
        ready.publish_ready(root)


def test_root_readback_does_not_silently_repair_tampered_configuration(tmp_path, monkeypatch):
    first, root, _, common, _ = _device(tmp_path, monkeypatch)
    ready = first._native_helper("os_state_ready")
    target = root / "etc/rosy/runtime.env"
    target.write_text("UNTRUSTED=1\n")
    pointer = (common / "state/current.json").read_bytes()
    with pytest.raises(ValueError):
        ready.publish_ready(root)
    assert target.read_text() == "UNTRUSTED=1\n"
    assert (common / "state/current.json").read_bytes() == pointer
    assert not (root / "run/rosy-os-state/ready.json").exists()
