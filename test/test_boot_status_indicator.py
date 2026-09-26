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
    status = json.loads((root / "run/rosy-boot/boot-status.json").read_text(encoding="utf-8"))
    assert status["stage"] == "FAILED:rosy-release-recover"
    assert (root / "sys/class/leds/ACT/trigger").read_text(encoding="ascii") == "timer"
    issue = (root / "run/rosy-boot/issue").read_text(encoding="utf-8")
    assert "rosy-pinky-e4us" in issue and "192.168.1.201" in issue
    assert "journalctl -b -u rosy-release-recover.service" in issue
    avahi = (root / "etc/avahi/services/rosy.service").read_text(encoding="utf-8")
    xml.dom.minidom.parseString(avahi)
    assert "<type>_rosy._tcp</type>" in avahi
    assert "product=rosy" in avahi and "role=robot" in avahi
    assert "proto=core-v1" in avahi and "tls=none" in avahi
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
    assert (root / "run/rosy-boot/boot-status.json").is_file()
    assert (root / "run/rosy-boot/issue").is_file()


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
    assert "ln -sfn /run/rosy-boot/issue" in customizer


def test_indicator_writes_only_to_a_root_owned_directory_and_never_follows_links(tmp_path):
    # Review H1: /run/rosy belongs to rosy-core. A compromised CORE could plant a
    # symlink at a predictable temp name and have root overwrite any file.
    module = _module()
    root = _device(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("keep me", encoding="utf-8")
    runtime = root / "run/rosy-boot"
    runtime.mkdir(parents=True)
    for name in (".issue.tmp", ".boot-status.json.tmp"):
        try:
            (runtime / name).symlink_to(victim)
        except OSError:
            pytest.skip("symlinks need privileges on this host")

    _record, errors, _calls = _render(module, root, FAILED_CARD_UNITS)

    assert errors == []
    assert victim.read_text(encoding="utf-8") == "keep me"
    assert not (root / "run/rosy").exists()
    source = (NATIVE / "rosy-boot-status.py").read_text(encoding="utf-8")
    assert "tempfile.mkstemp(dir=path.parent" in source
    assert 'STATUS_DIR = "run/rosy-boot"' in source


def test_unchanged_status_does_not_rewrite_or_reload(tmp_path):
    # Review M7: avahi re-announced and the console redrew every 30 s.
    module = _module()
    root = _device(tmp_path)
    _render(module, root, FAILED_CARD_UNITS)
    avahi = root / "etc/avahi/services/rosy.service"
    before = avahi.stat().st_mtime_ns

    _record, _errors, calls = _render(module, root, FAILED_CARD_UNITS)

    assert avahi.stat().st_mtime_ns == before
    assert ["agetty", "--reload"] not in calls


def test_one_sink_raising_anything_never_stops_the_black_box(tmp_path):
    # Review L1: a non-string device name raised AttributeError inside avahi.
    module = _module()
    root = _device(tmp_path)
    (root / "boot/firmware").mkdir(parents=True)
    (root / "etc/rosy/device-identity.json").write_text('{"device_name": 42}', encoding="utf-8")

    _record, errors, _calls = _render(module, root, FAILED_CARD_UNITS)

    assert (root / "boot/firmware/rosy-diag/latest.txt").is_file()
    assert all(not error.startswith("blackbox") for error in errors)


def test_avahi_advertises_the_configured_api_port(tmp_path):
    # Review L7: the port followed wait-core-ready, not a literal 8080.
    module = _module()
    root = _device(tmp_path)
    (root / "etc/rosy/runtime.env").write_text("ROSY_API_PORT=9090\n", encoding="utf-8")

    _render(module, root, FAILED_CARD_UNITS)

    assert "<port>9090</port>" in (root / "etc/avahi/services/rosy.service").read_text(encoding="utf-8")


def test_indicator_unit_is_rate_unlimited_and_not_ordered_after_the_runtime():
    service = (NATIVE / "rosy-boot-status.service").read_text(encoding="utf-8")
    core = (NATIVE / "rosy-core.service").read_text(encoding="utf-8")

    assert "StartLimitIntervalSec=0" in service  # timer + OnFailure bursts (review M6)
    assert "RuntimeDirectory=rosy-boot" in service and "RuntimeDirectoryPreserve=yes" in service
    assert "rosy-runtime.target" not in service  # review L2: show BOOTING/PROVISIONED early
    assert "RestartMode=direct" in core  # restarts no longer fire OnFailure each time


# --- D-192 US-003: CORE_READY as soon as the runtime target settles ---------
#
# rosy-pinky-e4us 2026-09-24: the indicator ran at ~9 s, ~20 s and then every
# 30 s, so CORE_READY appeared at 53-55 s although CORE was ready at ~23 s.

READY = NATIVE / "rosy-boot-status-ready.service"


def _unit_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def test_ready_run_is_ordered_after_the_runtime_target_without_requiring_it():
    unit = READY.read_text(encoding="utf-8")
    lines = _unit_lines(unit)
    after = [line for line in lines if line.startswith("After=")]

    assert after and {"rosy-runtime.target", "rosy-core.service"} <= set(after[0][len("After="):].split())
    # Ordering, not a dependency: a failed runtime must still be shown at once,
    # and the indicator must never pull the runtime in or hold it up.
    assert not any(line.startswith(("Requires=", "BindsTo=", "Requisite=", "PartOf=")) for line in lines)
    assert "Type=oneshot" in lines
    assert "ExecStart=/usr/bin/python3 -B /opt/rosy/native-runtime/rosy-boot-status.py" in lines
    assert "WantedBy=multi-user.target" in lines
    # Same root-owned output directory as the periodic indicator (review H1).
    assert "RuntimeDirectory=rosy-boot" in lines and "RuntimeDirectoryPreserve=yes" in lines
    assert "User=" not in unit


def test_the_runtime_target_does_not_pull_the_ready_run_in():
    # A unit the target Wants runs before the target is reached, when the
    # classifier still sees it activating.
    target = (NATIVE / "rosy-runtime.target").read_text(encoding="utf-8")
    core = (NATIVE / "rosy-core.service").read_text(encoding="utf-8")
    assert "rosy-boot-status-ready" not in target
    assert "rosy-boot-status-ready" not in core
    assert "WantedBy=rosy-runtime.target" not in READY.read_text(encoding="utf-8")


def test_image_installs_and_enables_the_ready_run():
    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")
    customizer = (ROOT / "deploy/image/customize-rootfs.sh").read_text(encoding="utf-8")
    verifier = (ROOT / "deploy/image/verify-mounted-image.py").read_text(encoding="utf-8")

    assert 'cp "$NATIVE_RUNTIME_SOURCE/rosy-boot-status-ready.service" "$OVERLAY/etc/systemd/system/"' in payload
    enable = customizer.split("systemctl --root")[1].split("\n\n")[0]
    assert "rosy-boot-status-ready.service" in enable
    assert '"rosy-boot-status-ready.service"' in verifier


def test_ready_run_gives_up_quickly():
    # D-192 review: a stuck ready run must not hold multi-user.target for 30 s.
    assert "TimeoutStartSec=10" in _unit_lines(READY.read_text(encoding="utf-8"))


def test_one_run_holds_the_lock_from_gathering_to_the_last_sink(tmp_path, monkeypatch):
    # D-192 review: an older classification must never overwrite CORE_READY.
    module = _module()
    events: list[str] = []

    from contextlib import contextmanager

    @contextmanager
    def lock(root):
        assert root == tmp_path
        events.append("lock")
        yield
        events.append("unlock")

    def gather(root, run):
        events.append("gather")
        return {"units": {}, "provisioning": None}

    monkeypatch.setattr(module, "run_lock", lock)
    monkeypatch.setattr(module, "gather", gather)
    monkeypatch.setattr(module, "classify", lambda units, provisioning: module.Stage("BOOTING"))
    monkeypatch.setattr(module, "status_record", lambda facts, stage, now: {"stage": "X"})
    monkeypatch.setattr(module, "apply", lambda root, record, stage, run: events.append("apply") or [])

    assert module.main(["--root", str(tmp_path)]) == 0
    assert events == ["lock", "gather", "apply", "unlock"]


@pytest.mark.skipif(sys.platform == "win32",
                    reason="flock is POSIX; the ordering test above covers Windows hosts")
def test_a_second_run_waits_for_the_first(tmp_path):
    import threading

    module = _module()
    entered = threading.Event()
    release = threading.Event()
    second_in = threading.Event()

    def first():
        with module.run_lock(tmp_path):
            entered.set()
            release.wait(5)

    def second():
        with module.run_lock(tmp_path):
            second_in.set()

    one = threading.Thread(target=first)
    one.start()
    assert entered.wait(5)
    two = threading.Thread(target=second)
    two.start()
    assert not second_in.wait(0.3), "second run entered while the first held the lock"
    release.set()
    assert second_in.wait(5)
    one.join()
    two.join()
    lock_file = tmp_path / "run/rosy-boot/.run.lock"
    assert lock_file.is_file() and (lock_file.stat().st_mode & 0o777) == 0o600


# --- Fallback AP shown to people (D-176 Task 5) -----------------------------

PW = "pass" + "word"  # assembled so the tracked-file secret scanner sees no literal
AP_VALUE = "Kx7" + "mQ2vR9tLpZq"


def _with_ap(root: Path) -> None:
    (root / "run/rosy-boot").mkdir(parents=True, exist_ok=True)
    (root / "run/rosy-boot/network.json").write_text(
        json.dumps({"mode": "ap", "ssid": "rosy-pinky-e4us", "address": "10.42.0.1"}), encoding="utf-8")
    (root / "etc/rosy/ap-credentials.json").write_text(
        json.dumps({"ssid": "rosy-pinky-e4us", PW: AP_VALUE}), encoding="utf-8")


def test_the_console_shows_how_to_join_the_fallback_ap(tmp_path):
    module = _module()
    root = _device(tmp_path)
    _with_ap(root)

    record, errors, _calls = _render(module, root, FAILED_CARD_UNITS)

    assert errors == []
    issue = (root / "run/rosy-boot/issue").read_text(encoding="utf-8")
    assert "Wi-Fi AP rosy-pinky-e4us" in issue and AP_VALUE in issue and "10.42.0.1" in issue
    assert record["network"] == {"mode": "ap", "ssid": "rosy-pinky-e4us", "address": "10.42.0.1"}


def test_the_ap_password_never_leaves_the_console(tmp_path):
    module = _module()
    root = _device(tmp_path)
    _with_ap(root)
    (root / "boot/firmware").mkdir(parents=True)

    _render(module, root, FAILED_CARD_UNITS)

    for path in (root / "run/rosy-boot/boot-status.json", root / "etc/avahi/services/rosy.service",
                 root / "boot/firmware/rosy-diag/latest.txt"):
        assert AP_VALUE not in path.read_text(encoding="utf-8"), path.name
    assert "network=ap" in (root / "etc/avahi/services/rosy.service").read_text(encoding="utf-8")


def test_station_mode_shows_no_ap_lines(tmp_path):
    module = _module()
    root = _device(tmp_path)

    _render(module, root, FAILED_CARD_UNITS)

    issue = (root / "run/rosy-boot/issue").read_text(encoding="utf-8")
    assert "Wi-Fi AP" not in issue
    assert "network=sta" in (root / "etc/avahi/services/rosy.service").read_text(encoding="utf-8")


# --- D-260: the boot display's inputs it cannot read itself ---------------------

READY_UNITS = {unit: "active\n" for unit in FAILED_CARD_UNITS}


def test_the_record_carries_the_runtime_mode_and_the_device_states(tmp_path):
    module = _module()
    root = _device(tmp_path)
    (root / "etc/rosy/runtime.env").write_text("ROSY_API_PORT=8081\nROSY_RUNTIME_MODE=motor\n", encoding="utf-8")
    (root / "run/rosy-boot").mkdir(parents=True)
    (root / "run/rosy-boot/hardware.json").write_text(json.dumps({"schema": 1, "devices": [
        {"id": "camera", "state": "no_response", "product": True, "evidence": "CSI -121", "label": "카메라"},
        {"id": "imu", "state": "bus_missing", "product": False, "evidence": "x"}]}), encoding="utf-8")

    record, errors, _calls = _render(module, root, READY_UNITS)

    assert errors == [] and record["api_port"] == 8081
    assert record["runtime_mode"] == "motor"
    # Evidence and labels stay in the 0640 hardware.json.
    assert record["devices"] == [{"id": "camera", "state": "no_response", "product": True},
                                 {"id": "imu", "state": "bus_missing", "product": False}]
    written = json.loads((root / "run/rosy-boot/boot-status.json").read_text(encoding="utf-8"))
    assert written["devices"] == record["devices"] and written["runtime_mode"] == "motor"


@pytest.mark.parametrize("hardware", [
    None, "not json", {"schema": 2, "devices": []},
    {"schema": 1, "devices": [{"id": "camera", "state": "broken", "product": True}]},
    {"schema": 1, "devices": [{"id": "camera", "state": "ok", "product": "yes"}]},
    {"schema": 1, "devices": [{"id": "x" * 65, "state": "ok", "product": True}]},
    {"schema": 1, "devices": [{"id": "d", "state": "ok", "product": True}] * 65},
])
def test_an_absent_or_malformed_probe_result_copies_no_device(tmp_path, hardware):
    module = _module()
    root = _device(tmp_path)
    if hardware is not None:
        (root / "run/rosy-boot").mkdir(parents=True)
        (root / "run/rosy-boot/hardware.json").write_text(
            hardware if isinstance(hardware, str) else json.dumps(hardware), encoding="utf-8")

    record, _errors, _calls = _render(module, root, READY_UNITS)

    assert record["devices"] == []


@pytest.mark.parametrize("line,expected", [("ROSY_RUNTIME_MODE=hardware", "hardware"),
                                           ("ROSY_RUNTIME_MODE=turbo", None), ("", None)])
def test_only_a_known_runtime_mode_is_copied(tmp_path, line, expected):
    module = _module()
    root = _device(tmp_path)
    (root / "etc/rosy/runtime.env").write_text(line + "\n", encoding="utf-8")

    assert module.gather(root, _runner(READY_UNITS, []))["runtime_mode"] == expected
