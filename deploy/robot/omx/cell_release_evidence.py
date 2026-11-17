"""Measured release evidence for a placed box: observation only, never read by a carry decision.

Slices the runner's per-tick trace (ROSY_CHUNK_TRACE rows: "pwm" = motion.effort_pwm by motor, "present") for the
`run release_place` and `run lift_place` steps, using the trace_receipt byte ranges those steps carry, and reports
whether the gripper effort dropped after the jaws opened and whether the wrist/gripper then held still."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

EDGE = 5  # rows averaged at the start and end of the release chunk
SETTLE_ROWS, SETTLE_SPREAD = 10, 0.5  # last rows of the lift: wrist_flex and gripper present spread (LeRobot units)
GRIPPER, WRIST, WRIST_IDX, GRIPPER_IDX = "gripper", "wrist_flex", 3, 5


def _pwm(row, motor):
    value = (row.get("pwm") or {}).get(motor)
    return abs(float(value)) if isinstance(value, (int, float)) else None


def _mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def release_evidence(release_rows, lift_rows=()):
    """Pure: {"gripper_pwm_before", "gripper_pwm_after", "wrist_pwm_peak_after", "settled", "basis"}."""
    try:
        release = [r for r in release_rows if isinstance(r, dict)]
        lift = [r for r in lift_rows if isinstance(r, dict)]
        if len(release) < 2 * EDGE:
            return {"basis": "unavailable"}
        after_rows = release[-EDGE:] + lift
        peak = max((v for v in (_pwm(r, WRIST) for r in after_rows) if v is not None), default=None)
        tail = [r["present"] for r in (lift or release)[-SETTLE_ROWS:]
                if isinstance(r.get("present"), list) and len(r["present"]) > GRIPPER_IDX]
        settled = None
        if len(tail) >= SETTLE_ROWS:
            settled = all(max(p[i] for p in tail) - min(p[i] for p in tail) < SETTLE_SPREAD
                          for i in (WRIST_IDX, GRIPPER_IDX))
        before, after = _mean(_pwm(r, GRIPPER) for r in release[:EDGE]), _mean(_pwm(r, GRIPPER) for r in release[-EDGE:])
        if before is None or after is None:
            return {"basis": "unavailable"}
        return {"gripper_pwm_before": before, "gripper_pwm_after": after, "wrist_pwm_peak_after": peak,
                "settled": settled, "basis": f"trace pwm ticks (edge {EDGE}, settle {SETTLE_ROWS} rows < {SETTLE_SPREAD})"}
    except (TypeError, ValueError, KeyError):
        return {"basis": "unavailable"}


def _rows(receipt, root):
    """Trace rows a step's receipt covers, or None (missing, wrong hash, unreadable)."""
    if not isinstance(receipt, dict) or receipt.get("status") != "ok" or root is None:
        return None
    try:
        path = (Path(root).expanduser().resolve().parent / receipt["source"]).resolve()
        if path.parent != Path(root).expanduser().resolve().parent:
            return None
        with path.open("rb") as stream:
            stream.seek(receipt["start"])
            data = stream.read(receipt["end"] - receipt["start"])
        if hashlib.sha256(data).hexdigest() != receipt.get("sha256"):
            return None
        return [json.loads(line) for line in data.decode().splitlines() if line.strip()]
    except (OSError, KeyError, TypeError, ValueError):
        return None


def from_steps(steps, io):
    """Release evidence for one carry's `steps` (cell_transfer), reading the owner trace under `io`'s parent."""
    try:
        by = {s.get("command"): s.get("trace_receipt") for s in steps if isinstance(s, dict)}
        release = _rows(by.get("run release_place"), io)
        if release is None:
            return {"basis": "unavailable"}
        return release_evidence(release, _rows(by.get("run lift_place"), io) or [])
    except Exception:  # noqa: BLE001  evidence must never change a carry
        return {"basis": "unavailable"}
