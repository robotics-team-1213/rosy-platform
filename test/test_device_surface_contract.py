"""D-169: the v1 product device surface is fixed.

emotion, lamp_control, led and imu_bno055 stay bench-only: no compose device
mapping, no native DeviceAllow entry, and no advertised sensor capability for
them. Widening the surface (hardware profile D-84 + field demand) requires a
superseding ADR — this contract turns accidental half-plumbing (a device node
added without that ADR) into a red test instead of a silent runtime gap.

Context: communication-protocol report 2026-09-22 §8-F; decision recorded in
docs/plans/2026-09-22-communication-protocol-remediation-plan.md (G1).

D-190 / D-181 intake: the LCD (spidev0.0), the RP1 header GPIO chip (LCD lines
and buzzer) and a read of the I2C-1 ADC are product devices now, but only for
the boot display unit. Every other native unit keeps the D-169 surface, and
the display gets exactly those three nodes. The mutation tests below prove
the guard turns red for each way the surface could widen.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "robot" / "compose.yaml"
IO_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-io.service"
NAV_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-navigation.service"
CAPS = ROOT / "deploy" / "robot" / "config" / "capabilities.hardware.yaml"

#: Path fragments that would mean a bench-only device got plumbed in.
#: Note "i2c-0" is the bench IMU bus; the product ADC bus is "i2c-1".
BENCH_ONLY_FRAGMENTS = ("spidev", "i2c-0", "gpiomem", "pwm", "gpiochip")
NATIVE = ROOT / "deploy" / "robot" / "native"
#: D-190: the one unit that may hold display devices, and exactly these.
DISPLAY_UNIT = "rosy-boot-display.service"
DISPLAY_DEVICES = ("/dev/spidev0.0", "/dev/gpiochip4", "/dev/i2c-1")


def test_compose_io_devices_stay_on_the_d169_surface():
    doc = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    devices = doc["services"]["rosy-io"]["devices"]
    assert len(devices) == 4, f"expected motor/lidar/camera/i2c-1, got {devices}"
    for device in devices:
        for fragment in BENCH_ONLY_FRAGMENTS:
            assert fragment not in device.lower(), (
                f"bench-only device plumbed into compose: {device}")


def _allows(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith("DeviceAllow=")]


def surface_violations(units: dict[str, str]) -> list[str]:
    """Every way the native units' device surface leaves D-169 + D-190."""
    found: list[str] = []
    for name, text in sorted(units.items()):
        allows = _allows(text)
        if name == DISPLAY_UNIT:
            devices = sorted(line.split("=", 1)[1].split()[0] for line in allows)
            if devices != sorted(DISPLAY_DEVICES):
                found.append(f"{name} devices {devices} != {sorted(DISPLAY_DEVICES)}")
            if "DevicePolicy=closed" not in text:
                found.append(f"{name} is not DevicePolicy=closed")
            continue
        for line in allows:
            for fragment in BENCH_ONLY_FRAGMENTS:
                if fragment in line.lower():
                    found.append(f"{name} grew a bench-only device: {line}")
    if DISPLAY_UNIT not in units:
        found.append(f"{DISPLAY_UNIT} is missing")
    return found


def _native_units() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in NATIVE.glob("*.service")}


def test_native_device_allow_stays_on_the_d169_surface():
    for unit in (IO_UNIT, NAV_UNIT):
        assert _allows(unit.read_text(encoding="utf-8")), f"{unit.name} pins no device surface at all"
    assert surface_violations(_native_units()) == []


@pytest.mark.parametrize("unit,line", [
    ("rosy-io.service", "DeviceAllow=/dev/spidev0.0 rw"),
    ("rosy-io.service", "DeviceAllow=/dev/gpiochip4 rw"),
    ("rosy-navigation.service", "DeviceAllow=/dev/gpiochip4 rw"),
    ("rosy-core.service", "DeviceAllow=/dev/spidev0.0 rw"),
    ("rosy-boot-status.service", "DeviceAllow=/dev/gpiochip4 rw"),
    ("rosy-io.service", "DeviceAllow=/dev/i2c-0 rw"),
    (DISPLAY_UNIT, "DeviceAllow=/dev/gpiomem rw"),
    (DISPLAY_UNIT, "DeviceAllow=/dev/i2c-0 rw"),
    (DISPLAY_UNIT, "DeviceAllow=/dev/ttyAMA0 rw"),
])
def test_mutation_widening_any_surface_turns_the_guard_red(unit, line):
    units = _native_units()
    units[unit] = units[unit] + line + "\n"

    assert surface_violations(units), f"{unit} + {line} was not caught"


def test_mutation_the_display_loses_its_sandbox_or_a_device():
    units = _native_units()
    display = units[DISPLAY_UNIT]

    for mutated in (display.replace("DevicePolicy=closed", "DevicePolicy=auto"),
                    display.replace("DeviceAllow=/dev/i2c-1 rw\n", "")):
        assert surface_violations({**units, DISPLAY_UNIT: mutated})
    assert surface_violations({name: text for name, text in units.items() if name != DISPLAY_UNIT})
    # and back to the real files: green again
    assert surface_violations(units) == []


def test_capabilities_do_not_advertise_bench_sensors():
    caps = yaml.safe_load(CAPS.read_text(encoding="utf-8"))
    assert caps["sensors"] == ["lidar", "encoder"], (
        "advertising imu/battery/etc. while their nodes are bench-only "
        "violates D-32 (advertised capabilities must hold)")
