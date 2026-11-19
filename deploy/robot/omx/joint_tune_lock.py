"""Cell-wide session locks, signal guards, and 5/6/7-DOF follower motor maps for `joint_tune.py`."""
from __future__ import annotations

import contextlib
import os
import re
import signal
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows test hosts without POSIX flock
    fcntl = None  # type: ignore[assignment]

#: 5-DOF follower IDs (11-15 arm + 16 gripper); XL430-W250 = 1060, XL330-M288 = 1200
FOLLOWER_5DOF = {11: (1060, 4), 12: (1060, 4), 13: (1060, 4), 14: (1200, 4), 15: (1200, 4), 16: (1200, 5)}
#: 6-DOF follower IDs (+ ID 17 wrist_yaw)
FOLLOWER_6DOF = {**FOLLOWER_5DOF, 17: (1200, 4)}
#: 7-DOF follower IDs (+ ID 17 wrist_yaw + ID 18 elbow_roll redundant swivel)
FOLLOWER_7DOF = {**FOLLOWER_6DOF, 18: (1060, 4)}

FOLLOWER_BY_DOF = {
    5: FOLLOWER_5DOF,
    6: FOLLOWER_6DOF,
    7: FOLLOWER_7DOF,
}


def follower_map_for_dof(dof: int = 5) -> dict[int, tuple[int, int]]:
    """Return the follower `(model, mode)` map for 5-DOF, 6-DOF, or 7-DOF arms."""
    if dof not in FOLLOWER_BY_DOF:
        raise ValueError(f"Unsupported follower DOF {dof}; expected 5, 6, or 7")
    return dict(FOLLOWER_BY_DOF[dof])


def lock_root() -> Path:
    """One place for the cell's session lock: shared by joint_tune, record_session and omx_autoupdate."""
    return Path(os.environ.get("ROSY_OMX_HOME", Path.home() / "rosy-omx"))


BUSY_S = 4 * 3600  # a session past this lets tests back on the host; host_probe ignores an expired marker


def hold_test_jobs(hold: bool, root: Path):
    """`~/rosy-jobs/busy` keeps remote test jobs off this host while any session runs (2026-11-01: test workers on
    the control PC made arm_a's wrist_roll fault and arm_b miss 477 ticks with two arms). A marker someone else
    wrote is never touched; the last session out (it gets the cell lock alone) removes ours."""
    path = Path.home() / "rosy-jobs" / "busy"
    try:
        if path.exists() and path.read_text().split()[1:2] != ["omx-session"]:
            return
        if hold:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{int(time.time()) + BUSY_S} omx-session {os.getpid()}\n")
            return
        with (root / "session.lock").open("a") as cell:
            fcntl.flock(cell, fcntl.LOCK_EX | fcntl.LOCK_NB)
            path.unlink(missing_ok=True)
    except (OSError, BlockingIOError):
        pass  # the marker only steers tests; another arm still holds the cell, or the disk refused


class _ArmLocks:
    def __init__(self, root, *handles):
        self.root, self.handles = root, handles
        hold_test_jobs(True, root)

    def close(self):
        for handle in reversed(self.handles):
            handle.close()
        hold_test_jobs(False, self.root)


def session_lock(arm: str | None = None):
    """Held for a whole tuning run or recording session. Without `arm` it holds the whole cell. With `arm` it holds
    that arm only: the cell lock shared (the updater and the two-arm pipeline take it exclusively, so they still
    wait for every arm) and the arm's own lock, which its observer also checks (2026-11-01: two arms work at once)."""
    root = lock_root()
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / "session.lock").open("a")
    try:
        fcntl.flock(handle, (fcntl.LOCK_SH if arm else fcntl.LOCK_EX) | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SystemExit("another OMX session holds session.lock")
    if arm is None:
        return _ArmLocks(root, handle)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", arm):
        handle.close()
        raise SystemExit(f"arm id {arm!r} is not a plain name")
    own = (root / f"session-{arm}.lock").open("a")
    try:
        fcntl.flock(own, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        own.close()
        handle.close()
        raise SystemExit(f"another OMX session holds session-{arm}.lock")
    return _ArmLocks(root, handle, own)


def _interrupt(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def protect_signals() -> None:
    """SIGTERM (systemd) and SIGHUP (a dropped SSH session) end the run like Ctrl-C, so cleanup runs."""
    signal.signal(signal.SIGTERM, _interrupt)
    signal.signal(signal.SIGHUP, _interrupt)


@contextlib.contextmanager
def no_interrupts():
    """While cleaning up, a second Ctrl-C (or SIGTERM/SIGHUP) must not abort torque OFF or a restore."""
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    try:
        previous = [signal.signal(s, signal.SIG_IGN) for s in signals]
    except ValueError:  # not the main thread: nothing to mask
        yield
        return
    try:
        yield
    finally:
        for s, handler in zip(signals, previous):
            signal.signal(s, handler)
