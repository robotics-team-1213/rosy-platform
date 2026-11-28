"""Process-owned OS file lock (moved from the retired land_async, D-1090 step 2).

The OS releases it when the holder exits or dies, so a killed run never leaves a stale lock behind.
"""

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path


class Busy(SystemExit):
    """Another process owns this lock."""


@contextmanager
def locked(path: Path, wait: bool = False):
    """A process-owned lock; closing it, including on process death, releases ownership."""
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":  # msvcrt LK_LOCK gave up after ~10 s (EDEADLK) behind a minutes-long holder (11-18)
                from land_queue import nt_lock
                nt_lock(stream.fileno(), wait)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise Busy(f"another process owns {path.name}") from exc
        yield
