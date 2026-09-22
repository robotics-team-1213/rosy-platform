#!/usr/bin/env python3
"""Inspect a mounted ROSY OS root without executing it."""

from __future__ import annotations

import argparse
import json
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
    )
    for path in required_paths:
        if not path.is_file():
            findings.append(f"missing required image path: {path.relative_to(root)}")
    # D-174 F1: each installed runtime copy imports signing from its own directory.
    for runtime in (root / "opt/rosy/native-runtime", release / "deploy/robot/native"):
        if (runtime / "native_release.py").is_file() and not (runtime / "signing.py").is_file():
            findings.append(
                f"missing native runtime helper: {(runtime / 'signing.py').relative_to(root).as_posix()}"
            )
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
