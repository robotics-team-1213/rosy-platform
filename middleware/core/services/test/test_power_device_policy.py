"""Per-device power policy (D-440, D-24 amendment).

The product's robot package declares devices; undeclared devices stay on; the
whole policy sits behind one bench switch (power.device_policy.enabled, false)
with a per-device override. A device that was off is ready again only after its
wake time AND a ready report. Config parsing through CORE and the bridge
adapters are tested in the gateway (`test_power_device_adapters.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core_common.protocol.schemas import PowerMode
from core_features.power.devices import DeviceLevel, parse_device_policy
from core_features.power.manager import PowerConfig, PowerManager

ON, REDUCED, OFF = DeviceLevel.ON, DeviceLevel.REDUCED, DeviceLevel.OFF

ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = ROOT / "contracts" / "foundation" / "config"
PINKY = ROOT / "middleware" / "devices" / "pinky" / "profile" / "config" / "core.yaml"
OMX = ROOT / "middleware" / "devices" / "omx" / "profile" / "config" / "core.yaml"


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
    config = PowerConfig(enabled=bool(raw.get("enabled", True)),
                         idle_after_s=float(raw["idle_after_s"]),
                         standby_after_s=float(raw["standby_after_s"]),
                         device_policy=parse_device_policy(raw.get("device_policy")))
    return PowerManager(config, events=bus, clock=clock)


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
