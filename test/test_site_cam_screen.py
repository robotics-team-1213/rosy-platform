import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/site/rosy_cam_screen.py"


def load():
    spec = importlib.util.spec_from_file_location("cam_screen", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Commands:
    def __init__(self, devices, identities, mdns="", avahi="", connected=None):
        self.devices = devices
        self.identities = identities
        self.mdns = mdns
        self.avahi = avahi
        self.connected = connected
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        assert kwargs["timeout"] == 10
        assert "shell" not in kwargs
        if args[0] == "avahi-browse":
            out = self.avahi
        elif args[1:] == ["devices"]:
            out = "List of devices attached\n" + self.devices
        elif args[1:] == ["mdns", "services"]:
            out = self.mdns
        elif args[1] == "connect":
            if self.connected is not None:
                self.devices = self.connected
            out = "connected"
        elif args[3:5] == ["shell", "getprop"]:
            out = self.identities[args[2]][args[5]]
        elif args[3:] == ["shell", "dumpsys", "power"]:
            out = "mWakefulness=Dozing\n"
        elif args[3:] == ["shell", "input", "keyevent", "KEYCODE_WAKEUP"]:
            out = ""
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, out, "")


CONFIG = {"adb_path": "/opt/platform-tools/adb", "expected_serial": "PHONE123", "expected_model": "SM-G991N"}


def identity(serial="PHONE123", model="SM-G991N"):
    return {"ro.serialno": serial, "ro.product.model": model}


def test_wake_targets_verified_phone_only():
    module = load()
    runner = Commands("phone:34567\tdevice\nother:34568\tdevice\n", {
        "phone:34567": identity(), "other:34568": identity("OTHER", "Tablet")})
    result = module.execute(CONFIG, "wake", runner)
    assert result["status"] == "wake_sent"
    assert runner.calls[-1] == [CONFIG["adb_path"], "-s", "phone:34567", "shell", "input", "keyevent", "KEYCODE_WAKEUP"]


@pytest.mark.parametrize("rows,identities", [
    ("phone\tdevice\n", {"phone": identity(model="Wrong")}),
    ("one\tdevice\ntwo\tdevice\n", {"one": identity(), "two": identity()}),
    ("phone\tunauthorized\n", {}),
])
def test_untrusted_or_ambiguous_never_wakes(rows, identities):
    module = load()
    runner = Commands(rows, identities)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", runner)
    assert not any("keyevent" in call for call in runner.calls)


@pytest.mark.parametrize("discovery", ["adb", "avahi"])
def test_dynamic_port_reconnect_then_verify(discovery):
    module = load()
    runner = Commands("", {"192.0.2.10:45678": identity()},
        mdns="adb-PHONE123-guid _adb-tls-connect._tcp 192.0.2.10:45678\n" if discovery == "adb" else "",
        avahi="=;eth0;IPv4;adb-PHONE123-guid;_adb-tls-connect._tcp;local;phone.local;192.0.2.10;45678;\n" if discovery == "avahi" else "",
        connected="192.0.2.10:45678\tdevice\n")
    result = module.execute(CONFIG, "status", runner)
    assert result == {"status": "connected", "model": "SM-G991N", "screen": "Dozing"}
    assert [CONFIG["adb_path"], "connect", "192.0.2.10:45678"] in runner.calls
    assert not any("keyevent" in call for call in runner.calls)


def test_advertisement_does_not_replace_actual_identity():
    module = load()
    runner = Commands("", {"192.0.2.10:45678": identity("IMPOSTOR")},
        mdns="adb-PHONE123-guid _adb-tls-connect._tcp 192.0.2.10:45678\n",
        connected="192.0.2.10:45678\tdevice\n")
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", runner)
    assert not any("keyevent" in call for call in runner.calls)


def test_unknown_advertisement_not_connected():
    module = load()
    runner = Commands("", {}, mdns="adb-PHONE123OTHER-guid _adb-tls-connect._tcp 192.0.2.10:45678\n")
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", runner)
    assert not any("connect" in call for call in runner.calls)


def test_timeout_never_wakes():
    module = load()
    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 10)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", timeout)


def test_duplicate_dynamic_connections_refused():
    module = load()
    runner = Commands("", {"192.0.2.10:45678": identity(), "192.0.2.10:45679": identity()},
        mdns="adb-PHONE123-one _adb-tls-connect._tcp 192.0.2.10:45678\nadb-PHONE123-two _adb-tls-connect._tcp 192.0.2.10:45679\n",
        connected="192.0.2.10:45678\tdevice\n192.0.2.10:45679\tdevice\n")
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", runner)
    assert not any("keyevent" in call for call in runner.calls)


@pytest.mark.parametrize("failed_step", ["connect", "getprop"])
def test_stale_port_then_live_duplicate_service(failed_step):
    module = load()
    runner = Commands("", {"192.0.2.10:42029": identity()},
        avahi="=;eth0;IPv4;adb-PHONE123-guid;_adb-tls-connect._tcp;local;phone.local;192.0.2.10;34747;\n"
              r"=;eth0;IPv4;adb-PHONE123-guid\032\0402\041;_adb-tls-connect._tcp;local;phone.local;192.0.2.10;42029;" + "\n",
        connected="192.0.2.10:42029\tdevice\n")
    def stale(args, **kwargs):
        if (args[1:] == ["connect", "192.0.2.10:34747"] or
                (len(args) > 2 and args[2] == "192.0.2.10:34747")):
            runner.calls.append(args)
            if failed_step == "getprop" and args[1] == "connect":
                return subprocess.CompletedProcess(args, 0, "connected", "")
            return subprocess.CompletedProcess(args, 1, "", "private failure")
        return runner(args, **kwargs)
    result = module.execute(CONFIG, "wake", stale)
    assert result["status"] == "wake_sent"
    assert runner.calls[-1][2] == "192.0.2.10:42029"


def test_stop_after_first_unique_verified_connection():
    module = load()
    runner = Commands("", {"192.0.2.10:34747": identity()},
        mdns="adb-PHONE123-one _adb-tls-connect._tcp 192.0.2.10:34747\nadb-PHONE123-two _adb-tls-connect._tcp 192.0.2.10:42029\n",
        connected="192.0.2.10:34747\tdevice\n")
    assert module.execute(CONFIG, "wake", runner)["status"] == "wake_sent"
    assert [CONFIG["adb_path"], "connect", "192.0.2.10:42029"] not in runner.calls


def test_public_example_can_be_loaded_without_real_identity():
    module = load()
    config = json.loads(SCRIPT.with_name("cam-screen.json.example").read_text())
    assert module.validate(config) == config
    assert config["expected_serial"] == "YOURPHONESERIAL"
