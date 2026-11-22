"""POSIX flock guard for shared top D435 depth Z16 captures (`depth-d435.lock`)."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import time

try:
    import fcntl
except ImportError:  # Windows unit tests
    fcntl = None  # type: ignore[assignment]

try:
    from joint_tune_lock import lock_root as _lock_root
except ImportError:  # standalone helpers without deploy/robot/omx on sys.path

    def _lock_root() -> Path:
        return Path(os.environ.get("ROSY_OMX_HOME", Path.home() / "rosy-omx"))


LOCK_FILENAME = "depth-d435.lock"


def depth_lock_path(lock_dir: Path | None = None) -> Path:
    return Path(lock_dir) / LOCK_FILENAME if lock_dir is not None else _lock_root() / LOCK_FILENAME


def is_depth_lock_held(lock_dir: Path | None = None) -> bool:
    """True when another process holds an exclusive `depth-d435.lock`."""
    if fcntl is None:
        return False
    path = depth_lock_path(lock_dir)
    if not path.exists():
        return False
    with open(path, "a+", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return False


@contextmanager
def hold_depth_lock(timeout_s: float = 5.0, lock_dir: Path | None = None):
    """Acquire `depth-d435.lock` exclusively until `timeout_s` or raise TimeoutError."""
    if fcntl is None:
        yield
        return
    path = depth_lock_path(lock_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    try:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("depth-d435.lock busy") from None
                time.sleep(min(0.05, remaining))
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()
