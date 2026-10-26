"""Process-safe serialization of one Fleet journal's physical owner RPCs."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
from threading import local
import time

_held = local()


@contextmanager
def physical_io(path):
    path = Path(path).resolve()
    if getattr(_held, "pid", None) != os.getpid():
        _held.pid, _held.paths = os.getpid(), set()
    held = _held.paths
    if path in held:
        yield
        return
    lock = path.with_name(path.name + ".physical-rpc.lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if lock.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise ValueError("unsafe physical RPC lock")
        if os.name == "posix" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError("unsafe physical RPC lock owner")
        if info.st_size == 0:
            os.write(fd, b"0")
        deadline = time.monotonic() + 2
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("physical profile RPC is busy") from None
                time.sleep(.01)
        held.add(path)
        yield
    finally:
        held.discard(path)
        os.close(fd)
