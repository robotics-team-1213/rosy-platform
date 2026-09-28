#!/usr/bin/env python3
"""Materialize a run-specific verified input lock on the native release host."""

from __future__ import annotations

import argparse
from pathlib import Path
import platform

import yaml


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
    args.output.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8", newline="\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
