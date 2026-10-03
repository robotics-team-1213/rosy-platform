#!/usr/bin/env python3
"""Print the colcon source roots from platform_parts.yaml (D-427 wave 0 item 5).

The roots are directories relative to the repository root. Shell consumers read
them space-separated:

    read -r -a COLCON_ROOTS <<< "$(python3 tools/harness/colcon_roots.py)"

Standard library only: the image host and the arm64 payload job may run
without PyYAML, so the manifest keeps ``colcon_roots`` as a one-line flow list.
test/architecture/test_colcon_roots.py checks this parse against PyYAML.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

MANIFEST = Path(__file__).resolve().with_name("platform_parts.yaml")
_LINE = re.compile(r"^colcon_roots:[ \t]*\[([^\]\n]*)\][ \t]*(?:#[^\n]*)?\r?$", re.M)
COLCON_OUTPUT = frozenset({"build", "install", "log"})


def colcon_roots(manifest: Path = MANIFEST) -> tuple[str, ...]:
    """The colcon source roots, in manifest order."""
    matches = _LINE.findall(manifest.read_text(encoding="utf-8"))
    if len(matches) != 1:
        raise ValueError(f"{manifest}: expected one 'colcon_roots: [..]' line, found {len(matches)}")
    roots = tuple(item.strip() for item in matches[0].split(",") if item.strip())
    if not roots or len(roots) != len(set(roots)):
        raise ValueError(f"colcon_roots must be non-empty and unique: {roots}")
    for root in roots:
        path = PurePosixPath(root)
        if (path.is_absolute() or ".." in path.parts or path.as_posix() != root
                or not re.fullmatch(r"[A-Za-z0-9_./-]+", root) or path.parts[0] in COLCON_OUTPUT):
            raise ValueError(f"colcon root must be a plain repo-relative directory: {root!r}")
    # A root inside another would make colcon find its packages twice.
    for outer in roots:
        for inner in roots:
            outer_parts, inner_parts = PurePosixPath(outer).parts, PurePosixPath(inner).parts
            if outer != inner and inner_parts[:len(outer_parts)] == outer_parts:
                raise ValueError(f"colcon root {inner!r} is nested in {outer!r}")
    return roots


if __name__ == "__main__":
    print(" ".join(colcon_roots()))
