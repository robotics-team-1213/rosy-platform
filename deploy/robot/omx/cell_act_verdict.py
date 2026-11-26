"""One verdict for a finished ACT policy drive: task_verified (cell_task_act_run) and the Pinky depart (cell_job_depart) both use it.

A drive result counts only when it exited clean with a success result, the arm folded again (its own park reply, the park
readback within tolerance of home, AND the measured live fold), the source count fell by exactly one (`took_one`) and the
destination zone was measured as this task's own slot and tier (`zone_acceptance`, D-1057). No second copy of this rule.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

from cell_policy_entry import park_ack_ok  # not cell_policy_timing: the job API has no omx_adapter on its path
from cell_presence import zone_acceptance

SUCCESS_RESULTS = ("released", "chunks_done")
FOLD_TOLERANCE = 3.0


def fold_readback(attempt: dict[str, Any], home: Any) -> dict[str, Any]:
    """Measured fold: the final transfer step is a settled park whose joint readback is within FOLD_TOLERANCE of home.

    The readback comes from the owner's park step (`state`, `settled`, `ok`), never from the placement result.
    `t` is the runner's monotonic clock, so it is carried as-is and not used as a wall time.
    """
    steps = (attempt.get("transfer") or {}).get("steps") if isinstance(attempt.get("transfer"), dict) else None
    park = steps[-1] if isinstance(steps, list) and steps and isinstance(steps[-1], dict) else {}
    state = park.get("state")
    # Body joints only (the first five), as cell_recovery.at_home does; the jaw is the sixth and does not count.
    numbers = (isinstance(state, list) and isinstance(home, list) and len(state) >= 5 and len(home) >= 5
               and all(type(v) in (int, float) and math.isfinite(v) for v in state[:5] + home[:5]))
    folded = bool(park.get("command") == "park" and park.get("ok") is True and park.get("settled") is True
                  and not park.get("fault") and numbers
                  and all(abs(p - h) <= FOLD_TOLERANCE for p, h in zip(state[:5], home[:5])))
    return {"folded": folded, "command": park.get("command"), "state": state if numbers else None,
            "home": home if numbers else None, "tolerance": FOLD_TOLERANCE, "runner_t": park.get("t")}


def plan_home(cfg_data: dict[str, Any]) -> Any:
    """The fold-home pose the runtime uses: `home` of the grasp plan file named by the config's `plan_path`.

    `cell_auto_setup.load_config` loads that file into `config["plan"]`; the config JSON itself never carries it.
    None when the file is unreadable or has no `home` (then nothing counts as folded).
    """
    try:
        plan = json.loads(Path(str(cfg_data.get("plan_path") or "")).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return plan.get("home") if isinstance(plan, dict) else None


FOLD_FRESH_S = 60.0  # the measured fold must come from this session's last park, not an old status line


def measured_fold(arm_id: str, prep_dir: Path, now: float | None = None) -> dict[str, Any]:
    """The arm's last runner state from chunk-status (the telemetry reader): folded only when that state says so and is
    fresh. 2026-11-19 panel: `folded` used to copy `placed`, so a Pinky could be released with the arm over its bed."""
    import time as _time

    from cell_camera_telemetry_sync import _collect_live_arm_states

    live = _collect_live_arm_states(prep_dir).get(arm_id) or {}
    now = _time.time() if now is None else now
    fresh = isinstance(live.get("updated_at"), (int, float)) and now - live["updated_at"] <= FOLD_FRESH_S
    return {"folded": bool(live.get("folded")) and fresh, "state": live.get("joints_deg"), "fresh": fresh}


def act_verdict(parsed: dict[str, Any], returncode: int | None, handoff: dict[str, Any], dst: str, *,
                fold_readback_fn: Callable, home: Any, live_fold: dict[str, Any]) -> dict[str, Any]:
    raw_park = parsed.get("park") if isinstance(parsed.get("park"), dict) else {}
    park_valid = park_ack_ok(raw_park, require_command=True)
    park_row = {**raw_park, "command": "park"} if park_valid else dict(raw_park)
    fold = fold_readback_fn({"transfer": {"steps": [park_row]}}, home)
    folded = bool(parsed.get("parked") is True and park_valid and fold["folded"] and live_fold["folded"])
    took_one = parsed.get("took_one") is True
    zone = parsed.get("zone_verification") if isinstance(parsed.get("zone_verification"), dict) else None
    zone_ok = zone_acceptance(zone, handoff, dst)
    verified = bool(returncode == 0 and parsed.get("result") in SUCCESS_RESULTS and folded and took_one and zone_ok)
    return {"verified": verified, "folded": folded, "took_one": took_one, "zone": zone, "zone_ok": zone_ok,
            "fold": fold, "live_fold": live_fold}


def unverified_reason(v: dict[str, Any]) -> str | None:
    """Why a verdict is not verified (None when it is): the missing measured fold or zone acceptance is named."""
    if v["verified"]:
        return None
    if not v["live_fold"].get("folded"):
        return "measured fold not confirmed (live fold missing, stale or not folded)"
    if not v["folded"]:
        return "arm fold (parked) not confirmed"
    if not v["zone_ok"]:
        return "zone_acceptance not met (destination zone not measured as this task's slot and tier)"
    return "took_one not confirmed" if not v["took_one"] else "drive result is not a verified success"
