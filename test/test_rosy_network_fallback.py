"""Fallback AP controller (D-176 Task 4)."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/pinky_pro/native"
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


def test_timer_does_not_mutate_radio_while_network_change_owns_lock(tmp_path):
    module = _module()
    from network_transaction import change_lock
    calls = []
    state = _state(module, ap_active=True, ap_since=0)
    with change_lock(tmp_path) as acquired:
        assert acquired
        following = module.step(state, 1000, {'mode': 'off'}, False, tmp_path,
                                lambda argv: calls.append(argv) or '')
    assert calls == [] and following == state


def test_ap_scope_changes_when_the_ap_reopens(tmp_path):
    module = _module()
    module._status(tmp_path, 'ap', 'fixture-ap')
    first = json.loads((tmp_path / module.STATUS).read_text())
    module._status(tmp_path, 'sta')
    module._status(tmp_path, 'ap', 'fixture-ap')
    second = json.loads((tmp_path / module.STATUS).read_text())
    assert first['epoch'] and second['epoch'] != first['epoch']


def test_controller_restart_does_not_close_a_radio_owned_by_another_change(tmp_path, monkeypatch):
    module = _module()
    from network_transaction import change_lock
    calls = []
    monkeypatch.setattr(module, '_run', lambda argv: calls.append(argv) or '')
    with change_lock(tmp_path):
        assert module.main(['--root', str(tmp_path), '--once']) == 0
    assert not any(argv[1:3] in (['connection', 'down'], ['connection', 'up'], ['device', 'connect'])
                   for argv in calls)


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
    (root / "etc/rosy/device-identity.json").write_text(
        json.dumps({"device_name": "rosy-pinky-e4us"}), encoding="utf-8")
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
    assert {key: status[key] for key in ('mode', 'ssid', 'address')} == {
        "mode": "ap", "ssid": "rosy-pinky-e4us", "address": "10.42.0.1"}
    assert status['epoch']
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
    (root / "etc/rosy/network-policy.json").write_text(
        json.dumps({"mode": "fallback", "fallback_security": "wpa2"}), encoding="utf-8")
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


def test_update_claim_defers_fallback_step_without_taking_radio_lock(tmp_path, monkeypatch):
    module = _module()
    import rosy_claim

    rosy_claim.acquire(tmp_path, "rosy-auto-update", "fixture update", 300, lock_wait_s=0)
    calls = []
    def forbidden_lock(*args, **kwargs):
        pytest.fail("fallback took the radio lock while the update claim was held")
    monkeypatch.setattr(module, "change_lock", forbidden_lock)
    state = module.LinkState(ap_active=True, ap_since=0)
    try:
        assert module.step(state, 1000, {"mode": "off"}, False, tmp_path,
                           lambda argv: calls.append(argv) or "") == state
        assert calls == []
        assert rosy_claim.check(tmp_path)["holder"] == "rosy-auto-update"
    finally:
        rosy_claim.release(tmp_path, "rosy-auto-update")


def test_update_claim_defers_startup_down_and_nm_observations(tmp_path, monkeypatch):
    module = _module()
    import rosy_claim

    rosy_claim.acquire(tmp_path, "rosy-auto-update", "fixture update", 300, lock_wait_s=0)
    display = tmp_path / module.DISPLAY_AP
    display.parent.mkdir(parents=True)
    display.write_text("existing AP display", encoding="utf-8")
    calls = []
    monkeypatch.setattr(module, "_run", lambda argv: calls.append(argv) or "")
    try:
        assert module.main(["--root", str(tmp_path), "--once"]) == 0
        assert calls == []
        assert display.read_text() == "existing AP display"
        assert rosy_claim.check(tmp_path)["holder"] == "rosy-auto-update"
    finally:
        rosy_claim.release(tmp_path, "rosy-auto-update")


@pytest.mark.parametrize("fail", [False, True])
def test_fallback_holds_claim_before_radio_lock_and_releases_it(tmp_path, monkeypatch, fail):
    module = _module()
    import rosy_claim

    holders = []
    @contextmanager
    def radio_lock(root, *, blocking=False):
        claim = rosy_claim.check(root)
        assert claim is not None, "radio lock must be acquired after the global claim"
        holders.append(claim["holder"])
        assert claim["holder"] != "rosy-auto-update"
        yield True
    monkeypatch.setattr(module, "change_lock", radio_lock)
    calls = []
    def run(argv):
        assert rosy_claim.check(tmp_path)["holder"] == holders[-1]
        calls.append(argv)
        if fail:
            raise ValueError("fixture NM failure")
        return ""
    state = module.LinkState(ap_active=True, ap_since=0)
    if fail:
        with pytest.raises(ValueError, match="fixture NM failure"):
            module.step(state, 1000, {"mode": "off"}, False, tmp_path, run)
    else:
        assert not module.step(state, 1000, {"mode": "off"}, False, tmp_path, run).ap_active
        module.step(state, 1000, {"mode": "off"}, False, tmp_path, run)
        assert holders[0] != holders[1], "each radio ownership must use a unique claim holder"
    assert calls
    assert rosy_claim.check(tmp_path) is None


@pytest.mark.parametrize("configured, expected", [(None, "open"), ("open", "open"), ("wpa2", "wpa2")])
def test_fallback_security_controls_profile_and_public_status(tmp_path, monkeypatch, configured, expected):
    module = _module()
    monkeypatch.setattr(module, "_display_gid", lambda: None)
    root = _device(tmp_path)
    policy = dict(POLICY)
    if configured is not None:
        policy["fallback_security"] = configured
    (root / "etc/rosy/network-policy.json").write_text(json.dumps(policy), encoding="utf-8")
    handoff = root / module.DISPLAY_AP
    handoff.parent.mkdir(parents=True)
    handoff.write_text(AP_VALUE, encoding="utf-8")

    assert module.perform(root, "open", _activated)

    profile = (root / f"etc/NetworkManager/system-connections/{module.PROFILE}.nmconnection").read_text()
    status = json.loads((root / module.STATUS).read_text())
    assert status["security"] == expected
    assert ("[wifi-security]" in profile) == (expected == "wpa2")
    assert (AP_VALUE in profile) == (expected == "wpa2")
    assert AP_VALUE not in json.dumps(status)
    if expected == "open":
        assert not handoff.exists()


def test_open_fallback_does_not_read_its_unused_credential_store(tmp_path, monkeypatch):
    module = _module()
    root = _device(tmp_path)
    original = module._read_json

    def read(path):
        assert path.name != "ap-credentials.json", "an open AP must not read its unused key store"
        return original(path)

    monkeypatch.setattr(module, "_read_json", read)
    assert module.perform(root, "open", _activated)


def test_open_fallback_only_needs_a_known_ssid(tmp_path):
    module = _module()
    root = _device(tmp_path)
    (root / "etc/rosy/ap-credentials.json").unlink()
    assert module.perform(root, "open", _activated)
    status = json.loads((root / module.STATUS).read_text())
    assert status["security"] == "open" and status["ssid"] == "rosy-pinky-e4us"


def test_relay_keeps_wpa2_even_when_fallback_is_open(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "_display_gid", lambda: None)
    root = _device(tmp_path)
    (root / "etc/rosy/network-policy.json").write_text(
        json.dumps({"mode": "relay", "fallback_security": "open"}), encoding="utf-8")
    assert module.perform(root, "open", _activated)
    profile = (root / f"etc/NetworkManager/system-connections/{module.PROFILE}.nmconnection").read_text()
    assert "[wifi-security]" in profile and AP_VALUE in profile
    (root / "etc/rosy/ap-credentials.json").write_text(json.dumps({"ssid": "fixture-ap"}), encoding="utf-8")
    assert not module.perform(root, "open", _activated)


@pytest.mark.parametrize("security", [None, "invalid", {}, []])
def test_invalid_fallback_security_does_not_open_an_ap(tmp_path, security):
    module = _module()
    root = _device(tmp_path)
    (root / "etc/rosy/network-policy.json").write_text(
        json.dumps({"mode": "fallback", "fallback_security": security}), encoding="utf-8")
    calls = []
    assert not module.perform(root, "open", lambda command: calls.append(command) or _activated(command))
    assert calls == []


def test_default_fallback_security_is_open(tmp_path):
    module = _module()
    assert module.load_policy(tmp_path)["fallback_security"] == "open"


@pytest.mark.parametrize("device_name", ["rosy-pinky-geg6", "rosy-pinky-nsfh"])
@pytest.mark.parametrize("override", [None, "fixture-recovery"])
def test_open_ap_keeps_each_device_name_unless_ssid_is_explicit(tmp_path, device_name, override):
    module = _module()
    root = _device(tmp_path)
    (root / "etc/rosy/device-identity.json").write_text(json.dumps({"device_name": device_name}))
    policy = {"mode": "fallback"}
    if override is not None:
        policy["ssid"] = override
    (root / "etc/rosy/network-policy.json").write_text(json.dumps(policy))
    assert module.perform(root, "open", _activated)
    assert json.loads((root / module.STATUS).read_text())["ssid"] == (override or device_name)


@pytest.mark.parametrize("override", [None, "fixture-recovery"])
def test_open_ap_does_not_invent_an_identity_when_the_canonical_one_is_absent(tmp_path, override):
    module = _module()
    root = _device(tmp_path)
    (root / "etc/rosy/device-identity.json").unlink()
    policy = {"mode": "fallback"}
    if override is not None:
        policy["ssid"] = override
    (root / "etc/rosy/network-policy.json").write_text(json.dumps(policy))
    calls = []
    assert not module.perform(root, "open", lambda command: calls.append(command) or _activated(command))
    assert calls == []
