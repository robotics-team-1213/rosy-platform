"""D-169: the v1 product device surface is fixed.

emotion, lamp_control, led and imu_bno055 stay bench-only: no compose device
mapping, no native DeviceAllow entry, and no advertised sensor capability for
them. Widening the surface (hardware profile D-84 + field demand) requires a
superseding ADR — this contract turns accidental half-plumbing (a device node
added without that ADR) into a red test instead of a silent runtime gap.

Context: communication-protocol report 2026-09-22 §8-F; decision recorded in
docs/plans/2026-09-22-communication-protocol-remediation-plan.md (G1).
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "robot" / "compose.yaml"
IO_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-io.service"
NAV_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-navigation.service"
CAPS = ROOT / "deploy" / "robot" / "config" / "capabilities.hardware.yaml"

#: Path fragments that would mean a bench-only device got plumbed in.
#: Note "i2c-0" is the bench IMU bus; the product ADC bus is "i2c-1".
BENCH_ONLY_FRAGMENTS = ("spidev", "i2c-0", "gpiomem", "pwm", "gpiochip")


def test_compose_io_devices_stay_on_the_d169_surface():
    doc = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    devices = doc["services"]["rosy-io"]["devices"]
    assert len(devices) == 4, f"expected motor/lidar/camera/i2c-1, got {devices}"
    for device in devices:
        for fragment in BENCH_ONLY_FRAGMENTS:
            assert fragment not in device.lower(), (
                f"bench-only device plumbed into compose: {device}")


def test_native_device_allow_stays_on_the_d169_surface():
    for unit in (IO_UNIT, NAV_UNIT):
        allows = [
            line.strip()
            for line in unit.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("DeviceAllow=")
        ]
        assert allows, f"{unit.name} pins no device surface at all"
        for line in allows:
            for fragment in BENCH_ONLY_FRAGMENTS:
                assert fragment not in line.lower(), (
                    f"{unit.name} grew a bench-only device: {line}")


def test_capabilities_do_not_advertise_bench_sensors():
    caps = yaml.safe_load(CAPS.read_text(encoding="utf-8"))
    assert caps["sensors"] == ["lidar", "encoder"], (
        "advertising imu/battery/etc. while their nodes are bench-only "
        "violates D-32 (advertised capabilities must hold)")
