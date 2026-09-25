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

D-247 intake: the root board device probe (rosy-hw-probe.service) observes
every board device, bench-only ones included, read-only and outside CORE. It
is not a product surface (it drives nothing and advertises nothing), so like
the display it gets exactly its own nodes, and no other unit gains any.
"""
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "robot" / "compose.yaml"
IO_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-io.service"
NAV_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-navigation.service"
CAPS = ROOT / "deploy" / "robot" / "config" / "capabilities.hardware.yaml"

#: Path fragments that would mean a bench-only device got plumbed in.
#: Note "i2c-0" is the bench IMU bus; the product ADC bus is "i2c-1".
BENCH_ONLY_FRAGMENTS = ("spidev", "i2c-0", "gpiomem", "pwm", "gpiochip",
                        # device classes grant every node of a kind (D-190 review)
                        "char-spi", "char-i2c", "char-gpio")
NATIVE = ROOT / "deploy" / "robot" / "native"
#: D-190: the one unit that may hold display devices, and exactly these.
DISPLAY_UNIT = "rosy-boot-display.service"
DISPLAY_DEVICES = ("/dev/spidev0.0", "/dev/gpiochip4", "/dev/i2c-1")
#: D-247: the read-only probe; the lamp and LCD nodes are only checked for existence.
PROBE_UNIT = "rosy-hw-probe.service"
PROBE_DEVICES = {"/dev/rosy-motor": "rw", "/dev/ttyAMA0": "rw", "/dev/i2c-0": "rw", "/dev/i2c-1": "rw",
                 "/dev/vcio": "rw", "/dev/kmsg": "r"}


def test_compose_io_devices_stay_on_the_d169_surface():
    doc = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    devices = doc["services"]["rosy-io"]["devices"]
    assert len(devices) == 4, f"expected motor/lidar/camera/i2c-1, got {devices}"
    for device in devices:
        for fragment in BENCH_ONLY_FRAGMENTS:
            assert fragment not in device.lower(), (
                f"bench-only device plumbed into compose: {device}")


def service_directives(text: str) -> dict[str, list[str]]:
    """[Service] values in order, as systemd reads them: an empty assignment
    resets the list. ``text`` is the unit followed by its drop-ins."""
    values: dict[str, list[str]] = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section != "[Service]" or not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if value == "":
            values[key] = []
        else:
            values.setdefault(key, []).append(value)
    return values


def _allows(text: str) -> list[str]:
    return [f"DeviceAllow={value}" for value in service_directives(text).get("DeviceAllow", [])]


def _non_root(directives: dict[str, list[str]]) -> bool:
    if directives.get("DynamicUser", ["no"])[-1] in {"yes", "true", "1", "on"}:
        return True
    return directives.get("User", ["root"])[-1] not in {"root", "0"}


def surface_violations(units: dict[str, str]) -> list[str]:
    """Every way the native units' device surface leaves D-169 + D-190."""
    found: list[str] = []
    for name, text in sorted(units.items()):
        directives = service_directives(text)
        allows = _allows(text)
        policy = (directives.get("DevicePolicy") or ["auto"])[-1]
        groups = {word for value in directives.get("SupplementaryGroups", []) for word in value.split()}
        if (_non_root(directives) and groups & {"gpio", "spi"} and policy != "closed"
                and (directives.get("PrivateDevices") or ["false"])[-1] != "true"):
            found.append(f"{name} has {sorted(groups & {'gpio', 'spi'})} without a closed device policy")
        if name == DISPLAY_UNIT:
            devices = sorted(line.split("=", 1)[1].split()[0] for line in allows)
            if devices != sorted(DISPLAY_DEVICES):
                found.append(f"{name} devices {devices} != {sorted(DISPLAY_DEVICES)}")
            if policy != "closed":
                found.append(f"{name} ends with DevicePolicy={policy}, not closed")
            continue
        if name == PROBE_UNIT:
            granted = {}
            for line in allows:
                device, _, access = line.split("=", 1)[1].partition(" ")
                granted[device] = access.strip()
            if granted != PROBE_DEVICES or len(allows) != len(PROBE_DEVICES):
                found.append(f"{name} devices {sorted(granted.items())} != {sorted(PROBE_DEVICES.items())}")
            if policy != "closed":
                found.append(f"{name} ends with DevicePolicy={policy}, not closed")
            if _non_root(directives):
                found.append(f"{name} must stay root: it reads nodes of every group")
            continue
        for line in allows:
            for fragment in BENCH_ONLY_FRAGMENTS:
                if fragment in line.lower():
                    found.append(f"{name} grew a bench-only device: {line}")
    if DISPLAY_UNIT not in units:
        found.append(f"{DISPLAY_UNIT} is missing")
    if PROBE_UNIT not in units:
        found.append(f"{PROBE_UNIT} is missing")
    return found


