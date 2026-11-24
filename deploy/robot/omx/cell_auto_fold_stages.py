#!/usr/bin/env python3
"""CLI, fail-closed safety-fence, and folded-at-home helpers for `cell_auto_fold.py` (D-1048)."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable


def _safety_fence_error(args) -> str | None:
    if args.expires_at is not None and time.time() > float(args.expires_at):
        return "SAFE_HOME_EXPIRED"
    if args.safety_fence is None and args.stop_generation is None:
        return None
    fence_path = Path(args.safety_fence) if (args.safety_fence and args.safety_fence.strip()) else None
    if fence_path is None or not fence_path.is_file():
        return "SAFETY_FENCE_MISSING"
    try:
        fence = json.loads(fence_path.read_text(encoding="utf-8"))
        upd = fence.get("updated_at") if isinstance(fence, dict) else None
        sg = fence.get("stop_generation") if isinstance(fence, dict) else None
        if not isinstance(fence, dict) or type(fence.get("human_hold")) is not bool:
            return "SAFETY_FENCE_UNREADABLE"
        if fence["human_hold"]:
            return "HUMAN_HOLD_ACTIVE"
        if isinstance(upd, bool) or not isinstance(upd, (int, float)) or not math.isfinite(upd) or not (-5.0 <= (time.time() - upd) <= 15.0):
            return "SAFETY_FENCE_STALE"
        if type(sg) is not int or args.stop_generation is None or sg != args.stop_generation:
            return "STOP_GENERATION_PREEMPTED"
    except Exception:
        return "SAFETY_FENCE_UNREADABLE"
    return None


def resolve_folded_at_home(
    cell, state: list, *, stage: str, latched: dict, is_holding: bool,
    steps: list, note_fn, hold_fn, ensure_unlatch_fn, schema: str,
) -> dict | None:
    """Return outcome when arm is already folded at home, or None to continue into release-and-lift recovery."""
    if stage == "park_only" and is_holding:
        return hold_fn("STILL_HOLDING_BEFORE_PARK", is_holding=True)
    if stage == "release_and_lift":
        if is_holding:
            return None
        held = cell.act("human-hold")
        if held.get("ok") is not True:
            return {"schema": schema, "result": "held", "reason": "HOLD_AFTER_LIFT_FAILED",
                    "candidate": "release_and_lift", "hold_ok": held.get("ok"), "steps": steps}
        return {"schema": schema, "result": "risen_for_visual_verify", "candidate": "release_and_lift",
                "state": state, "hold_ok": True, "steps": steps, "corridor": None}
    if latched["active"]:
        if is_holding:
            return hold_fn("HOLDING_AT_HOME", is_holding=True)
        ok_u, err_u = ensure_unlatch_fn(cell, latched, note_fn)
        if not ok_u:
            return hold_fn("UNLATCH_REFUSED", error=err_u)
    elif is_holding:
        return hold_fn("HOLDING_AT_HOME", is_holding=True)
    return {"schema": schema, "result": "folded", "candidate": "already_home", "state": state, "steps": steps,
            "corridor": None, **({"unlatched_live_hold": True} if latched["started"] else {})}


def write_req_result(incidents_dir: Path, request_id: str | None, arm: str, stage: str, out: dict[str, Any]) -> None:
    if not request_id:
        return
    res = str(out.get("result") or "")
    outcome = ("completed" if res in ("folded", "cleared", "parked_for_visual_verify")
               else "risen_for_visual_verify" if res == "risen_for_visual_verify"
               else "held_guard_tripped" if res == "held"
               else "skipped" if res == "skipped"
               else "failed")
    payload = {"request_id": request_id, "arm": arm, "stage": stage, "outcome": outcome,
               "detail": out.get("why"), "result": out}
    target = incidents_dir / f"auto-fold-req-{request_id}.result.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
    os.replace(tmp, target)


def run_cli_main(argv: list[str] | None, *, launch_fn: Callable[..., dict], recover_fn: Callable[..., dict],
                 candidate_names_fn: Callable[[], list[str]], choice_key: str, schema: str) -> int:
    del candidate_names_fn, choice_key
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list[:1] == ["launch"]:
        lp = argparse.ArgumentParser(prog="cell_auto_fold.py launch")
        lp.add_argument("--arm", required=True)
        lp.add_argument("--config-file", type=Path, required=True)
        lp.add_argument("--stage", choices=("full", "release_and_lift", "park_only"), default="full")
        lp.add_argument("--request-id", default=None)
        lp.add_argument("--expires-at", type=float, default=None)
        lp.add_argument("--stop-generation", type=int, default=None)
        lp.add_argument("--safety-fence", default=None)
        opts = lp.parse_args(args_list[1:])
        print(json.dumps(launch_fn(opts.arm, opts.config_file, stage=opts.stage,
                                   request_id=opts.request_id, expires_at=opts.expires_at,
                                   stop_generation=opts.stop_generation, safety_fence=opts.safety_fence), default=str))
        return 0

    from chunk_runner_recover import run_fold_session_cli

    ap = argparse.ArgumentParser(description="Fold a held arm home on its own (D-1048).")
    ap.add_argument("--arm", required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--library", type=Path, required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--roi", nargs=4, type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stage", choices=("full", "release_and_lift", "park_only"), default="full")
    ap.add_argument("--expires-at", type=float, default=None)
    ap.add_argument("--stop-generation", type=int, default=None)
    ap.add_argument("--safety-fence", default=None)
    ap.add_argument("--supervised", action="store_true")
    ap.add_argument("--unlatch-hold", action="store_true")
    ap.add_argument("--vlm-url")
    ap.add_argument("--vlm-model", default="qwen3-vl:8b-instruct")
    ap.add_argument("--vlm-provider", default="ollama")
    ap.add_argument("--vlm-config", type=Path)
    ap.add_argument("--vlm-timeout", type=float, default=25.0)
    args = ap.parse_args(args_list)
    if not args.supervised and not os.environ.get("ROSY_RECOVERY_INCIDENT"):
        ap.error("ROSY_RECOVERY_INCIDENT is required: this tool only folds an arm a held incident names")

    def _guarded_recover(cell, home, closed, **kw):
        fence_bad = _safety_fence_error(args)
        if fence_bad is not None:
            can_stop = bool(args.supervised and not args.unlatch_hold and not kw.get("moved_out") and not kw.get("latched_out"))
            stopped = cell.act("stop now") if can_stop else {}
            if stopped.get("ok") is True:
                return {"schema": schema, "result": "held", "reason": fence_bad, "hold_ok": None,
                        "ended": "stop_now", "unmoved": True, "steps": []}
            return {"schema": schema, "result": "held", "reason": fence_bad,
                    "hold_ok": cell.act("human-hold").get("ok"), "steps": []}
        return recover_fn(cell, home, closed, stage=args.stage, **kw)

    rc = run_fold_session_cli(args, _guarded_recover, schema)
    if rc == 3 and args.out.is_file():
        try:
            if json.loads(args.out.read_text(encoding="utf-8")).get("result") == "risen_for_visual_verify":
                return 0
        except Exception:
            pass
    return rc
