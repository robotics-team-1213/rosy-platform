#!/usr/bin/env python3
"""Folded but off home after a recovery park: the reviewed home stage in the same session, then measured again.

2026-11-27 arm_s: recover_hold parked settled at elbow_flex 54.9 (home 50.0, SETTLE_TOL 3.0) and re-latched the human
hold (PARK_NOT_HOME) twice; the home job could not start while that hold kept the session. User: match home first, in
the pipeline. Only an arm inside the coarse fold (REST_TOL) is rehomed, through cell_unwedge.return_home's own guards
(empty, folded, joint window); the fold is declared only when the new state is within SETTLE_TOL. No tolerance changes.
"""
from __future__ import annotations

import math
from typing import Callable


def rehomed(cell, rehome: Callable[[object], dict | None] | None, at, home, *, settle_tol: float, rest_tol: float,
            note: Callable[[dict], None]) -> list | None:
    """The settled state after a guarded rehome when the park left the arm folded but off home, else None."""
    if rehome is None or not _close(at, home, rest_tol) or _close(at, home, settle_tol):
        return None
    try:
        receipt = rehome(cell) or {"result": "home"}  # the cell recover drives (fenced), never a side channel
    except Exception as exc:  # noqa: BLE001 - a failed rehome falls back to the existing hold
        receipt = {"result": "stopped", "error": repr(exc)}
    # a failed return_home may itself send "stop now" (within REST_TOL) or human-hold: keep that ack as the evidence
    note({"step": "rehome", "result": receipt.get("result"), "error": receipt.get("error"), "stop": receipt.get("stop")})
    if receipt.get("result") != "home":
        return None
    status = cell.act("state")
    state = status.get("state") if isinstance(status, dict) and status.get("ok") is True else None
    return list(state[:6]) if _close(state, home, settle_tol) else None


def _close(state, home, tol: float) -> bool:
    return (isinstance(state, list) and len(state) >= 6
            and all(type(v) in (int, float) and math.isfinite(v) for v in state[:6])
            and all(abs(a - b) <= tol for a, b in zip(state[:5], home[:5])))
