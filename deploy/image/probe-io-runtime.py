#!/usr/bin/env python3
"""Check the hardware (rosy-io) runtime inside the built image (D-192).

On rosy-pinky-e4us (release 005) ``import dynamixel_sdk`` and ``import rosylib``
failed, ``sllidar_ros2`` was not installed and the rosy-io / rosy-navigation
units were not in the image. customize-rootfs.sh runs this in the chroot as
rosy-io.service would run (user rosy-io, its HOME, no user site, ROS and the
release sourced) after probe-core-runtime.py, and a failure fails the build.

Checks:
1. ``dynamixel_sdk`` and ``serial`` import from the pinned prefix (/usr/local);
2. ``rosylib.Battery`` has the pinkylib interface and ``rosylib.LED`` is refused;
3. the bringup nodes rosy-io launches import (``bringup.bringup``,
   ``bringup.battery_publisher``, the driver and the torque-free probe);
4. ``sllidar_ros2``, ``bringup`` and ``navigation`` resolve inside the release
   install, with ``sllidar_node`` and the launch files the units start;
5. the unit files are installed, not enabled, and keep the D-189 rules; the
   motor udev rule is installed.

It opens no device and writes nothing; run it with ``python3 -B``.
"""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import sys

HARDWARE_MODULES = (
    "dynamixel_sdk",
    "serial",
    "rosylib",
    "rosylib.battery",
    "bringup.dynamixel_driver",
    "bringup.dynamixel_probe",
    "bringup.battery_publisher",
    "bringup.bringup",
)
PINNED_MODULES = ("dynamixel_sdk", "serial")
PACKAGE_FILES = {
    "sllidar_ros2": ("lib/sllidar_ros2/sllidar_node",
                     "share/sllidar_ros2/launch/sllidar_c1_launch.py"),
    "bringup": ("share/bringup/launch/bringup_robot.launch.py",),
    "navigation": ("share/navigation/launch/hardware.launch.py",),
}
UNITS = ("rosy-io.service", "rosy-navigation.service")
UNIT_RULES = ("Environment=PYTHONNOUSERSITE=1", "/usr/bin/bash --noprofile --norc -c '",
              "ProtectSystem=strict", "ProtectHome=true", "DevicePolicy=closed")
UDEV_RULE = "etc/udev/rules.d/99-rosy-motor.rules"


def check_modules(prefix: str) -> list[str]:
    failures: list[str] = []
    for name in HARDWARE_MODULES:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - report every broken import
            failures.append(f"import {name}: {exc!r}")
            continue
        if name in PINNED_MODULES:
            location = str(getattr(module, "__file__", "") or "")
            if not location.startswith(prefix.rstrip("/") + "/"):
                failures.append(f"{name}: imported from {location}, not {prefix}")
    try:
        battery = importlib.import_module("rosylib").Battery
        for method in ("get_voltage", "battery_percentage"):
            if not callable(getattr(battery, method, None)):
                failures.append(f"rosylib.Battery has no {method}()")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"rosylib.Battery: {exc!r}")
    try:
        from rosylib import LED  # noqa: F401
        failures.append("rosylib.LED imported; the LED is bench-only (D-169)")
    except ImportError:
        pass
    return failures


def check_packages(release_install: Path) -> list[str]:
    failures: list[str] = []
    try:
        from ament_index_python.packages import get_package_prefix
    except Exception as exc:  # noqa: BLE001
        return [f"ament_index_python: {exc!r}"]
    release = str(release_install.resolve())
    for package, files in PACKAGE_FILES.items():
        try:
            prefix = Path(get_package_prefix(package))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{package}: not installed ({exc!r})")
            continue
        if not str(prefix.resolve()).startswith(release):
            failures.append(f"{package}: resolves to {prefix}, outside {release}")
        for relative in files:
            if not (prefix / relative).is_file():
                failures.append(f"{package}: missing {relative}")
    return failures


def check_units(root: Path) -> list[str]:
    failures: list[str] = []
    systemd = root / "etc/systemd/system"
    for unit in UNITS:
        path = systemd / unit
        if not path.is_file():
            failures.append(f"missing systemd unit: {unit}")
            continue
        text = path.read_text(encoding="utf-8")
        for rule in UNIT_RULES:
            if rule not in text:
                failures.append(f"{unit}: missing {rule}")
        for wants in systemd.glob("*.wants"):
            if os.path.lexists(wants / unit):
                failures.append(f"{unit} is enabled ({wants.name}); it must start by hand")
    if not (root / UDEV_RULE).is_file():
        failures.append(f"missing motor udev rule: {UDEV_RULE}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", default="/usr/local",
                        help="where the pinned distributions must import from")
    parser.add_argument("--release-install", type=Path, default=Path("/opt/rosy/current/install"))
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(argv)

    failures = (check_modules(args.prefix) + check_packages(args.release_install)
                + check_units(args.root))
    if failures:
        for failure in failures:
            print(f"IO_RUNTIME_PROBE_FAIL {failure}", file=sys.stderr)
        return 1
    print(f"IO_RUNTIME_PROBE_OK modules={len(HARDWARE_MODULES)} packages={len(PACKAGE_FILES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
