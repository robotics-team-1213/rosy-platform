"""Skill-first 1-call composite CLI over `rosy_agent_bridge` (snapshot, diagnose, frame, propose, schema, call)."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

_DIR = str(Path(__file__).resolve().parent)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import rosy_agent_bridge as br  # noqa: E402

_CAS_KEYS = (
    "fallback_from_task_id",
    "failure_bundle_id",
    "failure_context_sha256",
    "expected_context_sha256",
    "expected_readiness_digest",
    "expected_authority_epoch",
    "expected_dispatch_generation",
    "expected_stop_generation",
)


def _err_summary(res: dict[str, Any]) -> dict[str, Any]:
    return {"ok": False, "status": res.get("status"), "error_code": res.get("error_code"), "detail": res.get("detail")}


def _write_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(path)


def _summarize_fleet_state(res: dict[str, Any]) -> dict[str, Any]:
    if not res.get("ok"):
        return _err_summary(res)
    data = res.get("data") or {}
    fleet = data.get("fleet") or {}
    robots = [
        {k: r.get(k) for k in ("robot_id", "kind", "online", "mode", "battery_pct", "nav_state") if k in r}
        for r in (data.get("robots") or []) if isinstance(r, dict)
    ]
    return {"ok": True, "name": fleet.get("name"), "online": fleet.get("online"), "total": fleet.get("total"), "robots": robots}


def _summarize_fleet_cell(res: dict[str, Any]) -> dict[str, Any]:
    if not res.get("ok"):
        return _err_summary(res)
    d = res.get("data") or {}
    return {k: d.get(k) for k in (
        "cell_id", "cell_phase", "human_detected", "active_estop",
        "authority_epoch", "dispatch_generation", "stop_generation", "readiness_digest",
    ) if k in d}


def _summarize_cell_readiness(res: dict[str, Any]) -> dict[str, Any]:
    if not res.get("ok"):
        return _err_summary(res)
    d = res.get("data") or {}
    arms = {
        arm: {k: info.get(k) for k in ("folded", "incident_held", "incident_reason", "human_hold_latched",
                                       "fault", "live_state_age_s", "dirty", "active_job_id")}
        for arm, info in (d.get("arms") or {}).items() if isinstance(info, dict)
    }
    return {
        "ok": True, "observed_at": d.get("observed_at"), "cell_state_gen": d.get("cell_state_gen"),
        "allowed_tiers_now": d.get("allowed_tiers_now"), "blocking_refusals": d.get("blocking_refusals"),
        "readiness_digest": d.get("readiness_digest"), "arms": arms,
    }


def cmd_snapshot(bridge: br.RosyAgentBridge, args: argparse.Namespace) -> dict[str, Any]:
    cells = [args.cell] if args.cell else ["cell_s", "cell_ab"]
    fs = bridge.call_tool("fleet_state")
    fcells = {cid: bridge.call_tool("fleet_cell_readiness", {"cell_id": cid}) for cid in cells}
    cr = bridge.call_tool("cell_readiness")
    cq = bridge.call_tool("cell_queue", {"include_jobs": True, "include_failures": True, "limit": 5})

    any_ok = bool(fs.get("ok") or cr.get("ok") or cq.get("ok") or any(r.get("ok") for r in fcells.values()))
    cq_data = (cq.get("data") or {}) if cq.get("ok") else {}
    bundles = ((cq_data.get("failures") or {}).get("bundles") or []) if cq.get("ok") else []
    summary: dict[str, Any] = {
        "ok": any_ok,
        "fleet": _summarize_fleet_state(fs),
        "fleet_cells": {cid: _summarize_fleet_cell(r) for cid, r in fcells.items()},
        "arm_cell": _summarize_cell_readiness(cr),
        "queue": cq_data.get("queue") if cq.get("ok") else _err_summary(cq),
        "latest_failures": [
            {k: b.get(k) for k in ("bundle_id", "arm_id", "kind", "created_at_s") if k in b}
            for b in bundles if isinstance(b, dict)
        ],
    }
    if args.out_dir:
        raw_path = Path(args.out_dir).expanduser() / "snapshot.json"
        summary["raw_path"] = _write_json(raw_path, {
            "fleet_state": fs, "fleet_cells": fcells, "cell_readiness": cr, "cell_queue": cq,
        })
    return summary


def _resolve_diagnose_dir(out_dir: str | None, bundle_id: str) -> Path | None:
    if out_dir:
        return Path(out_dir).expanduser()
    scratch = os.environ.get("ROSY_SCRATCH", "").strip()
    if scratch:
        return Path(scratch).expanduser() / "rosy-diagnose" / bundle_id
    return None


def cmd_diagnose(bridge: br.RosyAgentBridge, args: argparse.Namespace) -> dict[str, Any]:
    fc_args: dict[str, Any] = {}
    if args.bundle_id:
        fc_args["bundle_id"] = args.bundle_id
    elif args.arm:
        fc_args["arm"] = args.arm
    fc = bridge.call_tool("cell_failure_context", fc_args)
    if not fc.get("ok"):
        return fc
    bundle = fc.get("data")
    if not isinstance(bundle, dict) or not isinstance(bundle.get("bundle_id"), str) or not br._safe_segment(bundle["bundle_id"]):
        return {"ok": False, "status": 502, "error_code": "INVALID_UPSTREAM_RESPONSE",
                "detail": "unsafe or malformed bundle_id"}
    bid = bundle["bundle_id"]
    out_dir = _resolve_diagnose_dir(args.out_dir, bid)
    if out_dir is None:
        return {"ok": False, "status": 400, "error_code": "INVALID_ARGS",
                "detail": "--out-dir is required when ROSY_SCRATCH is unset"}
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = _write_json(out_dir / "bundle.json", bundle)

    arm_id = bundle.get("arm_id")
    cid = args.cell or bundle.get("cell_id") or ("cell_s" if arm_id == "arm_s" else "cell_ab")
    cr = bridge.call_tool("cell_readiness")
    fr = bridge.call_tool("fleet_cell_readiness", {"cell_id": cid})

    saved_images: list[str] = []
    frames = ((bundle.get("visual") or {}).get("frames") or [])[: max(0, args.max_frames)]
    for fr_meta in frames:
        fn = fr_meta.get("file") if isinstance(fr_meta, dict) else None
        if not isinstance(fn, str) or not fn:
            continue
        asset = bridge.call_tool("cell_failure_asset", {"bundle_id": bid, "filename": fn})
        if asset.get("ok") and isinstance(asset.get("image_b64"), str):
            dest = out_dir / Path(fn).name
            dest.write_bytes(base64.b64decode(asset["image_b64"]))
            saved_images.append(str(dest))

    trace_tail_path = None
    trace_ref = (bundle.get("measurement") or {}).get("trace_ref")
    if isinstance(trace_ref, dict) and isinstance(trace_ref.get("file"), str):
        tfn = trace_ref["file"]
        t_asset = bridge.call_tool("cell_failure_asset", {"bundle_id": bid, "filename": tfn})
        if t_asset.get("ok") and isinstance(t_asset.get("text"), str):
            tdest = out_dir / Path(tfn).name
            tdest.write_text(t_asset["text"], encoding="utf-8")
            trace_tail_path = str(tdest)

    for view in [v.strip() for v in (args.views or "").split(",") if v.strip()]:
        live = bridge.call_tool("cell_frame", {"view": view})
        if live.get("ok") and isinstance(live.get("image_b64"), str):
            ldest = out_dir / f"live-{view}.jpg"
            ldest.write_bytes(base64.b64decode(live["image_b64"]))
            saved_images.append(str(ldest))

    fr_data = fr.get("data") if fr.get("ok") else {}
    hist = bundle.get("history_and_constraints") or {}
    meas = bundle.get("measurement") or {}
    cas = {
        "cell_id": cid,
        "arm_id": arm_id,
        "fallback_from_task_id": (bundle.get("correlation") or {}).get("fleet_task_id"),
        "failure_bundle_id": bid,
        "failure_context_sha256": bundle.get("context_sha256"),
        "expected_context_sha256": bundle.get("context_sha256"),
        "expected_readiness_digest": fr_data.get("readiness_digest"),
        "expected_authority_epoch": fr_data.get("authority_epoch"),
        "expected_dispatch_generation": fr_data.get("dispatch_generation"),
        "expected_stop_generation": fr_data.get("stop_generation"),
        "allowed_fallback_menu": hist.get("allowed_fallback_menu") or [],
    }
    cas_path = _write_json(out_dir / "cas_context.json", cas)
    return {
        "ok": True,
        "bundle_id": bid,
        "arm_id": arm_id,
        "cell_id": cid,
        "executor_mode": bundle.get("executor_mode"),
        "attempt_cause": meas.get("attempt_cause"),
        "stage": meas.get("stage"),
        "result": meas.get("result"),
        "freshness": bundle.get("freshness"),
        "measured_vetoes": hist.get("measured_vetoes"),
        "allowed_fallback_menu": cas["allowed_fallback_menu"],
        "cas": {k: cas[k] for k in ("cell_id", "arm_id", *_CAS_KEYS)},
        "cell_readiness": _summarize_cell_readiness(cr),
        "fleet_cell_readiness": _summarize_fleet_cell(fr),
        "saved_images": saved_images,
        "trace_tail_path": trace_tail_path,
        "bundle_path": bundle_path,
        "cas_path": cas_path,
        "out_dir": str(out_dir),
    }


def cmd_frame(bridge: br.RosyAgentBridge, args: argparse.Namespace) -> dict[str, Any]:
    res = bridge.call_tool("cell_frame", {"view": args.view})
    if not res.get("ok"):
        return res
    raw = base64.b64decode(res.pop("image_b64"))
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)
    return {**res, "view": args.view, "out": str(out_path)}


def cmd_propose(bridge: br.RosyAgentBridge, args: argparse.Namespace) -> dict[str, Any]:
    cas_path = Path(args.from_dir).expanduser() / "cas_context.json"
    if not cas_path.is_file():
        return {"ok": False, "status": 400, "error_code": "INVALID_ARGS",
                "detail": f"cas_context.json not found under {args.from_dir}"}
    cas = json.loads(cas_path.read_text(encoding="utf-8"))
    menu = cas.get("allowed_fallback_menu") or []
    if args.verb:
        allowed = any(
            isinstance(item, dict) and item.get("verb") == args.verb and item.get("preconditions_met") is True
            for item in menu
        )
        if not allowed:
            return {"ok": False, "status": 403, "error_code": "VERB_NOT_ALLOWED",
                    "detail": f"verb {args.verb!r} is not allowed with preconditions_met=true in allowed_fallback_menu"}

    payload: dict[str, Any] = {"cell_id": args.cell_id or cas["cell_id"]}
    if arm := (args.arm_id or cas.get("arm_id")):
        payload["arm_id"] = arm
    for k in _CAS_KEYS:
        if cas.get(k) is not None:
            payload[k] = cas[k]
    for cli_k, pay_k in (
        ("verb", "fallback_verb"), ("preset", "preset"), ("src_site", "src_site"), ("dst_site", "dst_site"),
        ("robot_id", "robot_id"), ("tier", "tier"), ("execution_mode", "execution_mode"),
        ("max_chunks", "max_chunks"), ("displaced_to", "displaced_to"), ("zone_id", "zone_id"),
    ):
        if (val := getattr(args, cli_k)) is not None:
            payload[pay_k] = val
    if args.request_key:
        payload["request_key"] = args.request_key
    else:
        seed = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        payload["request_key"] = "rosy-cli-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]

    if args.dry_run:
        if err := br._validate_args(br.TOOL_MAP["fleet_propose_cell_task"], payload):
            return {"ok": False, "status": 400, "error_code": "INVALID_ARGS", "detail": err}
        if refusal := bridge.check_cell_proposal_context(payload):
            return refusal
        return {"ok": True, "dry_run": True, "payload": payload}
    return bridge.call_tool("fleet_propose_cell_task", payload)


def cmd_sites(bridge: br.RosyAgentBridge, args: argparse.Namespace) -> dict[str, Any]:
    res = bridge.call_tool("fleet_cell_sites")
    if not res.get("ok"):
        return res
    d = res.get("data") or {}
    sites = d.get("sites") or []
    if args.area:
        sites = [s for s in sites if isinstance(s, dict) and s.get("area") == args.area]
    return {
        "ok": True,
        "schema": d.get("schema"),
        "count": len(sites),
        "zones": d.get("zones") or [],
        "sites": [
            {k: s.get(k) for k in ("site_id", "sim_site", "area", "col", "row", "tier", "arms", "status") if k in s}
            for s in sites if isinstance(s, dict)
        ],
    }


def _infer_pick_cell(args: argparse.Namespace) -> str:
    if args.cell:
        return args.cell
    preset = str(args.preset or "").strip()
    if preset.startswith("s5_") or preset == "export_s5_pallet":
        return "cell_ab"
    if preset.startswith(("s3_", "full_s3_")) or preset == "export_s3_belt":
        return "cell_s"
    if args.arm in ("arm_a", "arm_b"):
        return "cell_ab"
    return "cell_s"


def _poll_pick_tasks(bridge: br.RosyAgentBridge, task_ids: list[str], timeout_s: float) -> tuple[bool, list[dict[str, Any]]]:
    deadline = time.monotonic() + max(0.5, float(timeout_s))
    terminal = {"COMPLETED", "ABORTED", "CANCELLED"}
    latest: dict[str, dict[str, Any]] = {}
    while True:
        res = bridge.call_tool("fleet_cell_tasks")
        if res.get("ok"):
            for t in (res.get("data") or {}).get("tasks") or []:
                if isinstance(t, dict) and t.get("task_id") in task_ids:
                    latest[t["task_id"]] = t
            if all(tid in latest and latest[tid].get("status") in terminal for tid in task_ids):
                return True, [latest[tid] for tid in task_ids]
        if time.monotonic() >= deadline:
            return False, [latest.get(tid, {"task_id": tid, "status": "UNKNOWN"}) for tid in task_ids]
        time.sleep(1.5)


def _pair(text: str | None, *, sep=int) -> list | None:
    try:
        pair = [sep(x) for x in str(text).split(",")]
    except ValueError:
        pair = []
    return pair if len(pair) == 2 else None


def _motion_frame(args: argparse.Namespace) -> dict[str, Any]:
    return {"frame_seq": args.frame_seq, "frame_sha256": args.frame_sha256}


def _motion_error(detail: str) -> dict[str, Any]:
    return {"ok": False, "status": 400, "error_code": "INVALID_ARGS", "detail": detail}


def cmd_pick(bridge: br.RosyAgentBridge, args: argparse.Namespace) -> dict[str, Any]:
    cell_id = "cell_ab" if args.free_anchor and not args.cell else _infer_pick_cell(args)
    payload: dict[str, Any] = {"cell_id": cell_id}
    if args.free_anchor:  # free-position pick: pixels from a frame, never metres; the server derives the sites
        at_px = _pair(args.at_px)
        if at_px is None or not args.dst or args.frame_seq is None or not args.frame_sha256 or args.src or args.preset or args.tiers:
            return _motion_error("--free-anchor needs --at-px U,V --dst SITE --frame-seq N --frame-sha256 SHA from 'rosy frame', and no --src/--preset/--tiers")
        payload["motion"] = {"kind": "free_pick", "anchor_site": args.free_anchor, "at_px": at_px, "dst_site": args.dst,
                             **_motion_frame(args), **{k: v for k, v in (("object", args.object), ("colour", args.colour)) if v}}
        args.dst = None
    for cli_k, pay_k in (
        ("arm", "arm_id"), ("src", "src_site"), ("dst", "dst_site"), ("tier", "tier"),
        ("preset", "preset"), ("mode", "execution_mode"), ("max_chunks", "max_chunks"),
        ("robot_id", "robot_id"), ("zone_id", "zone_id"), ("request_key", "request_key"),
    ):
        if (val := getattr(args, cli_k)) is not None:
            payload[pay_k] = val
    if args.tiers is not None:
        try:
            payload["tiers"] = [int(x.strip()) for x in args.tiers.split(",") if x.strip()]
        except ValueError:
            return {"ok": False, "status": 400, "error_code": "INVALID_ARGS", "detail": "tiers must be comma-separated integers"}
    if args.auto_admit:
        payload["auto_admit"] = True
    tool_name = "fleet_propose_cell_task" if args.propose else "fleet_dispatch_cell_task"
    if args.dry_run:
        if err := br._validate_args(br.TOOL_MAP[tool_name], payload):
            return {"ok": False, "status": 400, "error_code": "INVALID_ARGS", "detail": err}
        return {"ok": True, "dry_run": True, "tool": tool_name, "payload": payload}
    res = bridge.call_tool(tool_name, payload)
    if not res.get("ok") or not args.wait:
        return res
    data = res.get("data") or {}
    tasks = data.get("tasks") or ([data["task"]] if isinstance(data.get("task"), dict) else [])
    task_ids = [str(t["task_id"]) for t in tasks if isinstance(t, dict) and t.get("task_id")]
    if not task_ids:
        return res
    if any(t.get("status") == "PROPOSED" for t in tasks if isinstance(t, dict)):
        return {**res, "waited": False, "needs_approval": True, "task_ids": task_ids}
    done, final_tasks = _poll_pick_tasks(bridge, task_ids, args.wait_timeout_s)
    return {
        **res,
        "ok": done and all(t.get("status") == "COMPLETED" for t in final_tasks),
        "waited": True,
        "timed_out": not done,
        "final_tasks": [
            {k: t.get(k) for k in ("task_id", "status", "arm_id", "src_site", "dst_site", "tier", "approved_by", "last_refusal")}
            for t in final_tasks
        ],
    }


def cmd_push(bridge: br.RosyAgentBridge, args: argparse.Namespace) -> dict[str, Any]:
    """A push is always a proposal: a named human approves it in the Fleet console."""
    px, direction = _pair(args.px), _pair(args.dir, sep=float)
    if px is None or direction is None or args.frame_seq is None or not args.frame_sha256:
        return _motion_error("--site, --px U,V, --dir DX,DY, --mm, --frame-seq and --frame-sha256 are required")
    payload: dict[str, Any] = {"cell_id": args.cell, "motion": {"kind": "push", "site": args.site, "px": px, "dir": direction,
                                                              "mm": args.mm, **_motion_frame(args)}}
    if args.arm:
        payload["arm_id"] = args.arm
    if args.request_key:
        payload["request_key"] = args.request_key
    if args.dry_run:
        if err := br._validate_args(br.TOOL_MAP["fleet_propose_cell_task"], payload):
            return _motion_error(err)
        return {"ok": True, "dry_run": True, "tool": "fleet_propose_cell_task", "payload": payload}
    res = bridge.call_tool("fleet_propose_cell_task", payload)
    return {**res, "needs_approval": True} if res.get("ok") else res


def cmd_schema(args: argparse.Namespace) -> tuple[Any, int]:
    if args.tool:
        if args.tool not in br.TOOL_MAP:
            return {"ok": False, "status": 400, "error_code": "UNKNOWN_TOOL", "detail": f"unknown tool {args.tool!r}"}, 1
        return br.TOOL_MAP[args.tool], 0
    return [
        {"name": t["name"], "description": t["description"], "required": t["inputSchema"].get("required", [])}
        for t in br.TOOL_SPECS
    ], 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--cell-url", default=None)
    ap.add_argument("--fleet-url", default=None)
    ap.add_argument("--learning-url", default=None)
    ap.add_argument("--cell-token-file", type=Path, default=None)
    ap.add_argument("--fleet-token-file", type=Path, default=None)
    ap.add_argument("--fleet-cookie-file", type=Path, default=None)
    ap.add_argument("--fleet-ca-file", default=None)
    ap.add_argument("--learning-token-file", type=Path, default=None)
    ap.add_argument("--timeout-s", type=float, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_snap = sub.add_parser("snapshot")
    p_snap.add_argument("--cell", choices=["cell_s", "cell_ab"], default=None)
    p_snap.add_argument("--out-dir", default=None)

    p_diag = sub.add_parser("diagnose")
    p_diag.add_argument("--arm", default=None)
    p_diag.add_argument("--bundle-id", default=None)
    p_diag.add_argument("--cell", choices=["cell_s", "cell_ab"], default=None)
    p_diag.add_argument("--views", default="")
    p_diag.add_argument("--max-frames", type=int, default=4)
    p_diag.add_argument("--out-dir", default=None)

    p_frame = sub.add_parser("frame")
    p_frame.add_argument("view")
    p_frame.add_argument("--out", required=True)

    p_prop = sub.add_parser("propose")
    p_prop.add_argument("--from", dest="from_dir", required=True)
    p_prop.add_argument("--verb", default=None)
    p_prop.add_argument("--cell-id", choices=["cell_s", "cell_ab"], default=None)
    p_prop.add_argument("--arm-id", default=None)
    p_prop.add_argument("--preset", default=None)
    p_prop.add_argument("--src-site", default=None)
    p_prop.add_argument("--dst-site", default=None)
    p_prop.add_argument("--robot-id", default=None)
    p_prop.add_argument("--tier", type=int, default=None)
    p_prop.add_argument("--execution-mode", choices=["guarded_pick", "act_policy"], default=None)
    p_prop.add_argument("--max-chunks", type=int, default=None)
    p_prop.add_argument("--displaced-to", default=None)
    p_prop.add_argument("--zone-id", default=None)
    p_prop.add_argument("--request-key", default=None)
    p_prop.add_argument("--dry-run", action="store_true")

    p_sites = sub.add_parser("sites")
    p_sites.add_argument("--area", default=None)

    p_pick = sub.add_parser("pick")
    p_pick.add_argument("--cell", choices=["cell_s", "cell_ab"], default=None)
    p_pick.add_argument("--arm", default=None)
    p_pick.add_argument("--src", default=None)
    p_pick.add_argument("--dst", default=None)
    p_pick.add_argument("--tier", type=int, default=None)
    p_pick.add_argument("--tiers", default=None)
    p_pick.add_argument("--preset", default=None)
    p_pick.add_argument("--mode", choices=["guarded_pick", "act_policy"], default=None)
    p_pick.add_argument("--max-chunks", type=int, default=None)
    p_pick.add_argument("--robot-id", default=None)
    p_pick.add_argument("--zone-id", default=None)
    p_pick.add_argument("--request-key", default=None)
    p_pick.add_argument("--free-anchor", default=None, help="pick at a pixel on this site (free position), not at a fixed slot")
    p_pick.add_argument("--at-px", default=None)
    p_pick.add_argument("--frame-seq", type=int, default=None)
    p_pick.add_argument("--frame-sha256", default=None, help="audit record of the chosen frame only; the cell re-measures at run time")
    p_pick.add_argument("--object", default=None)
    p_pick.add_argument("--colour", default=None)
    p_pick.add_argument("--propose", action="store_true")
    p_pick.add_argument("--auto-admit", action="store_true")
    p_pick.add_argument("--dry-run", action="store_true")
    p_pick.add_argument("--wait", action="store_true")
    p_pick.add_argument("--wait-timeout-s", type=float, default=120.0)

    p_push = sub.add_parser("push")
    p_push.add_argument("--cell", choices=["cell_s", "cell_ab"], default="cell_ab")
    p_push.add_argument("--arm", default=None)
    p_push.add_argument("--site", required=True)
    p_push.add_argument("--px", required=True)
    p_push.add_argument("--dir", required=True, help="DX,DY; write a leading minus as --dir=-1,0")
    p_push.add_argument("--mm", type=float, required=True)
    p_push.add_argument("--frame-seq", type=int, default=None)
    p_push.add_argument("--frame-sha256", default=None, help="audit record of the chosen frame only; the cell re-measures at run time")
    p_push.add_argument("--request-key", default=None)
    p_push.add_argument("--dry-run", action="store_true")

    p_schema = sub.add_parser("schema")
    p_schema.add_argument("tool", nargs="?", default=None)

    p_call = sub.add_parser("call")
    p_call.add_argument("tool")
    p_call.add_argument("--args-json", default=None)
    p_call.add_argument("--args-file", type=Path, default=None)
    return ap


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # a Windows cp1252/cp949 console cannot print site labels
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd == "schema":
        out, rc = cmd_schema(args)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return rc
    bridge = br.RosyAgentBridge(br.build_config(args))
    if args.cmd == "snapshot":
        res = cmd_snapshot(bridge, args)
    elif args.cmd == "diagnose":
        res = cmd_diagnose(bridge, args)
    elif args.cmd == "frame":
        res = cmd_frame(bridge, args)
    elif args.cmd == "propose":
        res = cmd_propose(bridge, args)
    elif args.cmd == "sites":
        res = cmd_sites(bridge, args)
    elif args.cmd == "pick":
        res = cmd_pick(bridge, args)
    elif args.cmd == "push":
        res = cmd_push(bridge, args)
    else:
        if args.args_file is not None and args.args_json is not None:
            ap.error("--args-file and --args-json are mutually exclusive")
        raw_json = Path(args.args_file).expanduser().read_text(encoding="utf-8-sig") if args.args_file is not None else (args.args_json or "{}")
        res = bridge.call_tool(args.tool, json.loads(raw_json))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
