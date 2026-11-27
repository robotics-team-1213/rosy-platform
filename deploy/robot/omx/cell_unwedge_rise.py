"""Let go and rise: the arm stopped low with a box in its jaws (moved out of cell_unwedge to keep it under the line limit)."""
from __future__ import annotations

import time

from cell_unwedge import CLEAR, JAW_STEP, JAW_TOL, LAG_STOP, RELEASE_OPEN, SETTLE_S, STEP, lags  # noqa: E402


def release_and_rise(cell, *, sleep=time.sleep) -> dict:
    """An arm stopped low with a box in its jaws: open back to about the opening it came down with, then rise straight up with
    the jaws round the box. A pull here would drag the box, so a blocked rise stops and asks. The caller folds home; a park
    closes the jaws first and refuses while the box is in them (2026-11-07, arm_b: this order, by hand, peak lag 0.77)."""
    status = cell.act("state")
    if not status.get("ok"):
        return {"result": "stopped", "error": status.get("error")}
    target, want = status["target"][5], status["state"][5] + RELEASE_OPEN
    while want - target > 0.05:
        step = round(min(JAW_STEP, want - target), 2)
        status = cell.act(f"jog gripper.pos {step}")
        if not status.get("ok"):
            return {"result": "stopped", "at": "open", "error": status.get("error")}
        target += step
        sleep(SETTLE_S)
    status = cell.act("state")
    if not status.get("ok") or status["state"][5] < want - JAW_TOL:
        return {"result": "stuck", "at": "open", "jaws": status.get("state", [None] * 6)[5]}
    for step in range(int(CLEAR / STEP)):
        status = cell.act(f"jog shoulder_lift.pos {-STEP}")
        if not status.get("ok"):
            return {"result": "stopped", "at": step, "error": status.get("error")}
        sleep(SETTLE_S)
        status = cell.act("state")
        if not status.get("ok"):
            return {"result": "stopped", "at": step, "error": status.get("error")}
        if max(lags(status)) > LAG_STOP:  # back down the way it rose, onto the support it started on (2026-11-27 arm_a ID12 overload)
            back = [(cell.act(f"jog shoulder_lift.pos {STEP}"), sleep(SETTLE_S))[0] for _ in range(step + 1)]  # one settle per jog
            return {"result": "stuck", "at": step, "lags": lags(status), "returned": all(b.get("ok") for b in back)}
    return {"result": "risen", "state": status["state"]}
