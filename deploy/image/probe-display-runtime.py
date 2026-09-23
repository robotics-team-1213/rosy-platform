#!/usr/bin/env python3
"""Check the boot display (rosy-boot-display) inside the built image (D-190).

On rosy-pinky-e4us (release 005) the product image had neither ``spidev`` nor
``RPi.GPIO`` and nothing drew the LCD. customize-rootfs.sh runs this in the
chroot as rosy-boot-display.service runs (user rosy-display, its HOME, no user
site, the release's site-packages on PYTHONPATH, no ROS), and a failure fails
the build.

Checks:
1. ``spidev``, ``lgpio``, ``numpy`` and ``PIL`` import from the apt packages;
2. ``RPi.GPIO`` is the rpi-lgpio layer (the classic RPi.GPIO does not drive
   the Pi 5's RP1). Its import may refuse a builder that is not a Raspberry
   Pi; that is accepted only when /proc/device-tree/model names no Pi;
3. ``rosylib.Battery`` and ``emotion.info_screen.render_boot`` import from the
   release, and the boot card renders for every stage with the DejaVu font;
4. the unit is installed, enabled for multi-user.target and keeps its
   sandbox (DevicePolicy=closed and exactly the three devices).

It opens no device and writes nothing; run it with ``python3 -B``.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import sys

APT_MODULES = ("spidev", "lgpio", "numpy", "PIL.Image")
APT_PREFIX = "/usr/lib/python3/dist-packages"
RELEASE_MODULES = ("rosylib", "rosylib.battery", "emotion.info_screen")
FONT = "usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
UNIT = "rosy-boot-display.service"
UNIT_RULES = (
    "User=rosy-display", "Environment=PYTHONNOUSERSITE=1", "ProtectSystem=strict",
    "ProtectHome=true", "DevicePolicy=closed", "PrivateNetwork=true",
    "ExecStart=/usr/bin/python3 -B /opt/rosy/native-runtime/rosy-boot-display.py",
)
DEVICES = ("/dev/spidev0.0", "/dev/gpiochip4", "/dev/i2c-1")
STAGES = ("BOOTING", "PROVISIONED", "CORE_READY", "FAILED:rosy-core")


def _on_a_pi(root: Path) -> bool:
    try:
        return "Raspberry Pi" in (root / "proc/device-tree/model").read_text(errors="replace")
    except OSError:
        return False


def check_modules(root: Path, release: str) -> list[str]:
    failures: list[str] = []
    for name in APT_MODULES:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - report every broken import
            failures.append(f"import {name}: {exc!r}")
            continue
        location = str(getattr(module, "__file__", "") or "")
        if not location.startswith(APT_PREFIX + "/"):
            failures.append(f"{name}: imported from {location}, not {APT_PREFIX}")
    spec = importlib.util.find_spec("RPi.GPIO")
    origin = str(getattr(spec, "origin", "") or "")
    if spec is None or not origin.startswith(APT_PREFIX + "/"):
        failures.append(f"RPi.GPIO: not the apt rpi-lgpio layer ({origin or 'missing'})")
    else:
        try:
            gpio = importlib.import_module("RPi.GPIO")
            if "lgpio" not in dir(gpio):  # rpi-lgpio imports lgpio into the module
                failures.append(f"RPi.GPIO at {origin} is not rpi-lgpio")
        except Exception as exc:  # noqa: BLE001
            if _on_a_pi(root):
                failures.append(f"import RPi.GPIO: {exc!r}")
            else:
                print(f"DISPLAY_PROBE_NOTE RPi.GPIO import refused off a Pi ({type(exc).__name__}); "
                      f"installed at {origin}")
    for name in RELEASE_MODULES:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"import {name}: {exc!r}")
            continue
        location = os.path.realpath(str(getattr(module, "__file__", "") or ""))
        if not location.startswith(release.rstrip("/") + "/"):
            failures.append(f"{name}: imported from {location}, not the release {release}")
    return failures


def check_render(root: Path) -> list[str]:
    failures: list[str] = []
    if not (root / FONT).is_file():
        failures.append(f"missing font: /{FONT}")
    try:
        info_screen = importlib.import_module("emotion.info_screen")
        for stage in STAGES:
            image = info_screen.render_boot({"stage": stage, "ipv4": ["192.0.2.1"],
                                             "battery_percent": 80, "battery_voltage": 7.9})
            if image.size != info_screen.DEFAULT_SIZE:
                failures.append(f"render_boot({stage}) drew {image.size}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"render_boot: {exc!r}")
    return failures


def check_unit(root: Path) -> list[str]:
    failures: list[str] = []
    path = root / "etc/systemd/system" / UNIT
    if not path.is_file():
        return [f"missing systemd unit: {UNIT}"]
    text = path.read_text(encoding="utf-8")
    for rule in UNIT_RULES:
        if rule not in text:
            failures.append(f"{UNIT}: missing {rule}")
    allowed = sorted(line.split("=", 1)[1].split()[0] for line in text.splitlines()
                     if line.startswith("DeviceAllow="))
    if allowed != sorted(DEVICES):
        failures.append(f"{UNIT}: DeviceAllow {allowed}, expected {sorted(DEVICES)}")
    if not os.path.lexists(root / "etc/systemd/system/multi-user.target.wants" / UNIT):
        failures.append(f"{UNIT} is not enabled")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--release-site", default="/opt/rosy/current/install/lib/python3.12/site-packages")
    args = parser.parse_args(argv)
    release = os.path.realpath(args.release_site)
    failures = check_modules(args.root, release) + check_render(args.root) + check_unit(args.root)
    if failures:
        for failure in failures:
            print(f"DISPLAY_PROBE_FAIL {failure}", file=sys.stderr)
        return 1
    print(f"DISPLAY_PROBE_OK modules={len(APT_MODULES) + 1 + len(RELEASE_MODULES)} stages={len(STAGES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
