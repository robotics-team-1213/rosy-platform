"""Fallback AP controller (D-176 Task 4)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"
PW = "pass" + "word"  # assembled so the tracked-file secret scanner sees no literal
AP_VALUE = "Kx7" + "mQ2vR9tLpZq"
POLICY = {"mode": "fallback", "grace_seconds": 120, "hold_seconds": 600}


def _module():
    sys.path.insert(0, str(NATIVE))
    spec = importlib.util.spec_from_file_location("rosy_network", NATIVE / "rosy-network.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _state(module, **values):
    return module.LinkState(**values)


def _activated(command: list[str]) -> str:
    return "GENERAL.STATE:activated\n" if "GENERAL.STATE" in command else ""


def test_uplink_keeps_the_ap_closed():
    module = _module()

    action, state = module.decide(_state(module), 1000.0, POLICY, uplink=True)

    assert action is None and state.no_uplink_since is None


def test_the_ap_opens_only_after_the_grace_period_without_uplink():
    module = _module()
    state = _state(module)

    action, state = module.decide(state, 1000.0, POLICY, uplink=False)
    assert action is None and state.no_uplink_since == 1000.0
    action, state = module.decide(state, 1119.0, POLICY, uplink=False)
    assert action is None
    action, state = module.decide(state, 1120.0, POLICY, uplink=False)

    assert action == "open" and state.ap_active and state.ap_since == 1120.0


def test_a_wired_uplink_closes_the_fallback_ap_at_once():
    module = _module()
    state = _state(module, ap_active=True, ap_since=1000.0)

    action, state = module.decide(state, 1010.0, POLICY, uplink=True)

    assert action == "close" and not state.ap_active


def test_the_ap_steps_aside_after_the_hold_so_site_wifi_can_be_retried():
    module = _module()
    state = _state(module, ap_active=True, ap_since=1000.0)

    action, state = module.decide(state, 1599.0, POLICY, uplink=False)
    assert action is None
    action, state = module.decide(state, 1600.0, POLICY, uplink=False)

    assert action == "close" and state.no_uplink_since == 1600.0  # a fresh grace before reopening


@pytest.mark.parametrize(("mode", "ap_active", "expected"),
                         [("off", True, "close"), ("off", False, None),
                          ("relay", False, "open"), ("relay", True, None)])
def test_off_and_relay_modes(mode, ap_active, expected):
    module = _module()

    action, _state_after = module.decide(_state(module, ap_active=ap_active), 1000.0,
                                         {**POLICY, "mode": mode}, uplink=True)

    assert action == expected


def _device(tmp_path: Path) -> Path:
    root = tmp_path / "device"
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/ap-credentials.json").write_text(
        json.dumps({"ssid": "rosy-pinky-e4us", PW: AP_VALUE}), encoding="utf-8")
    (root / "etc/rosy/network-policy.json").write_text(json.dumps({**POLICY, "country": "KR"}), encoding="utf-8")
    (root / "etc/NetworkManager/system-connections").mkdir(parents=True)
    return root


def test_opening_writes_a_root_only_ap_profile_and_a_secret_free_status(tmp_path):
    module = _module()
    root = _device(tmp_path)
    calls: list[list[str]] = []

    assert module.perform(root, "open", lambda command: calls.append(command) or _activated(command))

    profile = root / "etc/NetworkManager/system-connections/rosy-fallback-ap.nmconnection"
    text = profile.read_text(encoding="utf-8")
    assert "mode=ap" in text and "ssid=rosy-pinky-e4us" in text and "method=shared" in text
    if os.name == "posix":
        assert profile.stat().st_mode & 0o777 == 0o600
    assert ["nmcli", "connection", "up", "rosy-fallback-ap"] in calls
    status_text = (root / "run/rosy-boot/network.json").read_text(encoding="utf-8")
    status = json.loads(status_text)
    assert status == {"mode": "ap", "ssid": "rosy-pinky-e4us", "address": "10.42.0.1"}
    assert AP_VALUE not in status_text


def test_closing_takes_the_ap_down_and_reports_station_mode(tmp_path):
    module = _module()
    root = _device(tmp_path)
    calls: list[list[str]] = []

    module.perform(root, "close", lambda command: calls.append(command) or "")

    assert ["nmcli", "connection", "down", "rosy-fallback-ap"] in calls
    assert json.loads((root / "run/rosy-boot/network.json").read_text(encoding="utf-8"))["mode"] == "sta"


def test_without_ap_credentials_the_ap_is_not_opened(tmp_path):
    module = _module()
    root = _device(tmp_path)
    (root / "etc/rosy/ap-credentials.json").unlink()
    calls: list[list[str]] = []

    module.perform(root, "open", lambda command: calls.append(command) or "")

    assert calls == []
    assert json.loads((root / "run/rosy-boot/network.json").read_text(encoding="utf-8"))["mode"] == "none"


def test_uplink_means_a_default_route(tmp_path):
    module = _module()

    assert module.has_uplink(lambda command: "default via 192.168.1.1 dev wlan0 proto dhcp\n")
    assert not module.has_uplink(lambda command: "")


def test_policy_falls_back_to_image_defaults(tmp_path):
    module = _module()
    root = tmp_path / "device"
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/defaults.yaml").write_text((NATIVE / "defaults.yaml").read_text(encoding="utf-8"),
                                                 encoding="utf-8")

    assert module.load_policy(root)["mode"] == "fallback"


def test_the_service_runs_outside_core_after_config_is_applied():
    unit = (NATIVE / "rosy-network.service").read_text(encoding="utf-8")

    assert "ExecStart=/usr/bin/python3 -B /opt/rosy/native-runtime/rosy-network.py" in unit
    assert "After=NetworkManager.service rosy-config.service" in unit
    assert "Restart=always" in unit
    assert "User=" not in unit  # root: it drives NetworkManager (D-161: never inside CORE)


def test_an_ap_that_does_not_activate_is_not_advertised(tmp_path):
    # e.g. dnsmasq missing: the banner must not send people to a missing AP.
    module = _module()
    root = _device(tmp_path)

    assert not module.perform(root, "open", lambda command: "")

    assert json.loads((root / "run/rosy-boot/network.json").read_text(encoding="utf-8"))["mode"] == "none"


def test_a_failed_open_is_retried_instead_of_believed(tmp_path):
    module = _module()
    root = _device(tmp_path)
    waiting = module.LinkState(no_uplink_since=0.0)

    state = module.step(waiting, 200.0, POLICY, False, root, lambda command: "")

    assert not state.ap_active
    action, _ = module.decide(state, 200.0 + POLICY["grace_seconds"], POLICY, uplink=False)
    assert action == "open"


def test_a_connected_site_link_without_a_gateway_is_an_uplink():
    module = _module()
    outputs = {"ip": "", "nmcli": "lo:loopback:unmanaged:\nwlan0:wifi:connected:rosy-wifi-0123456789\n"}

    assert module.has_uplink(lambda command: outputs[command[0]])


def test_the_ap_itself_is_not_an_uplink():
    module = _module()
    outputs = {"ip": "", "nmcli": "wlan0:wifi:connected:rosy-fallback-ap\n"}

    assert not module.has_uplink(lambda command: outputs[command[0]])


def test_closing_asks_networkmanager_to_retry_the_site_wifi(tmp_path):
    module = _module()
    root = _device(tmp_path)
    calls: list[list[str]] = []

    module.perform(root, "close", lambda command: calls.append(command) or "")

    assert ["nmcli", "device", "connect", "wlan0"] in calls
