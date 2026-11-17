"""D-977 Decision 8 / D-911 4: a person at the cell, as a short-lived single-use local file.

``--commissioning`` and ``person_at_switch`` are passed to a carry only when this file exists, is owned by the owner's
user, is not group/world writable and is younger than ``MAX_AGE_S``. It is renamed away before use, so one file serves
one carry. It never comes from a wire message; a person at the cell creates it with ``install -m 600 /dev/null <path>``.
MAX_AGE_S is a proposal (a person walks to the arm and back), not a measurement.
"""
import os
from pathlib import Path
import stat
import time

MAX_AGE_S = 600.0


def consume(path, *, max_age_s: float = MAX_AGE_S, now=time.time) -> bool:
    """True once for a fresh token; a stale or unsafe file is never accepted (a stale one is removed)."""
    path = Path(path)
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        return False
    claimed = path.with_name(f"{path.name}.{os.getpid()}.used")
    try:
        os.rename(path, claimed)                     # atomic: of two readers only one wins the token
    except OSError:
        return False
    try:
        os.unlink(claimed)
    except OSError:
        pass
    return 0 <= now() - info.st_mtime <= max_age_s
