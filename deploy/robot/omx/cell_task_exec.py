"""Execution, TLS, hold-gating, and error diagnostics helpers for `cell_task_worker.py`."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen


def make_ca_urlopen(ca_file: str | Path | None = None):
    """Return a `urlopen`-compatible callable pinned to `ca_file` when provided."""
    if not ca_file:
        return urlopen
    ctx = ssl.create_default_context(cafile=str(Path(ca_file).expanduser()))

    def _open(req, **kwargs):
        return urlopen(req, context=ctx, **kwargs)

    return _open


def resolve_task_arm(task: dict[str, Any]) -> str:
    """Resolve the target OMX arm id for a queued Fleet cell task."""
    arm = str(task.get("arm_id") or "").strip()
    if arm:
        return arm
    return "arm_s" if task.get("cell_id") == "cell_s" else "arm_b"


def check_arm_hold(arm_id: str) -> dict[str, Any]:
    """Check local and synced Fleet incident holds for `arm_id`; fails closed to local hold."""
    import omx_incident

    try:
        st = omx_incident.status(arm_id)
        held = bool(st.get("local_held") or st.get("fleet_held") or st.get("held"))
        return {"held": held, "reason": st.get("local_reason") or st.get("fleet_reason")}
    except Exception:
        lf = omx_incident.hold_file(arm_id)
        return {"held": lf is not None, "reason": "local_hold_present" if lf is not None else None}


def classify_poll_error(exc: Exception, token_file: str | Path) -> dict[str, Any]:
    """Return structured poll error payload without leaking token bytes."""
    if isinstance(exc, HTTPError) and exc.code == 401:
        p = Path(token_file).expanduser()
        length = len(p.read_text(encoding="utf-8").strip()) if p.is_file() else 0
        return {
            "event": "poll_auth_error",
            "status": 401,
            "token_file": str(p),
            "token_chars": length,
            "hint": "Fleet rejected bearer token (post-rosy_account cutover expects valid 64-hex service/operator credential)",
            "backoff_s": 30.0,
        }
    return {"event": "poll_error", "error": repr(exc), "backoff_s": None}


# D-1057. Same tolerance as chunk_runner_guards.SETTLE_TOL, which the transfer gate uses to accept a park as home.
FOLD_TOLERANCE = 3.0
ZONE_BASIS = "predefined_side_and_top_target_zones"


def last_json_object(text: str) -> dict[str, Any]:
    """The JSON object that ends the output. cell_auto_pick prints it indented over many lines after free-form log lines,
    so take the earliest `{` from which one object parses through to the end of the text."""
    decoder, start = json.JSONDecoder(), text.find("{")
    while start != -1:
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        else:
            if isinstance(value, dict) and not text[end:].strip():
                return value
        start = text.find("{", start + 1)
    return {}


def _last_attempt(parsed: dict[str, Any]) -> dict[str, Any]:
    attempts = parsed.get("attempts")
    last = attempts[-1] if isinstance(attempts, list) and attempts else None
    return last if isinstance(last, dict) else {}


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


def _arm_run_spec(arm_id: str, prep_dir: Path) -> tuple[Path, Path, Path, tuple[int, int, int, int], str]:
    specs = {
        "arm_b": ("with-session-arm-b-par.sh", "cell-arm-b-stack.json", "object-catalog-orange.json", (10, 340, 230, 478), "temp_plate_b"),
        "arm_a": ("with-session-arm-a-par.sh", "cell-arm-a-stack.json", "object-catalog-orange.json", (395, 360, 625, 478), "temp_plate_a"),
        "arm_s": ("with-session-arm-s-live.sh", "cell-auto-arm-s-live.json", "catalog-board-live-1113.json", (90, 150, 560, 450), "pinky"),
    }
    if arm_id not in specs:
        raise ValueError(f"unsupported arm_id for guarded pick: {arm_id!r}")
    wrapper, cfg, cat, roi, default_src = specs[arm_id]
    return prep_dir / wrapper, prep_dir / cfg, prep_dir / cat, roi, default_src


def execute_guarded_cell_task(handoff: dict[str, Any], *, prep_dir: Path) -> dict[str, Any]:
    """Execute one Fleet cell handoff via the arm's session wrapper and `cell_auto_pick.py`."""
    arm_id = resolve_task_arm(handoff)
    hold = check_arm_hold(arm_id)
    if hold.get("held"):
        return {"arm": arm_id, "error": f"ARM_INCIDENT_HELD:{hold.get('reason')}",
                "stop_event": {"command": "stop", "ok": False, "folded": False}}
    wrapper, cfg, cat, default_roi, default_src = _arm_run_spec(arm_id, prep_dir)
    if not wrapper.is_file() or not cfg.is_file():
        return {"arm": arm_id, "error": "CELL_CONFIG_OR_WRAPPER_MISSING",
                "stop_event": {"command": "stop", "ok": False, "folded": False}}
    cfg_data = json.loads(cfg.read_text(encoding="utf-8"))
    src = str(handoff.get("src_site") or default_src)
    dst = str(handoff.get("dst_site") or ("pallet-l0" if arm_id != "arm_s" else "belt"))
    src_site = src.rsplit("-l", 1)[0]
    roi = (cfg_data.get("sites") or {}).get(src_site, {}).get("auto_roi") or default_roi
    omx_dir = Path(__file__).resolve().parent
    cmd = [
        str(wrapper),
        sys.executable,
        str(omx_dir / "cell_auto_pick.py"),
        "--config", str(cfg),
        "--catalog", str(cat if cat.is_file() else omx_dir / "object-catalog.example.json"),
        "--roi", *(str(int(v)) for v in roi),
        "--from", src,
        "--dest", dst,
        "--commissioning",
        "--person-at-switch",
        "--task-id", str(handoff.get("task_id") or ""),
        "--handoff-lease-id", str(handoff.get("handoff_lease_id") or ""),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    parsed = last_json_object(proc.stdout)
    # The wall clock at the end of the run bounds when the readbacks below existed (the runner's own clock is monotonic).
    measured_at = time.time()
    attempt = _last_attempt(parsed)
    placement = attempt.get("verify") if isinstance(attempt.get("verify"), dict) else {}
    placed = (proc.returncode == 0 and parsed.get("result") == "placed"
              and placement.get("verified") is True and placement.get("inside") is True)
    fold = fold_readback(attempt, plan_home(cfg_data))
    # D-1057: cell_auto_pick records only the top-frame placement check (`verify`, basis "map"). The side/top zone
    # measurement (cell_area_zones.verify_stack_outcome*) is used only if the attempt carries it as `zone_verification`;
    # nothing in cell_auto_pick emits that today, so without it the fields below stay unverified and Fleet refuses.
    zone = attempt.get("zone_verification") if isinstance(attempt.get("zone_verification"), dict) else None
    # The measured slot and tier must be the task's own: the destination site and the handoff tier.
    target = (zone or {}).get("target") if isinstance((zone or {}).get("target"), dict) else {}
    htier = handoff.get("tier")
    bound = (target.get("site") == dst and type(htier) is int and target.get("tier") == htier
             and type(target.get("col")) is int and type(target.get("row")) is int)
    zone_ok = bool(zone and zone.get("verified") is True and zone.get("basis") == ZONE_BASIS and bound)
    tier = handoff.get("tier")
    dst_area = dst.rsplit("-l", 1)[0]
    verification = ({**zone, "placement": placement} if zone is not None else
                    {"verified": False, "basis": placement.get("basis") or "unverified: no placement record",
                     "placement": placement,
                     "z_gate": {"verdict": "UNKNOWN", "reason": "no zone measurement from cell_auto_pick"}})
    stage_result = {
        "handoff_lease_id": handoff.get("handoff_lease_id"),
        "directive_id": handoff.get("task_id"),
        "arm_id": arm_id,
        "task_verified": placed and zone_ok,
        "place": {"area": dst_area, **({"tier": tier} if isinstance(tier, int) else {})},
        "verification": verification,
        "raw": parsed,
    }
    return {
        "arm": arm_id,
        "events_count": len(parsed.get("attempts") or []),
        "measured_at": measured_at,
        "stage_result": stage_result,
        "stop_event": {"command": "stop", "ok": fold["folded"], "folded": fold["folded"], "readback": fold,
                       **({"state": fold["state"]} if fold["state"] else {})},  # Fleet reads stop_event.state as joints
        **({"error": parsed.get("result") or f"exit_{proc.returncode}"} if not placed else
           {} if fold["folded"] else {"error": "FOLD_READBACK_MISSING"}),
    }
