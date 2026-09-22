"""Tracked Python sources are plain UTF-8, without a byte-order mark.

Several guards read sources with ``ast.parse(path.read_text(encoding="utf-8"))``
(the section 8 event catalogue, the vision boundaries). ``read_text`` keeps a
leading U+FEFF, and ``ast.parse`` then rejects the whole file as invalid, so a
BOM added by a Windows editor turns unrelated guards red at once. Catch it
here, by name, instead.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"


def _tracked_python_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [ROOT / name for name in out.decode("utf-8").split("\0") if name]


def test_no_tracked_python_file_starts_with_a_bom():
    offenders = []
    for path in _tracked_python_files():
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            if handle.read(3) == BOM:
                offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, f"strip the UTF-8 BOM from: {offenders}"
