"""Guards for the bench record page (D-943): other-arm lock holding, /proc visibility, input snapshots, restore list.

Split out of bench_record.py; behaviour is described there. Linux only (fcntl, /proc): anywhere else every check
refuses (fail closed).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import joint_tune_lock  # noqa: E402  (lock_root: where the per-arm session locks live)


def proc_cmdlines():
    """Command lines of every process (Linux /proc); unreadable /proc raises, so the caller refuses (fail closed)."""
    return [(p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            for p in Path("/proc").iterdir() if p.name.isdigit() and p.name != str(os.getpid()) and (p / "cmdline").exists()]


def proc_mounts():
    return Path("/proc/mounts").read_text()


def hold_other_arm_locks(arm, arms, procs=proc_cmdlines, mounts=proc_mounts):
    """(handles, None) with every OTHER arm of `arms`'s lock held, or ([], why a handover must not start). record_session --arm
    takes session.lock shared and session-<arm>.lock exclusive, so holding the same here (never the chosen arm's own,
    record_session takes that) keeps a second session from starting during handover; the caller keeps the handles
    until the units are restored. The /proc scan is an extra check, refused when hidepid could hide processes."""
    handles = []
    try:
        import fcntl
        root = joint_tune_lock.lock_root()
        root.mkdir(parents=True, exist_ok=True)
        others = {f"session-{a}.lock" for a in arms if a != arm}
        others |= {p.name for p in root.glob("session-*.lock")} - {f"session-{arm}.lock"}
        for name, mode in [("session.lock", fcntl.LOCK_SH), *[(n, fcntl.LOCK_EX) for n in sorted(others)]]:
            handle = (root / name).open("a")
            handles.append(handle)
            try:
                fcntl.flock(handle, mode | fcntl.LOCK_NB)
            except BlockingIOError:
                raise _Held(f"다른 OMX 세션이 {name}을 잡고 있습니다") from None
        # The chosen arm's own lock is record_session's to take next (shared cell lock + its own); probing it here only
        # refuses a start while something else already holds it, and releases it again right away. Residual window
        # (accepted): another same-arm session may start between this probe and record_session's own lock; its exclusive
        # session-<arm>.lock makes a concurrent same-arm recording fail to start.
        with (root / f"session-{arm}.lock").open("a") as own:
            try:
                fcntl.flock(own, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise _Held(f"다른 OMX 세션이 session-{arm}.lock을 잡고 있습니다") from None
        check_proc_visible(mounts)
        if recorder_running(procs):
            raise _Held("record_session 또는 chunk_runner가 실행 중입니다")
        return handles, None
    except Exception as exc:  # no fcntl, unreadable root or /proc: cannot prove the cell is idle
        release(handles)
        return [], str(exc) if isinstance(exc, _Held) else f"다른 세션이 없는지 확인할 수 없습니다: {type(exc).__name__}"


def check_proc_visible(mounts=proc_mounts):
    """Raises _Held unless /proc shows every process (hidepid other than 0/off could hide a recorder); fail closed."""
    for line in mounts().splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1] == "/proc" and fields[2] == "proc":
            if re.search(r"(^|,)hidepid=(?!(0|off)(,|$))", fields[3]):
                raise _Held("/proc가 hidepid로 마운트되어 다른 세션 프로세스를 확인할 수 없습니다")
            return
    raise _Held("/proc 마운트 옵션을 확인할 수 없습니다")


def recorder_running(procs=proc_cmdlines):
    """True when a recorder/chunk runner is alive, or when that cannot be told (fail closed)."""
    try:
        return any(re.search(r"record_session\.py|chunk_runner", line) for line in procs())
    except Exception:
        return True


class _Held(Exception):
    pass


def release(handles):
    for handle in reversed(handles):
        try:
            handle.close()
        except OSError:
            pass


def write_snapshot(snap, files):
    """Write each (name, bytes) into a new private dir (0700) as exclusive 0600 files and check the bytes read back."""
    snap.mkdir(parents=True, mode=0o700)
    for name, data in files:
        fd = os.open(snap / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        if (snap / name).read_bytes() != data:
            raise ValueError("스냅샷 파일이 검증한 내용과 다릅니다")


def write_restore_list(path, units):
    """The units still to restore, atomically (temp + rename); an empty list removes the file."""
    if not units:
        return path.unlink(missing_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(units))
    os.replace(tmp, path)  # a crash never leaves a half-written list

