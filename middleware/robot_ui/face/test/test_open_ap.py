"""Open recovery AP display compatibility, without device or network access."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from emotion import info_screen, wifi_qr


ROOT = Path(__file__).resolve().parents[4]
SSID = "rosy-pinky-e4us"
KEY = "rosy-" + "k7m4-p9xr"
NETWORK = {"mode": "ap", "ssid": SSID, "address": "10.42.0.1", "security": "open"}


def _native(name, monkeypatch):
    directory = ROOT / "deploy/robot/pinky_pro/native"
    monkeypatch.syspath_prepend(str(ROOT / "contracts/foundation"))
    monkeypatch.syspath_prepend(str(directory))
    module_name = "open_ap_" + name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, directory / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def _state(root):
    directory = root / "run/rosy-boot"
    directory.mkdir(parents=True)
    (directory / "network.json").write_text(json.dumps(NETWORK), encoding="utf-8")
    return directory


def _deny_read(monkeypatch, forbidden):
    read_text = Path.read_text

    def checked(path, *args, **kwargs):
        assert path != forbidden, "open AP must not read its unused key"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", checked)


def test_open_join_payload_escapes_ssid_and_omits_even_a_stale_key():
    payload = wifi_qr.wifi_payload("robot;open", KEY, security="open")
    assert payload == "WIFI" + ":T:nopass;S:robot\\;open;;"
    assert KEY not in payload and ";P:" not in payload


@pytest.mark.parametrize("security", [None, "unknown", {}, []])
def test_malformed_security_does_not_draw_a_join_code(security):
    payload = {"network": {**NETWORK, "security": security}, "ap_login": KEY}
    assert info_screen.ap_qr(payload) is None


@pytest.mark.parametrize("login", [None, KEY])
def test_open_ap_card_shows_no_password_and_a_passwordless_qr(login):
    payload = {"stage": "CORE_READY", "network": NETWORK, "ap_login": login}
    rows = {name: text for name, text, _colour in info_screen.boot_lines(payload)}
    assert rows["ap_login"] == "No password"
    expected = wifi_qr.encode("WIFI" + f":T:nopass;S:{SSID};;")
    assert info_screen.ap_qr(payload) == expected


@pytest.mark.parametrize("security", [None, "wpa2"])
def test_protected_and_legacy_ap_still_need_the_key(security):
    network = {key: value for key, value in NETWORK.items() if key != "security"}
    if security is not None:
        network["security"] = security
    payload = {"stage": "CORE_READY", "network": network}
    assert info_screen.ap_qr(payload) is None
    rows = {name: text for name, text, _colour in info_screen.boot_lines(payload)}
    assert rows["ap_login"] == "PW: see the operator AP store"
    payload["ap_login"] = KEY
    assert info_screen.ap_qr(payload) == wifi_qr.encode(wifi_qr.wifi_payload(SSID, KEY))


def test_native_face_retains_open_security_without_reading_a_stale_key(tmp_path, monkeypatch):
    module = _native("rosy-face", monkeypatch)
    directory = _state(tmp_path)
    handoff = directory / "ap-display.txt"
    handoff.write_text(f"{SSID}\n{KEY}\n", encoding="utf-8")
    _deny_read(monkeypatch, handoff)
    view = module.read_view(tmp_path, None)
    assert view["network"]["security"] == "open"
    assert "ap_login" not in view


def test_boot_status_retains_security_and_console_ignores_a_stale_key(tmp_path, monkeypatch):
    module = _native("rosy-boot-status", monkeypatch)
    _state(tmp_path)
    facts = module.gather(tmp_path, lambda _command: "")
    assert facts["network"]["security"] == "open"
    issue = module.render_issue({"stage": "BOOTING", "network": NETWORK}, KEY)
    assert "No password" in issue and KEY not in issue


def test_boot_console_does_not_read_the_unused_ap_credential_store(tmp_path, monkeypatch):
    module = _native("rosy-boot-status", monkeypatch)
    store = tmp_path / "etc/rosy/ap-credentials.json"
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({"ssid": SSID, "pass" + "word": KEY}), encoding="utf-8")
    _deny_read(monkeypatch, store)
    record = {"stage": "BOOTING", "network": NETWORK}
    errors = module.apply(tmp_path, record, module.Stage("BOOTING"), lambda _command: "")
    assert errors == []
    issue = (tmp_path / "run/rosy-boot/issue").read_text(encoding="utf-8")
    assert "No password" in issue and KEY not in issue
