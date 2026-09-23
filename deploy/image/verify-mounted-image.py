#!/usr/bin/env python3
"""Inspect a mounted ROSY OS root without executing it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys


REQUIRED_UNITS = (
    "rosy-first-boot.service",
    "rosy-release-recover.service",
    "rosy-sd-provision.service",
    "rosy-core.service",
    "rosy-runtime.target",
)


def package_names(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


MOTOR_OVERLAY = "dtoverlay=uart4-pi5"
MOTOR_UDEV_RULE = "etc/udev/rules.d/99-rosy-motor.rules"
BASE_BOOT_LINES = ("enable_uart=1", "dtparam=i2c_arm=on")
HARDWARE_UNITS =("rosy-io.service", "rosy-navigation.service")
SLLIDAR_FILES = ("lib/sllidar_ros2/sllidar_node", "share/sllidar_ros2/launch/sllidar_c1_launch.py")


def overlay_applies_to_pi5(text: str, overlay: str = MOTOR_OVERLAY) -> bool:
    """Read-only twin of configure-uart-pi5.sh's awk check: the line counts
    before any section header or under [all] / [pi5], comments stripped."""
    active = True
    for raw in text.splitlines():
        stripped = raw.strip()
        if re.fullmatch(r"\[[^]]+\]", stripped):
            active = re.sub(r"\s", "", stripped) in {"[all]", "[pi5]"}
            continue
        line = re.sub(r"\s*#.*", "", raw).strip()
        if active and line == overlay:
            return True
    return False


def inspect(root: Path, release_id: str) -> list[str]:
    root = root.resolve()
    findings: list[str] = []
    release = root / "opt/rosy/releases" / release_id
    required_paths = (
        root / "opt/ros/jazzy/setup.bash",
        release / "install/setup.bash",
        root / "etc/rosy/motion_profiles.yaml",
        root / "etc/rosy/cyclonedds.xml",
        root / "opt/rosy/first-boot/rosy-first-boot.py",
        root / "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem",
        root / "opt/rosy/native-runtime/native_release.py",
        root / "opt/rosy/native-runtime/recover-release.sh",
        root / "opt/rosy/native-runtime/signing.py",
        release / "deploy/robot/native/native_release.py",
        release / "deploy/robot/native/signing.py",
    )
    for path in required_paths:
        if not path.is_file():
            findings.append(f"missing required image path: {path.relative_to(root)}")
    # D-174 F1: the native runtime runs from the image and must never leave bytecode
    # behind (it would be unlisted and fail verify()). colcon's install/ tree ships
    # its own __pycache__ as part of the built payload, so it is not checked here.
    for runtime in (root / "opt/rosy/native-runtime", release / "deploy/robot/native"):
        if runtime.is_dir():
            for cache in sorted(runtime.rglob("__pycache__")):
                findings.append(f"bytecode cache in native runtime: {cache.relative_to(root).as_posix()}")
    for unit in REQUIRED_UNITS:
        if not (root / "etc/systemd/system" / unit).is_file():
            findings.append(f"missing systemd unit: {unit}")

    required_file = release / "required-ros-packages.txt"
    inventory_file = release / "rosy-packages.txt"
    required = package_names(required_file)
    inventory = package_names(inventory_file)
    for package in sorted(required - inventory):
        findings.append(f"required ROS package missing from inventory: {package}")

    if (root / "usr/bin/docker").exists() or (root / "usr/bin/dockerd").exists():
        findings.append("docker must not be installed in the product image")
    # CORE SRS §25: UTC ISO 8601 timestamps (evidence freshness, Fleet log
    # correlation) presume a synced clock — chrony ships enabled in the image.
    if not (root / "usr/sbin/chronyd").exists():
        findings.append("chrony is not installed: timestamps presume a synced clock")
    elif not (root / "etc/systemd/system/multi-user.target.wants/chrony.service").exists():
        findings.append("chrony.service is not enabled")
    # D-192 US-003: CORE_READY is shown as soon as the runtime target settles.
    # lexists: `systemctl --root` links point at the image's /usr/lib, not the host's.
    ready = "rosy-boot-status-ready.service"
    if not (root / "etc/systemd/system" / ready).is_file():
        findings.append(f"missing systemd unit: {ready}")
    elif not os.path.lexists(root / "etc/systemd/system/multi-user.target.wants" / ready):
        findings.append(f"{ready} is not enabled")
    # D-192 US-004: the motor bus (UART4) and its /dev/rosy-motor alias.
    config = root / "boot/firmware/config.txt"
    if not config.is_file():
        findings.append("missing boot configuration: boot/firmware/config.txt")
    elif not overlay_applies_to_pi5(config.read_text(encoding="utf-8", errors="replace")):
        findings.append(f"boot/firmware/config.txt does not enable {MOTOR_OVERLAY} for the Pi 5")
    if config.is_file():
        # The Ubuntu base image provides these today (LiDAR UART0 /dev/ttyAMA0,
        # ADC /dev/i2c-1, both seen on rosy-pinky-e4us); a new base must not drop them.
        text = config.read_text(encoding="utf-8", errors="replace")
        for line in BASE_BOOT_LINES:
            if not overlay_applies_to_pi5(text, line):
                findings.append(f"boot/firmware/config.txt lost {line} for the Pi 5 (base image changed?)")
    if not (root / MOTOR_UDEV_RULE).is_file():
        findings.append(f"missing motor udev rule: {MOTOR_UDEV_RULE}")
    # D-192 US-005: the hardware runtime ships installed, not enabled (D-161).
    for unit in HARDWARE_UNITS:
        if not (root / "etc/systemd/system" / unit).is_file():
            findings.append(f"missing systemd unit: {unit}")
        for wants in sorted((root / "etc/systemd/system").glob("*.wants")):
            if os.path.lexists(wants / unit):
                findings.append(f"{unit} must not be enabled ({wants.name})")
    if "sllidar_ros2" not in inventory:
        findings.append("sllidar_ros2 (RPLIDAR C1 driver) is missing from the release inventory")
    for relative in SLLIDAR_FILES:
        if not (release / "install" / relative).is_file():
            findings.append(f"sllidar_ros2 is not installed: install/{relative}")
    # D-176: the fallback AP is NetworkManager shared mode, which runs dnsmasq.
    if not (root / "usr/sbin/dnsmasq").exists():
        findings.append("dnsmasq is not installed: the fallback AP (NM shared mode) cannot start")
    runtime = root / "etc/rosy/runtime.env"
    if runtime.exists():
        content = runtime.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(?m)^(ROSY_NAMESPACE|ROSY_ROBOT_NUMBER|ROS_DOMAIN_ID)=.+$", content):
            findings.append("common image is not device-neutral: runtime identity is populated")
    complete = root / "var/lib/rosy/provisioning/complete.json"
    if complete.exists():
        findings.append(f"common image contains device-specific state: {complete.relative_to(root)}")
    connections = root / "etc/NetworkManager/system-connections"
    if connections.is_dir() and any(connections.iterdir()):
        findings.append(f"common image contains device-specific state: {connections.relative_to(root)}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    findings = inspect(args.root, args.release_id)
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "release_id": args.release_id}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
