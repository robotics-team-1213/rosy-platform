"""Candidate common-config critical section; all patch writers must use it."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import threading
import time


_thread_lock = threading.RLock()
_held = threading.local()


@contextmanager
def transaction(path):
    path = Path(path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("unsafe config path")
    lock = path.with_name(path.name + ".lock")
    with _thread_lock:
        if getattr(_held, "path", None) == path:
            yield path
            return
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        acquired = False
        try:
            info = os.fstat(fd)
            if lock.is_symlink() or not stat.S_ISREG(info.st_mode):
                raise ValueError("unsafe config lock")
            if os.name == "posix" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError("unsafe config lock owner")
            if info.st_size == 0:
                os.write(fd, b"0")
            deadline = time.monotonic() + 2
            while not acquired:
                try:
                    if os.name == "nt":
                        import msvcrt
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("config update busy")
                    time.sleep(.01)
            _held.path = path
            yield path
        finally:
            _held.path = None
            if acquired:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
