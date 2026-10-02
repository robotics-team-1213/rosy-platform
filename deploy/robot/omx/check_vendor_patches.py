"""Apply every open_manipulator patch to the pinned vendor files, in exact Dockerfile order.

Host check that the image build's `git apply --check` chain holds before a rebuild: it fetches
only the vendor files the patches touch (raw GitHub at stack.lock.yaml's revision), applies the
patches the Dockerfile applies to ``/opt/omx_ws/src/open_manipulator`` in its order, then parses
the resulting launch (.py), YAML and xacro (XML) files.

Usage: check_vendor_patches.py [--cache DIR]
Exit 0 on success, 1 on an apply or parse failure, 3 when the vendor files cannot be fetched.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import yaml

OMX = Path(__file__).resolve().parent
RAW = "https://raw.githubusercontent.com/ROBOTIS-GIT/open_manipulator/{revision}/{path}"
_APPLY = re.compile(r"COPY patches/(?P<name>[\w.-]+\.patch) /tmp/(?P=name)\s*\n"
                    r"RUN git -C /opt/omx_ws/src/open_manipulator apply --check /tmp/(?P=name)")


class FetchError(RuntimeError):
    """The pinned vendor files are unavailable (offline or upstream moved)."""


def dockerfile_patch_order(dockerfile: Path = OMX / "Dockerfile") -> list[Path]:
    names = [match.group("name") for match in _APPLY.finditer(dockerfile.read_text(encoding="utf-8"))]
    if not names:
        raise ValueError("no open_manipulator patch applications found in the Dockerfile")
    return [OMX / "patches" / name for name in names]


def vendor_revision(lock: Path = OMX / "stack.lock.yaml") -> str:
    return str(yaml.safe_load(lock.read_text(encoding="utf-8"))["vendor"]["revision"])


def touched_vendor_files(patches: list[Path]) -> list[str]:
    """Pre-existing vendor paths (``--- a/...``); files a patch creates come from /dev/null."""
    paths: list[str] = []
    for patch in patches:
        for line in patch.read_text(encoding="utf-8").splitlines():
            if line.startswith("--- a/") and line[6:] not in paths:
                paths.append(line[6:])
    return paths


def fetch(paths: list[str], revision: str, cache: Path) -> Path:
    base = cache / revision
    for path in paths:
        target = base / path
        if target.is_file():
            continue
        try:
            with urllib.request.urlopen(RAW.format(revision=revision, path=path), timeout=20) as response:
                data = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FetchError(f"{path}: {exc}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return base


def _git(work: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(work), *args],
                          capture_output=True, text=True)


def apply_in_order(vendor: Path, patches: list[Path], work: Path) -> list[str]:
    """Copy the vendor files into a fresh git tree and apply each patch; return failures."""
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(vendor, work)
    _git(work, "init", "-q")
    errors = []
    for patch in patches:
        checked = _git(work, "apply", "--check", str(patch))
        if checked.returncode != 0:
            errors.append(f"{patch.name}: {checked.stderr.strip()}")
            break
        applied = _git(work, "apply", str(patch))
        if applied.returncode != 0:
            errors.append(f"{patch.name}: {applied.stderr.strip()}")
            break
    return errors


def parse_results(work: Path, patches: list[Path]) -> list[str]:
    errors = []
    for path in sorted({line[6:] for patch in patches for line in patch.read_text(encoding="utf-8").splitlines()
                        if line.startswith("+++ b/")}):
        file = work / path
        try:
            text = file.read_text(encoding="utf-8")
            if path.endswith(".py"):
                ast.parse(text, filename=path)
            elif path.endswith((".yaml", ".yml")):
                list(yaml.safe_load_all(text))
            elif path.endswith((".xacro", ".xml", ".urdf")):
                ElementTree.fromstring(text)
        except Exception as exc:  # report every unparsable result
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
    return errors


def check(cache: Path | None = None, work: Path | None = None) -> tuple[list[str], Path]:
    """Run the whole check; returns (errors, patched tree). Raises FetchError when offline."""
    patches = dockerfile_patch_order()
    cache = cache or Path(tempfile.gettempdir()) / "rosy-omx-vendor-cache"
    vendor = fetch(touched_vendor_files(patches), vendor_revision(), cache)
    work = work or Path(tempfile.mkdtemp(prefix="rosy-omx-vendor-patch-"))
    errors = apply_in_order(vendor, patches, work)
    return (errors or parse_results(work, patches)), work


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", type=Path, default=None, help="vendor file cache (default: system temp)")
    args = parser.parse_args(argv)
    try:
        errors, work = check(args.cache)
    except FetchError as exc:
        print(f"vendor files unavailable: {exc}", file=sys.stderr)
        return 3
    for error in errors:
        print(error, file=sys.stderr)
    print(f"{'FAILED' if errors else 'ok'}: {', '.join(p.name for p in dockerfile_patch_order())} -> {work}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
