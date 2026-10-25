"""Real config application must survive A→B→A, including prior cached files."""
import json
from pathlib import Path

import pytest

from os_state_boot_fakes import shared_roots
from test_os_first_boot_state import SERIAL, _provision_a
from test_first_boot_provisioning import _bundle, _module as firstboot_module
from test_rosy_config_apply import _module as config_module


def _card(root, text):
    path = root / "boot/firmware/rosy-config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema_version: 1\n" + text, encoding="utf-8")
    return path


def test_actual_config_changes_and_applied_digest_survive_b_and_return_to_a(tmp_path, monkeypatch):
    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    card_a = _card(root_a, "ap:\n  mode: off\nlogin:\n  boot_code: off\n")
    applied = config_module().apply(root_a, lambda _: "")
    assert applied["state"] == "applied", applied
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    for relative in ("etc/rosy/network-policy.json", "etc/rosy/login-policy.json",
                     "var/lib/rosy/config/applied.json"):
        target = root_b / relative
        assert target.is_file(), f"config owner did not publish {relative} for B"
        assert target.read_bytes() == (root_a / relative).read_bytes()
    _card(root_b, "ap:\n  mode: always\nlogin:\n  boot_code: operator\n")
    assert config_module().apply(root_b, lambda _: "")["state"] == "applied"
    first.FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)
    assert json.loads((root_a / "etc/rosy/network-policy.json").read_text())["mode"] == "always"
    # The old card file is still present in A: the committed applied digest must be current too.
    assert card_a.exists()
    assert (root_a / "var/lib/rosy/config/applied.json").read_bytes() == (
        root_b / "var/lib/rosy/config/applied.json").read_bytes()


def test_config_during_initialization_is_not_overwritten_by_the_first_bundle(tmp_path, monkeypatch):
    root_a, root_b, _, _ = shared_roots(tmp_path, monkeypatch)
    _card(root_a, "ap:\n  mode: off\nlogin:\n  boot_code: off\n")
    assert config_module().apply(root_a, lambda _: "")["state"] == "applied"
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    first = firstboot_module()
    assert first.FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
        bundle=bundle, hardware_serial=SERIAL)["ok"]
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    path = root_b / "etc/rosy/network-policy.json"
    assert path.is_file(), "initial config must enter the first committed generation"
    assert json.loads(path.read_text())["mode"] == "off"


def test_timezone_is_root_specific_projection_of_the_same_committed_setting(tmp_path, monkeypatch):
    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    for root in (root_a, root_b):
        zone = root / "usr/share/zoneinfo/Asia/Seoul"
        zone.parent.mkdir(parents=True)
        zone.write_bytes(b"TZif synthetic zone payload")
    _card(root_a, "timezone: Asia/Seoul\n")
    assert config_module().apply(root_a, lambda _: "")["state"] == "applied"
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    target = root_b / "etc/localtime"
    assert target.is_symlink(), "timezone must be projected without running timedatectl on the test host"
    assert target.readlink() == Path("/usr/share/zoneinfo/Asia/Seoul")
