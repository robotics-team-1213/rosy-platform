"""Place confirmed cargo before an incident-bound home command can fold the arm."""
from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path


def _pose(row):
    return (isinstance(row, list) and len(row) >= 6
            and all(type(v) in (int, float) and math.isfinite(v) for v in row[:6]))


def _empty(status, closed):
    target = status.get("target")
    return (status.get("holding") is False and _pose(target)
            and not (target[5] <= closed + 1.0 and status["state"][5] > target[5] + 2.0))


def placement_due(context, config_file, cwd):
    import cell_params

    stopped = context.get("stopped_at")
    if type(stopped) not in (float, int) or not math.isfinite(stopped):
        return False
    config = json.loads(config_file.read_text(encoding="utf-8"))
    params = config.get("params_path")
    values = cell_params.load(cwd / Path(params).expanduser() if params else None)["values"]
    return time.time() - stopped >= cell_params.get(values, "runner.idle_park_s")


def bound_request_due(arm, incident_id):
    from cell_recovery_placement_context import load_context
    from omx_incident_auto import _auto_fold_config
    from omx_incident_fleet import incidents_dir

    try:
        context = load_context(incidents_dir(), arm, incident_id)
        if not context or not context.get("cargo"):
            return True  # USB holds with an empty gripper can be homed immediately.
        spec = json.loads(_auto_fold_config().read_text(encoding="utf-8"))[arm]
        cwd = Path(spec["cwd"]).expanduser()
        return placement_due(context, cwd / spec["config"], cwd)
    except (sqlite3.Error, KeyError, OSError, TypeError, ValueError):
        return False


def before_bound_home(args, cell, closed, kw, journal, directory, *, load_context, build_backend, place_nearest):
    """Return a refusal, verified placement, or None when already empty. Caller retains the session lock."""
    from cell_envelope import _state_current

    if journal.pending():
        return {"result": "held", "reason": "PLACEMENT_VERIFICATION_PENDING"}
    status = cell.act("state")
    if status.get("ok") is not True or not _pose(status.get("state")):
        return {"result": "held", "reason": "STATE_UNREADABLE"}
    context = load_context(directory, args.arm, args.expected_incident_id)
    if _empty(status, closed):
        if getattr(args, "commissioning", False):
            return {"result": "held", "reason": "PLACEMENT_TRIAL_REQUIRES_CARGO"}
        if context and context.get("cargo") and not journal.confirmed(args.expected_incident_id):
            return {"result": "held", "reason": "PLACEMENT_UNVERIFIED"}
        return None
    if status.get("holding") is not True or not _pose(status.get("target")):
        return {"result": "held", "reason": "PLACEMENT_REQUIRED_BEFORE_HOME"}
    if status.get("human_hold_latched") is not False:
        return {"result": "held", "reason": "LIVE_HOLD_LATCHED"}
    if args.stage != "full" or not _state_current(status, time.time()):
        return {"result": "held", "reason": "PLACEMENT_STATE_UNCONFIRMED"}
    if not args.safety_fence or args.expires_at is None or type(args.stop_generation) is not int:
        return {"result": "held", "reason": "PLACEMENT_FENCE_REQUIRED"}
    if not context or not isinstance(context.get("cargo"), dict) or not context["cargo"]:
        return {"result": "held", "reason": "PLACEMENT_CARGO_CONTEXT_UNKNOWN"}
    if not placement_due(context, args.config, Path.cwd()):
        return {"result": "held", "reason": "PLACEMENT_IDLE_INTERVAL_PENDING"}
    backend = build_backend(args, cell, {**kw, "placement_context": context["cargo"],
                                        "placement_commissioning": getattr(args, "commissioning", False)}, status)
    # An unexpected backend failure can follow a partial move; keep the corridor until its lease expires.
    if kw.get("moved_out") is not None:
        kw["moved_out"].append(True)
    result = place_nearest(backend, holding=True, journal=journal, incident_id=args.expected_incident_id)
    if result.get("result") != "placed":
        return result
    after = cell.act("state")
    if (journal.pending() or not _state_current(after, time.time()) or not _pose(after.get("state"))
            or after["operating_context"] != status["operating_context"] or after.get("human_hold_latched") is not False
            or not _empty(after, closed)):
        return {"result": "held", "reason": "POST_PLACEMENT_EMPTY_UNCONFIRMED", "placement": result}
    return result
