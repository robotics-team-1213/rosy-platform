"""Give a hold_gpu.sh lock back while an alone test waits, then take it again (D-866 §4 batch jobs beside remote_job).

A training under tools/remote/hold_gpu.sh keeps ~/rosy-jobs/train-<pid>.lock for hours, and remote_job admits an alone
job only on an empty host, with every pytest queued behind it (2026-11-09: three suites waited 4 h behind a SmolVLA run).
A job calls yield_turn() where it can stop (between stages, after a checkpoint): with an alone job waiting it moves its
lock aside, waits until no alone job waits or runs, and puts the lock back under the .admit flock remote_job admits with.
"""
import fcntl
import os
import time
from pathlib import Path

JOBS = Path.home() / "rosy-jobs"


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _fields(path):
    try:
        return path.read_text(encoding="utf-8").split()
    except OSError:
        return []


def alone_waiting(jobs=None):
    jobs = jobs or JOBS
    return any(f and f[0].isdigit() and alive(int(f[0])) for f in map(_fields, jobs.glob("*.alone-wait")))


def alone_running(jobs=None):
    jobs = jobs or JOBS
    return any(len(f) > 1 and f[1] == "alone" and f[0].isdigit() and alive(int(f[0])) for f in map(_fields, jobs.glob("*.lock")))


def yield_turn(jobs=None, pid=None, poll=30., say=print, sleep=time.sleep):
    """Seconds spent aside; 0 when this process holds no lock or no alone job waits."""
    jobs = jobs or JOBS
    lock = jobs / f"train-{pid or os.getpid()}.lock"
    if not lock.exists() or not alone_waiting(jobs):
        return 0.
    aside, started = lock.with_name(lock.name + ".aside"), time.monotonic()
    lock.rename(aside)  # a dead job's .aside is no lock: remote_job reads *.lock only
    say(f"[gpu-yield] {lock.name} aside: an alone test waits", flush=True)
    with open(jobs / ".admit", "a") as admit:
        while True:
            sleep(poll)
            fcntl.flock(admit, fcntl.LOCK_EX)
            try:
                if not alone_waiting(jobs) and not alone_running(jobs):
                    aside.rename(lock)
                    break
            finally:
                fcntl.flock(admit, fcntl.LOCK_UN)
    waited = time.monotonic() - started
    say(f"[gpu-yield] {lock.name} back after {waited:.0f} s", flush=True)
    return waited
