#!/usr/bin/env python3
"""Why an arm session did not start, as one JSON line, and whether the session wrapper may try again.

2026-11-26: 11 of 143 cell jobs ended in a bare "REFUSED: the arm session did not start" with no reason (home 9 times in a
row, 22:14-22:36). The wrapper calls this with what it saw; the last JSON line of the job log carries `reason`, `code`,
the lock holder and the motor comm code. Exit 10 means "retry" (this process already waited); anything else means refuse.

Safety states (motor fault, torque ON, hardware error, hold, incident) are never retried. Transient causes get a fixed
number of tries inside RETRY_WINDOW_S: a held lock (a finished job's wrapper keeps it ~100 s), an observer handoff that
lost a race, one more bus read after a comm timeout, one more camera read.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

RETRY_WINDOW_S = 150.0  # total wrapper time since the first attempt; a longer wait is a stuck holder, not a transient
RETRY = {  # code -> (extra tries, wait before the next try); lock_held may use every try inside the window
    "lock_held": (None, 5.0), "observer_handoff": (2, 3.0), "motor_comm": (1, 3.0), "camera": (1, 5.0),
}
SAFETY = re.compile(r"torque[^\n]{0,24}\b(on|enabled)\b|hardware[ _]error|overload|overheat|temperature|human[- ]hold|incident|"
                    r"\bfault\b|following error|contact|cap exceeded", re.I)
COMM = re.compile(r"comm[ _:=]*\(?\s*(-?\d{3,5})", re.I)
NOISE = re.compile(r"(null|none|false|\b0)\b\s*[,}]?\s*$", re.I)
EVIDENCE = re.compile(r"error|refus|fail|exception|timeout|timed out|comm|handoff|lock|camera|UVC|-71", re.I)


def tail(path, size: int = 8000) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - size))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def evidence(status_path, n0: int, log_path) -> list[str]:
    """Error lines only: failed chunk-status rows after the wrapper started, then the session log's tail."""
    rows = []
    try:
        for line in Path(status_path).read_text(encoding="utf-8", errors="replace").splitlines()[n0:]:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("ok") is False:
                rows.append(f"{row.get('command')}: {row.get('error') or row.get('fault')}")
    except OSError:
        pass
    lines = [ln.strip() for ln in tail(log_path).splitlines() if ln.strip()] if log_path else []
    return [ln[:240] for ln in [*rows, *(ln for ln in lines if EVIDENCE.search(ln) and not NOISE.search(ln))]][-6:]


def lock_holder(arm: str, lock_dir=None) -> dict | None:
    """Pid and command line of the process holding ~/rosy-omx/session-<arm>.lock (from /proc/locks), if any."""
    try:
        inode = os.stat((Path(lock_dir) if lock_dir else Path.home() / "rosy-omx") / f"session-{arm}.lock").st_ino
        for line in Path("/proc/locks").read_text().splitlines():
            words = line.split()
            if len(words) >= 6 and words[5].rsplit(":", 1)[-1] == str(inode):
                pid = int(words[4])
                cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
                return {"pid": pid, "cmd": cmd[:160]}
    except (OSError, ValueError):
        pass
    return None


HOLD_KEYS = ("fault", "hold", "human_hold_latched", "contact", "torque_enabled", "hardware_error")


def state_flags(*paths) -> list[str]:
    """Safety flags set in the files the session itself writes (live.json, motor-health snapshot), read directly: a log
    line may not mention them. Any key in HOLD_KEYS with a truthy value, at any depth, or a health status of fault."""
    found = []

    def walk(node, where):
        if isinstance(node, dict):
            for key, val in node.items():
                if key in HOLD_KEYS and val not in (None, False, 0, "", [], {}):
                    found.append(f"{where}:{key}")
                elif key == "status" and val == "fault":
                    found.append(f"{where}:status=fault")
                else:
                    walk(val, where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    for path in paths:
        try:
            walk(json.loads(Path(path).read_text(encoding="utf-8")), Path(path).name)
        except (OSError, ValueError, TypeError):
            continue
    return found


def classify(hint: str, lines: list[str], bg_alive: bool = False) -> tuple[str, int | None]:
    """(code, comm code). A safety state wins over every transient reading."""
    text = "\n".join(lines)
    if SAFETY.search(text):
        return "safety_state", None
    comm = COMM.search(text)
    if bg_alive:
        return "start_timeout", int(comm.group(1)) if comm else None
    if comm:
        return "motor_comm", int(comm.group(1))
    if hint == "lock_held":
        return "lock_held", None
    if re.search(r"handoff|observer", text, re.I):
        return "observer_handoff", None
    if re.search(r"camera|UVC|-71|frame", text, re.I):
        return "camera", None
    return hint or "unknown", None


def decide(code: str, attempt: int, elapsed_s: float) -> float | None:
    """Seconds to wait before another try, or None to refuse now."""
    policy = RETRY.get(code)
    if policy is None or elapsed_s >= RETRY_WINDOW_S:
        return None
    extra, wait = policy
    return wait if extra is None or attempt <= extra else None


def refusal(arm: str, hint: str, message: str, *, status=None, n0: int = 0, log=None, bg_alive: bool = False,
            attempt: int = 1, t0: float | None = None, now: float | None = None, lock_dir=None,
            state_files=()) -> tuple[dict, float | None]:
    now = time.time() if now is None else now
    lines = evidence(status, n0, log) if status and hint != "lock_held" else []  # a held lock says nothing about older status rows
    code, comm = classify(hint, lines, bg_alive)
    elapsed = round(now - t0, 1) if t0 else 0.0
    wait = decide(code, attempt, elapsed)
    if wait is not None and (flags := state_flags(*state_files)):  # never start another session on a held, faulted or torque-on arm
        code, wait = "safety_state", None
        lines = [f"session state file reports {', '.join(flags)}", *lines]
    row = {"result": "retry" if wait is not None else "refused", "stage": "session", "arm": arm, "code": code,
           "reason": f"{message} [{code}]" + (f" comm {comm}" if comm is not None else ""), "attempt": attempt,
           "elapsed_s": elapsed, "evidence": lines[-3:]}
    if comm is not None:
        row["comm"] = comm
    if code == "lock_held" or hint == "lock_held":
        row["lock_holder"] = lock_holder(arm, lock_dir)
    if wait is not None:
        row["retry_in_s"] = wait
    return row, wait


def main(argv=None, *, sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", required=True)
    ap.add_argument("--code", default="")
    ap.add_argument("--message", required=True)
    ap.add_argument("--status")
    ap.add_argument("--n0", type=int, default=0)
    ap.add_argument("--log")
    ap.add_argument("--bg-alive", default="0")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--t0", type=float)
    ap.add_argument("--state-file", action="append", default=[], help="live.json or motor-health snapshot to read before any retry")
    args = ap.parse_args(argv)
    row, wait = refusal(args.arm, args.code, args.message, status=args.status, n0=args.n0, log=args.log,
                        bg_alive=args.bg_alive == "1", attempt=args.attempt, t0=args.t0, state_files=args.state_file)
    print(json.dumps(row, default=str), flush=True)
    if wait is None:
        return 0
    sleep(wait)
    return 10


if __name__ == "__main__":
    sys.exit(main())
