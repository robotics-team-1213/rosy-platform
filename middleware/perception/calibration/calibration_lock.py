"""Nonblocking, process-owned lock for calibration read/modify/replace."""
from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def calibration_lock(destination):
    path = Path(destination).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + '.lock')
    if lock.is_symlink():
        raise ValueError('Calibration lock must not be a link')
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(lock, flags, 0o600), 'r+b', buffering=0) as stream:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'\0')
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError('Calibration writer is busy') from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('Calibration writer is busy') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    # Keep the lock inode stable. Unlinking it permits two different lock files
    # to be held concurrently. Process exit releases the OS lock automatically.
