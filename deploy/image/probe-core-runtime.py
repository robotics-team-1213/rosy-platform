#!/usr/bin/env python3
"""Import what rosy-core.service loads at start, inside the built image (D-189).

The first 2026.09.23-005 boot failed on ``from pydantic import field_validator``
because rosdep had installed apt pydantic 1.10. Every host test and the image
build passed: the image never imported CORE. customize-rootfs.sh runs this in
the chroot with ROS and the release overlay sourced, and a failure fails the
image build.

Checks, in order:
1. every distribution pinned in the requirements file is installed at exactly
   that version, and pydantic's major version is 2;
2. the pinned modules import from the pinned install prefix, not from apt;
3. ``core.main`` and ``core.node`` import, and so does every module either of
   them imports lazily inside a function (``import uvicorn``,
   ``core_api_web.api.app``, the bridges), except imports guarded by ``try``;
4. the extra modules CORE loads later on its hot path (fleet agent websockets).

It writes nothing: run it with ``python3 -B`` so no bytecode lands in the
signed release tree.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.metadata
import importlib.util
from pathlib import Path
import re
import sys


ENTRY_MODULES = ("core.main", "core.node")
EXTRA_MODULES = (
    "core_api_web.api.app",
    "core_features.fleet_agent.agent",
    "websockets",
    "websockets.exceptions",
)
# Distribution name -> top-level module, where they differ.
MODULE_NAMES = {
    "pydantic-core": "pydantic_core",
    "typing-extensions": "typing_extensions",
    "typing-inspection": "typing_inspection",
    "annotated-types": "annotated_types",
    "annotated-doc": "annotated_doc",
    "pyserial": "serial",  # D-192 rosy-io set; dynamixel-sdk maps by rule
}
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)")


def read_pins(requirements: Path) -> dict[str, str]:
    """``name==version`` lines of a hash-locked requirements file."""
    pins: dict[str, str] = {}
    for line in requirements.read_text(encoding="utf-8").splitlines():
        match = PIN.match(line.strip())
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    if not pins:
        raise ValueError(f"no pins in {requirements}")
    return pins


def lazy_imports(source: str) -> list[str]:
    """Absolute modules a file imports anywhere, except under ``try``."""
    tree = ast.parse(source)
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for child in node.body:
                guarded.update(id(inner) for inner in ast.walk(child))
    modules: list[str] = []
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "__future__":
                continue
            modules.append(node.module)
            modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return list(dict.fromkeys(modules))


def _import(name: str) -> None:
    """Import a module, or the attribute ``a.b.c`` names on module ``a.b``."""
    try:
        importlib.import_module(name)
        return
    except ModuleNotFoundError as exc:
        parent, _, attribute = name.rpartition(".")
        if not parent or exc.name != name:
            raise
    module = importlib.import_module(parent)
    if not hasattr(module, attribute):
        raise ImportError(f"cannot import name {attribute!r} from {parent!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--prefix", default="/usr/local",
                        help="where the pinned distributions must import from")
    args = parser.parse_args(argv)

    failures: list[str] = []
    pins = read_pins(args.requirements)
    for name, version in pins.items():
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            failures.append(f"{name}: not installed (pinned {version})")
            continue
        if installed != version:
            failures.append(f"{name}: {installed} installed, {version} pinned")
        module_name = MODULE_NAMES.get(name, name.replace("-", "_"))
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - report every broken import
            failures.append(f"{name}: import {module_name} failed: {exc!r}")
            continue
        location = str(getattr(module, "__file__", "") or "")
        if not location.startswith(args.prefix.rstrip("/") + "/"):
            failures.append(f"{name}: imported from {location}, not {args.prefix}")

    try:
        import pydantic

        if not str(pydantic.VERSION).startswith("2."):
            failures.append(f"pydantic {pydantic.VERSION} is not major 2")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"pydantic: {exc!r}")

    modules = list(ENTRY_MODULES)
    for entry in ENTRY_MODULES:
        try:
            spec = importlib.util.find_spec(entry)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{entry}: {exc!r}")
            continue
        if spec is None or not spec.origin:
            failures.append(f"{entry}: not found on the release path")
            continue
        modules.extend(lazy_imports(Path(spec.origin).read_text(encoding="utf-8")))
    modules.extend(EXTRA_MODULES)

    for name in dict.fromkeys(modules):
        try:
            _import(name)
        except Exception as exc:  # noqa: BLE001 - report every broken import
            failures.append(f"import {name}: {exc!r}")

    if failures:
        for failure in failures:
            print(f"CORE_RUNTIME_PROBE_FAIL {failure}", file=sys.stderr)
        return 1
    print(f"CORE_RUNTIME_PROBE_OK pins={len(pins)} modules={len(set(modules))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
