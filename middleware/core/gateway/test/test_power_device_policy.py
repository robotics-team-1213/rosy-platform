"""Per-device power policy (D-440, D-24 amendment).

The product's robot package declares devices; undeclared devices stay on; the
whole policy sits behind one bench switch (power.device_policy.enabled, false)
with a per-device override; timings come from one profile and are overridable
per robot through the CORE overlay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from core.bridge import device_power
from core.system.power import _power_config
from core_common.config import load_config
from core_common.protocol.schemas import PowerMode
from core_features.power.devices import DeviceLevel, parse_device_policy
from core_features.power.manager import PowerManager

ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = ROOT / "contracts" / "foundation" / "config"
PINKY = ROOT / "middleware" / "devices" / "pinky" / "profile" / "config" / "core.yaml"
OMX = ROOT / "middleware" / "devices" / "omx" / "profile" / "config" / "core.yaml"

ON, REDUCED, OFF = DeviceLevel.ON, DeviceLevel.REDUCED, DeviceLevel.OFF


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Bus:
    def __init__(self) -> None:
        self.events = []

    def publish(self, type_, severity=None, source=None, data=None):
        self.events.append((type_, data))

    def types(self):
        return [t for t, _ in self.events]


def _pinky_power(enabled: bool | None = None, **overrides) -> dict:
    default = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))["power"]
    pinky = yaml.safe_load(PINKY.read_text(encoding="utf-8"))["power"]
    default["device_policy"]["devices"] = pinky["device_policy"]["devices"]
    if enabled is not None:
        default["device_policy"]["enabled"] = enabled
    default.update(overrides)
    return default


def _manager(raw: dict, clock: Clock, bus: Bus | None = None) -> PowerManager:
    return PowerManager(_power_config(raw), events=bus, clock=clock)


def _to(mgr: PowerManager, clock: Clock, mode: PowerMode) -> None:
    cfg = mgr._cfg
    clock.now += {PowerMode.IDLE: cfg.idle_after_s, PowerMode.STANDBY: cfg.standby_after_s}[mode] + 1.0
    mgr.tick()
    assert mgr.mode == mode


# --- parsing -----------------------------------------------------------------

def test_yaml_on_off_booleans_parse_as_levels():
    cfg = parse_device_policy(yaml.safe_load(
        "devices: {lidar: {idle: on, standby: off}, cam: {idle: reduced}}"))
    assert cfg.devices["lidar"].idle is ON
    assert cfg.devices["lidar"].standby is OFF
    assert cfg.devices["cam"].idle is REDUCED
    assert cfg.devices["cam"].standby is ON          # unstated level stays on
    assert cfg.enabled is False                      # the bench switch defaults off


@pytest.mark.parametrize("spec", [{"idle": "sleepy"}, {"wake_ready_s": -1}])
def test_bad_device_declaration_is_refused(spec):
    with pytest.raises(ValueError):
        parse_device_policy({"devices": {"lidar": spec}})


def test_shipped_defaults_keep_the_bench_switch_off():
    raw = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
    cfg = _power_config(raw["power"])
    assert cfg.device_policy.enabled is False
    assert cfg.device_policy.devices == {}


def test_pinky_declares_lidar_camera_perception_and_not_the_wheels():
    devices = parse_device_policy(
        yaml.safe_load(PINKY.read_text(encoding="utf-8"))["power"]["device_policy"]).devices
    assert set(devices) == {"lidar", "camera", "perception"}
    assert devices["lidar"].required_for_motion is True
    assert all(p.enabled is None for p in devices.values())    # nothing bypasses the switch


def test_omx_declares_no_devices():
    assert "power" not in (yaml.safe_load(OMX.read_text(encoding="utf-8")) or {})


# --- switch off: exactly the old behaviour ----------------------------------

def test_switch_off_keeps_every_device_on_and_quiet():
    clock, bus = Clock(), Bus()
    mgr = _manager(_pinky_power(), clock, bus)
    _to(mgr, clock, PowerMode.STANDBY)
    assert set(mgr.device_levels().values()) == {ON}
    assert mgr.motion_ready() is True
    assert "power.device_changed" not in bus.types()
    assert all(not d.managed for d in mgr.status().devices)


# --- switch on ---------------------------------------------------------------

@pytest.mark.parametrize("mode,expected", [
    (PowerMode.IDLE, {"lidar": ON, "camera": ON, "perception": REDUCED}),
    (PowerMode.STANDBY, {"lidar": OFF, "camera": OFF, "perception": OFF}),
])
def test_levels_follow_the_declared_table(mode, expected):
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True), clock)
    _to(mgr, clock, mode)
    assert mgr.device_levels() == expected


def test_wake_restores_devices_and_readiness_waits_per_device():
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True), clock)
    _to(mgr, clock, PowerMode.STANDBY)
    assert mgr.motion_ready() is False
    mgr.on_command("teleop")
    assert set(mgr.device_levels().values()) == {ON}
    for name in ("lidar", "camera", "perception"):
        mgr.report_device_ready(name, True)
    clock.now += 0.6
    assert mgr.device_ready("perception") is True
    assert mgr.device_ready("lidar") is False
    assert mgr.motion_ready() is False
    clock.now += 1.5                                  # 2.1 s
    assert mgr.motion_ready() is True                 # only lidar is required for motion
    assert mgr.device_ready("camera") is False
    clock.now += 1.0
    assert mgr.device_ready("camera") is True


def test_a_woken_device_is_not_ready_until_it_confirms():
    """Fail safe: time alone never makes a device ready again after OFF."""
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True), clock)
    _to(mgr, clock, PowerMode.STANDBY)
    mgr.report_device_ready("lidar", True)            # a last scan while OFF is not a confirmation
    mgr.on_command("teleop")
    clock.now += 60.0
    assert mgr.device_ready("lidar") is False
    assert mgr.motion_ready() is False
    assert mgr.status().motion_ready is False
    mgr.report_device_ready("lidar", True)
    assert mgr.motion_ready() is True


def test_the_ready_clock_restarts_when_the_wake_command_really_went_out():
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True), clock)
    _to(mgr, clock, PowerMode.STANDBY)
    mgr.on_command("teleop")
    clock.now += 5.0                                  # start_motor service came up late
    mgr.device_restarted("lidar")
    mgr.report_device_ready("lidar", True)
    assert mgr.motion_ready() is False                # the spin-up counts from the send
    clock.now += 2.1
    assert mgr.motion_ready() is True


def test_a_report_before_the_wake_command_went_out_is_not_a_confirmation():
    """Review finding: a scan still in flight while the motor stops must not confirm the wake."""
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True), clock)
    _to(mgr, clock, PowerMode.STANDBY)
    mgr.on_command("teleop")
    mgr.report_device_ready("lidar", True)            # leftover scan, start_motor not sent yet
    mgr.device_restarted("lidar")                     # now it is sent ... and has no effect
    clock.now += 60.0
    assert mgr.motion_ready() is False


def test_with_the_switch_off_no_report_can_hold_motion():
    clock = Clock()
    mgr = _manager(_pinky_power(), clock)
    mgr.report_device_ready("lidar", False)
    mgr.device_restarted("lidar")
    assert mgr.motion_ready() is True
    assert mgr.managed_devices() == set()


def test_a_managed_device_must_confirm_after_core_starts():
    """CORE may have restarted while the device was off: motion waits for its report."""
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True), clock)
    assert mgr.managed_devices() == {"lidar", "camera", "perception"}
    clock.now += 60.0
    assert mgr.motion_ready() is False
    mgr.report_device_ready("lidar", True)
    assert mgr.motion_ready() is True


def test_an_unknown_applied_level_is_sent_once_and_counts_as_a_restart():
    port, restarted = FakePort("lidar"), []
    applied = {"lidar": None}
    for _ in range(3):
        device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port}, restarted=restarted.append)
    assert port.calls == [ON] and restarted == ["lidar"]


@pytest.mark.parametrize("block", [True, {"devices": ["lidar"]}, {"devices": {"lidar": "off"}},
                                   {"enabled": "false"}, {"devices": {"lidar": {"enabled": "off"}}},
                                   {"devices": {"lidar": {"wake_ready_s": float("nan")}}}])
def test_a_malformed_block_is_refused_by_the_parser_and_leaves_the_policy_off(block):
    with pytest.raises(ValueError):
        parse_device_policy(block)
    cfg = _power_config({"device_policy": block})
    assert cfg.device_policy.enabled is False and cfg.device_policy.devices == {}


def test_adapter_report_holds_readiness_until_the_device_says_so():
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True), clock)
    _to(mgr, clock, PowerMode.STANDBY)
    mgr.wake("api")
    mgr.report_device_ready("lidar", False)
    clock.now += 10.0
    assert mgr.device_ready("lidar") is False
    mgr.report_device_ready("lidar", True)
    assert mgr.device_ready("lidar") is True


def test_reduced_to_on_is_not_a_restart():
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True), clock)
    mgr.report_device_ready("perception", True)       # confirmed once after CORE start
    _to(mgr, clock, PowerMode.IDLE)
    mgr.on_command("mode")
    assert mgr.device_level("perception") is ON
    assert mgr.device_ready("perception") is True


def test_per_device_override_acts_without_the_bench_switch():
    raw = _pinky_power()
    raw["device_policy"]["devices"]["lidar"]["enabled"] = True
    clock = Clock()
    mgr = _manager(raw, clock)
    _to(mgr, clock, PowerMode.STANDBY)
    assert mgr.device_levels() == {"lidar": OFF, "camera": ON, "perception": ON}


def test_undeclared_device_is_always_on():
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True), clock)
    _to(mgr, clock, PowerMode.STANDBY)
    assert mgr.device_level("imu") is ON
    assert mgr.device_ready("imu") is True


def test_power_disabled_overrides_the_device_switch():
    clock = Clock()
    mgr = _manager(_pinky_power(enabled=True) | {"enabled": False}, clock)
    clock.now += 10_000
    mgr.tick()
    assert set(mgr.device_levels().values()) == {ON}


def test_device_change_events_and_status_shape():
    clock, bus = Clock(), Bus()
    mgr = _manager(_pinky_power(enabled=True), clock, bus)
    _to(mgr, clock, PowerMode.STANDBY)
    changed = [d for t, d in bus.events if t == "power.device_changed"]
    assert {d["device"] for d in changed} == {"lidar", "camera", "perception"}
    assert "power.lidar_changed" in bus.types()       # the PWR-005 event stays
    status = mgr.status()
    assert [d.name for d in status.devices] == ["camera", "lidar", "perception"]
    assert status.motion_ready is False and status.lidar_spinning is False


# --- per-robot override through the CORE overlay -----------------------------

def test_overlay_overrides_timings_and_switch_per_robot(tmp_path, monkeypatch):
    overlay = tmp_path / "rosy.yaml"
    overlay.write_text(yaml.safe_dump({"power": {
        "idle_after_s": 30, "standby_after_s": 120,
        "device_policy": {"enabled": True, "devices": {"camera": {"wake_ready_s": 4.0}}}}}),
        encoding="utf-8")
    monkeypatch.setenv("ROSY_CONFIG", str(overlay))
    monkeypatch.setenv("ROSY_ROBOT", "pinky_pro")
    cfg = _power_config(load_config(str(CONFIG_DIR / "rosy_default.yaml"))["power"])
    assert (cfg.idle_after_s, cfg.standby_after_s) == (30.0, 120.0)
    assert cfg.device_policy.enabled is True
    assert cfg.device_policy.devices["camera"].wake_ready_s == 4.0
    assert cfg.device_policy.devices["camera"].standby is OFF   # the profile's facts stay


# --- adapters ------------------------------------------------------------------

class FakePort:
    def __init__(self, name, ready=True):
        self.name, self.ready, self.calls = name, ready, []

    def apply(self, level):
        self.calls.append(level)
        return self.ready


def test_reconcile_sends_nothing_while_levels_stay_on():
    port = FakePort("lidar")
    applied = {}
    for _ in range(5):
        device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port})
    assert port.calls == []


def test_reconcile_sends_once_per_change_and_retries_an_unready_service():
    port = FakePort("lidar", ready=False)
    applied = {}
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port})
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port})
    assert port.calls == [OFF, OFF]                   # not latched while unreachable
    port.ready = True
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port})
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port})
    assert port.calls == [OFF, OFF, OFF]


def test_reconcile_reports_the_restart_only_when_the_on_command_went_out():
    port, applied, restarted = FakePort("lidar"), {}, []
    device_power.reconcile_devices({"lidar": OFF}, applied, {"lidar": port}, restarted=restarted.append)
    port.ready = False
    device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port}, restarted=restarted.append)
    assert restarted == []                            # not sent yet: nothing restarted
    port.ready = True
    device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port}, restarted=restarted.append)
    device_power.reconcile_devices({"lidar": ON}, applied, {"lidar": port}, restarted=restarted.append)
    assert restarted == ["lidar"]


def test_service_port_treats_reduced_as_on():
    sent = []
    port = device_power.ServiceDevicePort("lidar", lambda on: sent.append(on) or True)
    port.apply(REDUCED)
    port.apply(OFF)
    assert sent == [True, False]


def test_topic_ports_share_one_latched_board():
    published = []
    board = device_power.DeviceBoard(published.append)
    device_power.TopicDevicePort("camera", board).apply(OFF)
    device_power.TopicDevicePort("perception", board).apply(REDUCED)
    assert json.loads(published[-1]) == {"camera": "off", "perception": "reduced"}


@pytest.mark.parametrize("raw,expected", [
    ('{"device": "camera", "ready": true}', ("camera", True)),
    ('{"device": "camera", "ready": "yes"}', None),
    ('{"device": "lidar", "ready": true}', None),     # only a scan confirms the LiDAR
    ("not json", None),
    ("[1]", None),
])
def test_ready_report_parsing(raw, expected):
    assert device_power.parse_ready_report(raw) == expected
