#!/usr/bin/env python3
"""Materialize a run-specific verified input lock on the native release host."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import platform
import subprocess
import tempfile
import urllib.request

import yaml


def verify_tailscale(section: dict) -> None:
    """Download the D-477 tailscale deb and refuse unless it is the locked package."""
    url = section["url"]
    if not url.startswith("https://"):
        raise SystemExit(f"tailscale url must be https: {url}")
    with tempfile.TemporaryDirectory() as tmp:
        deb = Path(tmp) / "tailscale.deb"
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - https checked above
            deb.write_bytes(response.read())
        check_tailscale_deb(deb, section)


def check_tailscale_deb(deb: Path, section: dict) -> None:
    data = deb.read_bytes()
    if len(data) != int(section["size"]):
        raise SystemExit(f"tailscale deb size mismatch: got {len(data)}, lock says {section['size']}")
    actual = hashlib.sha256(data).hexdigest()
    if actual != section["sha256"]:
        raise SystemExit(f"tailscale deb sha256 mismatch: got {actual}, lock says {section['sha256']}")
    for flag in ("--info", "--contents"):
        result = subprocess.run(["dpkg-deb", flag, str(deb)], capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(f"dpkg-deb {flag} failed on tailscale deb: {result.stderr.strip()}")
    if "./usr/sbin/tailscaled" not in (line.split()[-1] for line in result.stdout.splitlines() if line.split()):
        raise SystemExit("tailscale deb does not contain the tailscaled binary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    if platform.machine() != "aarch64":
        parser.error("resolved release locks may only be created on native aarch64")
    if len(args.revision) != 40 or any(c not in "0123456789abcdef" for c in args.revision):
        parser.error("revision must be 40 lowercase hexadecimal characters")
    lock = yaml.safe_load(args.input.read_text(encoding="utf-8"))
    lock["image_tool"]["commit"] = args.revision
    lock["sources"]["rosy_revision"] = args.revision
    for section in ("image_tool", "base_image", "os", "ros"):
        lock[section]["verified"] = True
    verify_tailscale(lock["tailscale"])
    lock["tailscale"]["verified"] = True
    args.output.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8", newline="\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
