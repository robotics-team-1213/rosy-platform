#!/usr/bin/env python3
"""CLI & atomic request-result helpers for `cell_auto_fold.py` (D-1048)."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable


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

    import cell_choices
    import cell_corridor
    import cell_objects
    import cell_params as prm
    import cell_pipeline as cp
    import cell_pivot
    import cell_place_fit
    import cell_space
    import cell_unwedge
    from cell_observe import predicted_pixel
    from omx_adapter.chunk_library import NAMES, park_path

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
    args = ap.parse_args(args_list)
    if not args.supervised and not os.environ.get("ROSY_RECOVERY_INCIDENT"):
        ap.error("ROSY_RECOVERY_INCIDENT is required: this tool only folds an arm a held incident names")
    arm, cell, space, home, choices_path, moved_out = args.arm, None, None, [], None, []
    try:
        config = cell_place_fit.with_tiers(json.loads(args.config.read_text(encoding="utf-8")))[0]
        params = config["params"] = prm.load(config.get("params_path"))["values"]
        calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text())
        library = json.loads(args.library.read_text())
        home = library["chunks"]["home"][-1]
        closed = float(library["gripper_closed"])
        transit = {NAMES.index(k): float(v) for k, v in library.get("transit", {}).items()} or None
        site = config["sites"][args.site]
        cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
        space = cell_space.Space(Path(config.get("space_dir", "~/rosy-omx/space")).expanduser())
        to_px = lambda p: predicted_pixel(config, calibration, args.site, p)  # noqa: E731
        booked = {}
        choices_path = Path(config.get("work_dir") or ".") / f"auto-fold-choices-{arm}.json"
        choices = cell_choices.Choices(choices_path)
        for name in candidate_names_fn():
            choices.offer(choice_key, name, "D-1048")
        choices.save()
        park_speed = library.get("transit_speed", 0.85)
        plan = lambda s: park_path(list(s), home, closed, library["fps"], transit, park_speed)  # noqa: E731
        low = lambda s: cell_pivot.joints_tcp(s)[2] < prm.get(params, "corridor.clear_z_m", cell_corridor.CLEAR_Z_M)  # noqa: E731

        def look(frames):
            img = cell.frame("top")
            mask = cell_objects.foreground(img, args.roi, params=params, surface_px=site.get("surface_px"),
                                           surface_lab=site.get("surface_lab"))
            return cell_corridor.check([cell_pivot.joints_tcp(f)[:3] for f in frames], mask, args.roi, to_px,
                                       params=params, surface_px=site.get("surface_px"))

        def reserve(frames):
            r = cell_corridor.runs([cell_pivot.joints_tcp(f)[:3] for f in frames])
            lane = cell_corridor.corridor(r[0] + r[1], to_px, (args.roi[3] - args.roi[1], args.roi[2] - args.roi[0]),
                                          args.roi, prm.get(params, "corridor.half_width_mm", cell_corridor.HALF_WIDTH_MM))
            booked["mask"] = lane
            return space.reserve(arm, lane, ttl_s=300.0)

        fence_bad = None
        if args.expires_at is not None and time.time() > float(args.expires_at):
            fence_bad = "SAFE_HOME_EXPIRED"
        elif args.safety_fence is not None or args.stop_generation is not None:
            fence_path = Path(args.safety_fence) if (args.safety_fence and args.safety_fence.strip()) else None
            if fence_path is None or not fence_path.is_file():
                fence_bad = "SAFETY_FENCE_MISSING"
            else:
                try:
                    fence = json.loads(fence_path.read_text(encoding="utf-8"))
                    upd = fence.get("updated_at") if isinstance(fence, dict) else None
                    sg = fence.get("stop_generation") if isinstance(fence, dict) else None
                    if not isinstance(fence, dict) or type(fence.get("human_hold")) is not bool:
                        fence_bad = "SAFETY_FENCE_UNREADABLE"
                    elif fence["human_hold"]:
                        fence_bad = "HUMAN_HOLD_ACTIVE"
                    elif (isinstance(upd, bool) or not isinstance(upd, (int, float))
                          or not math.isfinite(upd) or not (-5.0 <= (time.time() - upd) <= 15.0)):
                        fence_bad = "SAFETY_FENCE_STALE"
                    elif type(sg) is not int or args.stop_generation is None or sg != args.stop_generation:
                        fence_bad = "STOP_GENERATION_PREEMPTED"
                except Exception:
                    fence_bad = "SAFETY_FENCE_UNREADABLE"
        if fence_bad:
            stopped = cell.act("stop now") if args.supervised else {}
            result = {"schema": schema, "result": "held", "reason": fence_bad,
                      "hold_ok": None if stopped.get("ok") is True else cell.act("human-hold").get("ok"),
                      **({"ended": "stop_now", "unmoved": True} if stopped.get("ok") is True else {}), "steps": []}
        else:
            result = recover_fn(cell, home, closed, plan=plan, look=look, reserve=reserve, release=lambda: space.release(arm),
                                release_and_rise=cell_unwedge.release_and_rise, low=low,
                                order=lambda names: choices.ranked(choice_key, names),
                                release_unmoved=args.supervised, moved_out=moved_out, stage=args.stage)
    except Exception as exc:
        err = f"ERROR: {type(exc).__name__}: {str(exc)[:160]}"
        if space is not None:
            space.release(arm)
        if cell is None:
            result = {"schema": schema, "result": "held", "reason": err, "hold_ok": None,
                      **({"unmoved": True} if args.supervised else {}), "steps": []}
        else:
            stopped = cell.act("stop now") if args.supervised and not moved_out else {}
            if stopped.get("ok") is True:
                result = {"schema": schema, "result": "held", "reason": err, "hold_ok": None, "ended": "stop_now",
                          "unmoved": True, "steps": []}
            else:
                held = cell.act("human-hold")
                result = {"schema": schema, "result": "held", "reason": err, "hold_ok": held.get("ok"), "steps": []}
    result["incident_id"] = None if args.supervised else os.environ["ROSY_RECOVERY_INCIDENT"]
    result["home"], result["supervised"] = list(home), bool(args.supervised)
    if choices_path is not None:
        result["choices_path"] = str(choices_path)
    if result["result"] == "folded":
        result["stop"] = cell.act("stop")
    args.out.write_text(json.dumps(result, default=str, indent=1))
    print(json.dumps({k: result.get(k) for k in ("result", "reason", "candidate")}))
    return 0 if result["result"] in ("folded", "risen_for_visual_verify") else 3
