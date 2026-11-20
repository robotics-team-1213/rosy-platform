#!/usr/bin/env python3
"""Deliver SIGINT/SIGTERM/SIGHUP/SIGUSR2 to the main thread only (Linux), so blocking them there blocks the process.

pthread_sigmask acts on the calling thread, and the kernel hands a process signal to any thread that does not block
it. chunk_runner_interrupt.gated_close blocks these signals in the main thread from the gate's verdict through the
torque OFF; that holds for the whole process only if no other thread accepts them. chunk_runner.py, run as a script,
calls `route()` before any import that can start threads (numpy/BLAS, lerobot, serial): the main thread blocks them, so
threads created meanwhile inherit the blocked mask, and threading.Thread.start keeps doing so for every later Python
thread. `unblock_main()` then lets only the main thread receive them. `unrouted_threads()` reads /proc/self/task to
name any thread (a native one started outside Thread.start) that still accepts one of them. Stdlib only, no effect
where pthread_sigmask is missing (Windows test hosts).
"""
from __future__ import annotations

from pathlib import Path
import signal
import sys
import threading

ROUTED = tuple(getattr(signal, n) for n in ("SIGINT", "SIGTERM", "SIGHUP", "SIGUSR2") if hasattr(signal, n))
_MASK = getattr(signal, "pthread_sigmask", None)
_ORIGINAL_START = threading.Thread.start


def _start_blocked(self, *args, **kwargs):
    """A new thread inherits its creator's mask at pthread_create: block for that moment, then restore."""
    previous = _MASK(signal.SIG_BLOCK, ROUTED)
    try:
        return _ORIGINAL_START(self, *args, **kwargs)
    finally:
        _MASK(signal.SIG_SETMASK, previous)


def route() -> list:
    """Block ROUTED in this (main) thread and make Thread.start create blocked threads. Returns the names of threads
    that already existed (they may accept the signals: warned on stderr)."""
    if _MASK is None:
        return []
    others = [t.name for t in threading.enumerate() if t is not threading.main_thread()]
    if others:
        print(f"main_thread_signals: threads started before routing may take SIGTERM: {others}", file=sys.stderr,
              flush=True)
    _MASK(signal.SIG_BLOCK, ROUTED)
    threading.Thread.start = _start_blocked
    return others


def unblock_main() -> None:
    if _MASK is not None:
        _MASK(signal.SIG_UNBLOCK, ROUTED)


def unrouted_threads() -> list:
    """Thread ids (other than the main thread) whose SigBlk lacks one of ROUTED; [] where /proc is missing."""
    tasks, main, out = Path("/proc/self/task"), str(threading.main_thread().native_id), []
    if _MASK is None or not tasks.is_dir():
        return out
    want = sum(1 << (int(s) - 1) for s in ROUTED)
    for task in tasks.iterdir():
        if task.name == main:
            continue
        try:
            blocked = next(int(line.split()[1], 16) for line in (task / "status").read_text().splitlines()
                           if line.startswith("SigBlk:"))
        except (OSError, StopIteration, ValueError):
            continue  # the thread ended meanwhile
        if blocked & want != want:
            out.append(int(task.name))
    return out