def _native_units() -> dict[str, str]:
    """Each unit with its drop-ins (``<unit>.d/*.conf``) appended in name order."""
    units = {}
    for path in NATIVE.glob("*.service"):
        text = path.read_text(encoding="utf-8")
        for dropin in sorted((NATIVE / f"{path.name}.d").glob("*.conf")):
            text += "\n" + dropin.read_text(encoding="utf-8")
        units[path.name] = text
    return units


def _in_service(text: str, line: str) -> str:
    """``text`` with ``line`` added at the end of its [Service] section."""
    lines = text.splitlines()
    start = lines.index("[Service]")
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("[")),
               len(lines))
    return "\n".join(lines[:end] + [line] + lines[end:]) + "\n"


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
    ("rosy-io.service", "DeviceAllow=char-spidev rw"),
    ("rosy-navigation.service", "DeviceAllow=char-i2c rw"),
    ("rosy-core.service", "DeviceAllow=char-gpiochip rw"),
    (DISPLAY_UNIT, "DeviceAllow=/dev/gpiomem rw"),
    (DISPLAY_UNIT, "DeviceAllow=/dev/i2c-0 rw"),
    (DISPLAY_UNIT, "DeviceAllow=/dev/ttyAMA0 rw"),
    (DISPLAY_UNIT, "DeviceAllow=char-gpiochip rw"),
    (DISPLAY_UNIT, "DevicePolicy=auto"),
    ("rosy-io.service", "DevicePolicy=auto"),  # gpio/spi groups without a closed policy
    # D-247: the probe gets its six nodes and nothing more, read-only where it only reads.
    (PROBE_UNIT, "DeviceAllow=/dev/gpiochip4 rw"),
    (PROBE_UNIT, "DeviceAllow=/dev/spidev0.0 rw"),
    (PROBE_UNIT, "DeviceAllow=/dev/kmsg rw"),
    (PROBE_UNIT, "DeviceAllow=char-i2c rw"),
    (PROBE_UNIT, "DevicePolicy=auto"),
    (PROBE_UNIT, "User=rosy-core"),
    ("rosy-login-code.service", "DeviceAllow=/dev/i2c-0 rw"),
])
def test_mutation_widening_any_surface_turns_the_guard_red(unit, line):
    units = _native_units()
    units[unit] = _in_service(units[unit], line)

    assert surface_violations(units), f"{unit} + {line} was not caught"


def test_mutation_a_drop_in_is_part_of_the_unit(tmp_path, monkeypatch):
    dropin = tmp_path / f"{DISPLAY_UNIT}.d"
    dropin.mkdir()
    for path in NATIVE.glob("*.service"):
        (tmp_path / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "NATIVE", tmp_path)
    assert surface_violations(_native_units()) == []

    (dropin / "50-widen.conf").write_text("[Service]\nDevicePolicy=auto\n", encoding="utf-8")
    assert any("DevicePolicy=auto" in item for item in surface_violations(_native_units()))
    (dropin / "50-widen.conf").write_text("[Service]\nDeviceAllow=/dev/gpiomem rw\n", encoding="utf-8")
    assert surface_violations(_native_units())
    # an empty DeviceAllow= resets the list, as in systemd
    (dropin / "50-widen.conf").write_text("[Service]\nDeviceAllow=\n", encoding="utf-8")
    assert surface_violations(_native_units())


def test_a_line_after_install_is_not_part_of_the_service():
    # The parser reads [Service] only, like systemd: the proofs above insert there.
    units = _native_units()
    display = units[DISPLAY_UNIT]
    assert "[Install]" in display and display.index("[Service]") < display.index("[Install]")

    assert _allows(display + "DeviceAllow=/dev/gpiomem rw\n") == _allows(display)


def test_mutation_the_display_loses_its_sandbox_or_a_device():
    units = _native_units()
    display = units[DISPLAY_UNIT]

    for mutated in (display.replace("DevicePolicy=closed", "DevicePolicy=auto"),
                    display.replace("DeviceAllow=/dev/i2c-1 rw\n", ""),
                    _in_service(display, "DeviceAllow=")):
        assert surface_violations({**units, DISPLAY_UNIT: mutated})
    assert surface_violations({name: text for name, text in units.items() if name != DISPLAY_UNIT})
    # and back to the real files: green again
    assert surface_violations(units) == []


def test_capabilities_do_not_advertise_bench_sensors():
    caps = yaml.safe_load(CAPS.read_text(encoding="utf-8"))
    assert caps["sensors"] == ["lidar", "encoder"], (
        "advertising imu/battery/etc. while their nodes are bench-only "
        "violates D-32 (advertised capabilities must hold)")
