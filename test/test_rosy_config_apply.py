"""Apply rosy-config.yaml at boot and scrub its passwords from the card (D-176 Task 2)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"
PASSWORD = "site-" + "wifi-" + "pass"
AP_PASSWORD = "robot-" + "ap-" + "pass"


def _module():
    sys.path.insert(0, str(NATIVE))
    spec = importlib.util.spec_from_file_location("rosy_config_apply", NATIVE / "rosy-config-apply.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _device(tmp_path: Path, config: str) -> Path:
    root = tmp_path / "device"
    (root / "boot/firmware").mkdir(parents=True)
    (root / "boot/firmware/rosy-config.yaml").write_text(config, encoding="utf-8")
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/defaults.yaml").write_text((NATIVE / "defaults.yaml").read_text(encoding="utf-8"),
                                                 encoding="utf-8")
    (root / "etc/rosy/fleet-bootstrap.json").write_text(
        json.dumps({"endpoint": "https://perpros.local", "trust_profile": "rosy-pilot-lan",
                    "pairing_required": False}), encoding="utf-8")
    (root / "etc/NetworkManager/system-connections").mkdir(parents=True)
    (root / "home/rosy/.ssh").mkdir(parents=True)
    return root


def _apply(module, root):
    calls: list[list[str]] = []
    result = module.apply(root, lambda command: calls.append(command) or "")
    return result, calls


CONFIG = (
    "# Edit on any PC. Passwords are replaced by <applied> after the robot applies them.\n"
    "schema_version: 1\n"
    "timezone: Asia/Seoul\n"
    "wifi:\n"
    "  - ssid: site-5g\n"
    f"    password: {PASSWORD}\n"
    "    priority: 20\n"
    "ap:\n"
    "  mode: fallback\n"
    f"  password: {AP_PASSWORD}\n"
    "fleet:\n"
    "  endpoint: https://fleet.example.invalid\n"
)


def _profiles(root):
    return sorted((root / "etc/NetworkManager/system-connections").glob("rosy-wifi-*.nmconnection"))


def test_wifi_fleet_ap_and_timezone_are_applied_and_passwords_leave_the_card(tmp_path):
    module = _module()
    root = _device(tmp_path, CONFIG)

    result, calls = _apply(module, root)

    assert result["state"] == "applied"
    [profile] = _profiles(root)
    text = profile.read_text(encoding="utf-8")
    assert "ssid=site-5g" in text and "autoconnect-priority=20" in text
    assert PASSWORD not in text and "psk=" in text
    if os.name == "posix":
        assert profile.stat().st_mode & 0o777 == 0o600
    card = (root / "boot/firmware/rosy-config.yaml").read_text(encoding="utf-8")
    assert PASSWORD not in card and AP_PASSWORD not in card
    assert card.count('"<applied>"') == 2
    assert card.startswith("# Edit on any PC.")  # comments and layout survive
    fleet = json.loads((root / "etc/rosy/fleet-bootstrap.json").read_text(encoding="utf-8"))
    assert fleet["endpoint"] == "https://fleet.example.invalid"
    assert fleet["trust_profile"] == "rosy-pilot-lan"
    policy = json.loads((root / "etc/rosy/network-policy.json").read_text(encoding="utf-8"))
    assert policy["mode"] == "fallback" and policy["grace_seconds"] == 120
    assert AP_PASSWORD not in json.dumps(policy)
    assert json.loads((root / "etc/rosy/ap-credentials.json").read_text(encoding="utf-8"))["password"] == AP_PASSWORD
    assert ["timedatectl", "set-timezone", "Asia/Seoul"] in calls
    assert ["nmcli", "connection", "reload"] in calls


def test_the_same_file_is_not_applied_twice(tmp_path):
    module = _module()
    root = _device(tmp_path, CONFIG)
    _apply(module, root)
    profile = _profiles(root)[0]
    before = profile.stat().st_mtime_ns

    result, calls = _apply(module, root)

    assert result["state"] == "unchanged"
    assert profile.stat().st_mtime_ns == before
    assert calls == []


def test_an_invalid_file_applies_nothing_and_says_why(tmp_path):
    module = _module()
    root = _device(tmp_path, "schema_version: 1\nrobot_number: 3\n")

    result, calls = _apply(module, root)

    assert result["state"] == "invalid"
    assert "identity" in result["error"]
    assert _profiles(root) == []
    status = json.loads((root / "run/rosy-boot/config-status.json").read_text(encoding="utf-8"))
    assert status["state"] == "invalid"
    assert calls == []


def test_networks_removed_from_the_file_are_removed_from_the_robot(tmp_path):
    module = _module()
    root = _device(tmp_path, CONFIG)
    _apply(module, root)
    (root / "boot/firmware/rosy-config.yaml").write_text(
        f"schema_version: 1\nwifi:\n  - ssid: backup\n    password: {PASSWORD}\n", encoding="utf-8")

    _apply(module, root)

    [profile] = _profiles(root)
    assert "ssid=backup" in profile.read_text(encoding="utf-8")


def test_an_applied_password_keeps_the_existing_profile(tmp_path):
    module = _module()
    root = _device(tmp_path, CONFIG)
    _apply(module, root)
    psk_line = next(line for line in _profiles(root)[0].read_text(encoding="utf-8").splitlines()
                    if line.startswith("psk="))
    card = (root / "boot/firmware/rosy-config.yaml")
    card.write_text(card.read_text(encoding="utf-8").replace("priority: 20", "priority: 30"), encoding="utf-8")

    result, _calls = _apply(module, root)

    assert result["state"] == "applied"
    text = _profiles(root)[0].read_text(encoding="utf-8")
    assert psk_line in text and "autoconnect-priority=30" in text


def test_flow_style_yaml_is_still_scrubbed(tmp_path):
    module = _module()
    root = _device(tmp_path, "{schema_version: 1, wifi: [{ssid: a, password: " + PASSWORD + "}]}\n")

    result, _calls = _apply(module, root)

    assert result["state"] == "applied"
    card = (root / "boot/firmware/rosy-config.yaml").read_text(encoding="utf-8")
    assert PASSWORD not in card and "<applied>" in card


def test_operator_keys_from_the_file_join_the_existing_ones(tmp_path):
    module = _module()
    import base64
    import struct

    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + b"\x05" * 32
    key = "ssh-ed25519 " + base64.b64encode(blob).decode() + " field@laptop"
    root = _device(tmp_path, f"schema_version: 1\noperator_ssh_keys:\n  - {key}\n")
    (root / "home/rosy/.ssh/authorized_keys").write_text("ssh-ed25519 AAAAexisting old\n", encoding="utf-8")

    _apply(module, root)

    keys = (root / "home/rosy/.ssh/authorized_keys").read_text(encoding="utf-8").splitlines()
    assert keys == ["ssh-ed25519 AAAAexisting old", key]


def test_no_file_means_nothing_to_do(tmp_path):
    module = _module()
    root = _device(tmp_path, "")
    (root / "boot/firmware/rosy-config.yaml").unlink()

    result, calls = _apply(module, root)

    assert result["state"] == "absent" and calls == []


def test_main_never_fails_the_boot(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "apply", lambda *_a: (_ for _ in ()).throw(RuntimeError("boom")))

    assert module.main(["--root", str(tmp_path)]) == 0


def test_the_card_file_is_never_read_into_diagnostics():
    sys.path.insert(0, str(NATIVE))
    spec = importlib.util.spec_from_file_location("rosy_diag_redact_cfg", NATIVE / "rosy_diag_redact.py")
    redact = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(redact)

    assert redact.is_denied_path("/boot/firmware/rosy-config.yaml")
    assert redact.is_denied_path("/etc/rosy/ap-credentials.json")
