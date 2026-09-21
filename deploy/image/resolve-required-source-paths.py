#!/usr/bin/env python3
"""Resolve required ROS package paths plus their in-tree dependency closure."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET


DEPENDENCY_TAGS = {
    "depend",
    "build_depend",
    "build_export_depend",
    "buildtool_depend",
    "buildtool_export_depend",
    "exec_depend",
}


def package_catalog(source_root: Path) -> dict[str, tuple[Path, set[str]]]:
    catalog: dict[str, tuple[Path, set[str]]] = {}
    for manifest in sorted(source_root.rglob("package.xml")):
        root = ET.parse(manifest).getroot()
        name_node = root.find("name")
        if name_node is None or not (name_node.text or "").strip():
            raise ValueError(f"package name missing in {manifest}")
        name = (name_node.text or "").strip()
        if name in catalog:
            raise ValueError(f"duplicate package name {name}: {manifest}")
        dependencies = {
            (node.text or "").strip()
            for node in root
            if node.tag in DEPENDENCY_TAGS and (node.text or "").strip()
        }
        catalog[name] = (manifest.parent, dependencies)
    return catalog


def required_names(path: Path) -> list[str]:
    names = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not names or len(names) != len(set(names)):
        raise ValueError("required package list must be non-empty and unique")
    return names


def resolve(catalog: dict[str, tuple[Path, set[str]]], roots: list[str]) -> set[str]:
    missing = sorted(set(roots) - set(catalog))
    if missing:
        raise ValueError("required packages missing from source tree: " + ", ".join(missing))
    selected: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        pending.extend(sorted(catalog[name][1] & catalog.keys()))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--required", type=Path, required=True)
    parser.add_argument("--chroot-prefix", required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve(strict=True)
    catalog = package_catalog(source_root)
    selected = resolve(catalog, required_names(args.required))
    prefix = PurePosixPath(args.chroot_prefix)
    for name in sorted(selected):
        relative = catalog[name][0].relative_to(source_root)
        print(prefix.joinpath(*relative.parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
