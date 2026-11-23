"""Non-blocking GPU training/lock probe for `act_policy_http_server.py` (D-1073)."""
from __future__ import annotations

import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows unit test compatibility
    fcntl = None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    proc_root = Path("/proc")
    if proc_root.is_dir():
        return (proc_root / str(pid)).exists()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def gpu_training_status(gpu_lock_file: Path | None, jobs_dir: Path | None) -> tuple[bool, str | None]:
    """Return ``(busy, reason)`` without ever keeping a persistent descriptor on ``gpu_lock_file``."""
    if gpu_lock_file is not None and fcntl is not None:
        lock_path = Path(gpu_lock_file).expanduser()
        if lock_path.exists():
            try:
                with lock_path.open("r", encoding="utf-8", errors="ignore") as fh:
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except OSError:
                        return True, "gpu_lock_held"
                    finally:
                        try:
                            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            pass
            except OSError:
                return True, "gpu_lock_unreadable"

    if jobs_dir is not None:
        jdir = Path(jobs_dir).expanduser()
        if jdir.is_dir():
            for path in sorted(jdir.glob("*.lock")):
                try:
                    parts = path.read_text(encoding="utf-8", errors="replace").split()
                    if len(parts) >= 2 and parts[1] == "gpu" and _pid_alive(int(parts[0])):
                        return True, f"train_lock:{path.name}"
                except (OSError, ValueError):
                    continue
    return False, None
