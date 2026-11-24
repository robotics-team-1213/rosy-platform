"""Runner PID / live.json stall detection and status-log draining for FifoCell."""
from __future__ import annotations

import json
import os
import time


def runner_liveness(live, *, last_t, last_mono, stall_timeout_s, now_mono, finite_stamp, kill=os.kill):
    if not isinstance(live, dict):
        return None, last_t, last_mono
    pid = live.get("pid")
    if type(pid) is int and pid > 0:
        try:
            kill(pid, 0)
        except ProcessLookupError:
            return ("runner_dead", f"chunk_runner pid {pid} exited while awaiting status"), last_t, last_mono
        except PermissionError:
            pass
    lt = finite_stamp(live.get("t"))
    if lt is not None:
        if last_t is None or lt > last_t:
            last_t, last_mono = lt, now_mono
        elif stall_timeout_s > 0 and last_mono is not None and now_mono - last_mono > stall_timeout_s:
            return ("runner_stalled", f"chunk_runner live.json stalled for >{stall_timeout_s:.1f}s"), last_t, last_mono
    return None, last_t, last_mono


def cache_state_row(cell, row):
    if (isinstance(row, dict) and row.get("ok") and not row.get("fault")
            and row.get("operating_context") and row.get("library_sha256")):
        cell._cached_state = row
        cell._cached_state_mono = time.monotonic()


def status_row_outcome(row, *, command, expected, verb, recovery, is_hold, hold_req, sent_at, finite_stamp, now=None):
    """Classify one parsed status row for FIFO drain or Unix socket wait ('hold', 'match', or None)."""
    if not isinstance(row, dict):
        return None
    if is_hold:
        if row.get("command") != "human-hold":
            return None
        rt = finite_stamp(row.get("t"))
        ceiling = (time.time() if now is None else now) + 1.0
        if rt is None or rt > ceiling or (rt < sent_at if hold_req else rt <= sent_at):
            return None
        return "hold" if row.get("hold_req") == hold_req else None
    matches = (command, expected, "run " + (verb if recovery else expected))
    if row.get("command") in matches or (not recovery and row.get("fault")):
        return "match"
    return None


def drain_status(cell, status_path, start, command, expected, verb, recovery, is_hold, hold_req, sent_at, finite_stamp):
    matched_hold = None
    try:
        if status_path.exists():
            with status_path.open("rb") as stream:
                stream.seek(start)
                while line := stream.readline():
                    if not line.endswith(b"\n"):
                        break
                    start = stream.tell()
                    try:
                        row = json.loads(line.decode("utf-8"))
                    except (ValueError, RecursionError):
                        if not is_hold:
                            raise
                        continue
                    outcome = status_row_outcome(
                        row, command=command, expected=expected, verb=verb, recovery=recovery,
                        is_hold=is_hold, hold_req=hold_req, sent_at=sent_at, finite_stamp=finite_stamp,
                    )
                    if outcome == "hold":
                        matched_hold = row
                    elif outcome == "match":
                        cache_state_row(cell, row)
                        return row, start
    except (OSError, ValueError, RecursionError):
        if not is_hold:
            raise
    return matched_hold, start
