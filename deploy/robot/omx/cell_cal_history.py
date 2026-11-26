"""Calibration values a step replaces are kept: the files as they were go to calibration-history/ beside them.

2026-11-26: a remap rewrote the map and emptied the bias file with a single .bak, so a second remap lost the values of the
one before. Nothing here deletes, and keep() never raises: a failed copy is reported on stderr and the new values are
saved either way. Cell configs already keep their .bak-* copies (cell_config_io.atomic_write), so they are not copied here.
shortcut: no pruning (about 80 KB per map save, a few KB per bias save); prune by age if the cell disk runs low.
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

FOLDER = "calibration-history"


def keep(paths, reason: str, clock=time.time) -> Path | None:
    """Copy the existing files among `paths` into <first file's folder>/calibration-history/<UTC time>-<reason>/."""
    try:
        files = [Path(p).expanduser().resolve() for p in paths if p and Path(p).expanduser().is_file()]
        if not files:
            return None
        now = clock()
        folder = files[0].parent / FOLDER / f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime(now))}.{int(now % 1 * 1e6):06d}-{reason}"
        folder.mkdir(parents=True, exist_ok=True)
        for file in files:
            shutil.copy2(file, folder / file.name)
        return folder
    except Exception as exc:  # noqa: BLE001 - the history must never stop a calibration value from being saved
        print(f"calibration history not kept ({reason}): {exc}", file=sys.stderr)
        return None
