"""Boot indicator outside CORE (D-174 T0): stage → status file, ACT LED, console, mDNS."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import xml.dom.minidom

import pytest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/native"
FAILED_CARD_UNITS = {
    "rosy-release-recover.service": "failed\n",
    "rosy-first-boot.service": "active\n",
    "rosy-sd-provision.service": "active\n",
    "rosy-core.service": "inactive\n",
    "rosy-runtime.target": "inactive\n",
}


def _module():
    sys.path.insert(0, str(NATIVE))
    spec = importlib.util.spec_from_file_location("rosy_boot_status", NATIVE / "rosy-boot-status.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _device(tmp_path: Path, *, led: bool = True) -> Path:
    root = tmp_path / "device"
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/device-identity.json").write_text(
        json.dumps({"device_name": "rosy-pinky-e4us", "hostname": "rosy-pinky-e4us"}), encoding="utf-8")
    (root / "var/lib/rosy/provisioning").mkdir(parents=True)
    (root / "var/lib/rosy/provisioning/state.json").write_text('{"state":"PROVISIONED"}', encoding="utf-8")
    (root / "proc/sys/kernel/random").mkdir(parents=True)
    (root / "proc/sys/kernel/random/boot_id").write_text("23fe37a5\n", encoding="utf-8")
    if led:
        (root / "sys/class/leds/ACT").mkdir(parents=True)
        for name in ("trigger", "delay_on", "delay_off"):
            (root / "sys/class/leds/ACT" / name).write_text("", encoding="ascii")
    return root


def _runner(units: dict[str, str], calls: list[list[str]]):
    def run(command):
        calls.append(command)
        if command[:2] == ["systemctl", "show"]:
            return units.get(command[-1], "")
        if command[:2] == ["hostname", "-I"]:
            return "192.168.1.201 fd23::764f\n"
        return ""
    return run


def _render(module, root, units):
    calls: list[list[str]] = []
    run = _runner(units, calls)
    facts = module.gather(root, run)
    stage = module.classify(facts["units"], facts["provisioning"])
    record = module.status_record(facts, stage, datetime(2026, 9, 23, tzinfo=timezone.utc))
    errors = module.apply(root, record, stage, run)
    return record, errors, calls


def test_the_first_card_failure_is_visible_on_every_sink(tmp_path):
    module = _module()
    root = _device(tmp_path)

    record, errors, calls = _render(module, root, FAILED_CARD_UNITS)

    assert errors == []
    assert record["stage"] == "FAILED:rosy-release-recover"
    assert record["ipv4"] == ["192.168.1.201"]
    status = json.loads((root / "run/rosy/boot-status.json").read_text(encoding="utf-8"))
    assert status["stage"] == "FAILED:rosy-release-recover"
    assert (root / "sys/class/leds/ACT/trigger").read_text(encoding="ascii") == "timer"
    issue = (root / "run/rosy/issue").read_text(encoding="utf-8")
    assert "rosy-pinky-e4us" in issue and "192.168.1.201" in issue
    assert "journalctl -b -u rosy-release-recover.service" in issue
    avahi = (root / "etc/avahi/services/rosy.service").read_text(encoding="utf-8")
    xml.dom.minidom.parseString(avahi)
    assert "<type>_rosy._tcp</type>" in avahi
    assert "stage=FAILED:rosy-release-recover" in avahi
    assert ["agetty", "--reload"] in calls


def test_ready_device_shows_a_heartbeat(tmp_path):
    module = _module()
    root = _device(tmp_path)
    ready = {unit: "active\n" for unit in FAILED_CARD_UNITS}

    record, errors, _calls = _render(module, root, ready)

    assert record["stage"] == "CORE_READY"
    assert (root / "sys/class/leds/ACT/trigger").read_text(encoding="ascii") == "heartbeat"


def test_one_broken_sink_never_stops_the_others(tmp_path):
    module = _module()
    root = _device(tmp_path)
    (root / "etc/avahi").mkdir(parents=True)
    (root / "etc/avahi/services").write_text("not a directory", encoding="utf-8")

    record, errors, _calls = _render(module, root, FAILED_CARD_UNITS)

    assert len(errors) == 1 and errors[0].startswith("avahi")
    assert (root / "run/rosy/boot-status.json").is_file()
    assert (root / "run/rosy/issue").is_file()


def test_missing_led_is_not_an_error(tmp_path):
    module = _module()
    root = _device(tmp_path, led=False)

    _record, errors, _calls = _render(module, root, FAILED_CARD_UNITS)

    assert errors == []


def test_untrusted_text_cannot_break_the_avahi_xml(tmp_path):
    module = _module()
    record = {"stage": "FAILED:x", "release_id": "<r&>", "device_name": "a\"b"}

    xml.dom.minidom.parseString(module.render_avahi(record))


def test_main_never_fails_the_boot(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "gather", lambda *_a: (_ for _ in ()).throw(RuntimeError("boom")))

    assert module.main(["--root", str(tmp_path)]) == 0


@pytest.mark.parametrize(
    "unit", ["rosy-release-recover.service", "rosy-first-boot.service",
             "rosy-sd-provision.service", "rosy-core.service"],
)
def test_boot_units_refresh_the_indicator_when_they_fail(unit):
    source = (ROOT / ("deploy/image/first-boot" if unit == "rosy-first-boot.service" else "deploy/robot/native")
              / unit).read_text(encoding="utf-8")

    assert "OnFailure=rosy-boot-status.service" in source


def test_indicator_units_are_outside_core_and_never_gate_the_runtime():
    service = (NATIVE / "rosy-boot-status.service").read_text(encoding="utf-8")
    timer = (NATIVE / "rosy-boot-status.timer").read_text(encoding="utf-8")
    target = (NATIVE / "rosy-runtime.target").read_text(encoding="utf-8")
    core = (NATIVE / "rosy-core.service").read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    assert "ExecStart=/usr/bin/python3 -B /opt/rosy/native-runtime/rosy-boot-status.py" in service
    assert "OnUnitActiveSec=" in timer and "OnBootSec=" in timer
    assert "rosy-boot-status" not in target
    assert "rosy-boot-status" not in core.replace("OnFailure=rosy-boot-status.service", "")


def test_image_installs_and_enables_the_indicator():
    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")
    customizer = (ROOT / "deploy/image/customize-rootfs.sh").read_text(encoding="utf-8")

    assert 'rosy-boot-status.service" "$OVERLAY/etc/systemd/system/' in payload
    assert 'rosy-boot-status.timer" "$OVERLAY/etc/systemd/system/' in payload
    assert "rosy-boot-status.timer" in customizer.split("systemctl --root")[1].split("\n\n")[0]
    assert "etc/issue.d/rosy.issue" in customizer
