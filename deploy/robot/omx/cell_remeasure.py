"""D-1057: re-measure a kept result that is about to go stale (owner evidence older than STALE_S) without moving the arm.

A fresh owner-evidence body is built from fresh top/side frames judged against the stored before frames, and from the live
runner state; the original park readback is kept because the arm has not moved since.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from cell_presence import zone_acceptance

STALE_S = 65.0  # aligned with cell_result_outbox.STALE_S
def context_path(prep_dir: str | Path, task_id: str) -> Path:
    return Path(prep_dir).expanduser() / f"remeasure-{task_id}.json"  # beside the cell config the worker already uses


def write_context(cfg: Path, cfg_data: dict[str, Any], handoff: dict[str, Any], arm_id: str, prep_dir: Path, dst: str,
                  src_site: str, src_roi, zone: dict | None, *, cat_path: Path | None = None) -> None:
    """What a later re-measurement needs, in the prep directory (never sent to Fleet). Best effort."""
    work_dir = cfg_data.get("work_dir")
    if not work_dir:
        return
    try:
        path = context_path(prep_dir, str(handoff.get("task_id")))
        dst_base = dst.rsplit("-l", 1)[0]
        sites = cfg_data.get("sites") if isinstance(cfg_data.get("sites"), dict) else {}
        dst_cfg = sites.get(dst) if isinstance(sites.get(dst), dict) else (sites.get(dst_base) if isinstance(sites.get(dst_base), dict) else {})
        dst_roi = ((zone or {}).get("target") or {}).get("roi") or dst_cfg.get("auto_roi")
        payload = {
            "cfg": str(cfg), "prep_dir": str(prep_dir), "arm_id": arm_id, "dst": dst, "src_site": src_site, "src_roi": list(src_roi),
            **({"dst_roi": [int(v) for v in dst_roi]} if isinstance(dst_roi, (list, tuple)) and len(dst_roi) == 4 else {}),
            "handoff": {k: handoff.get(k) for k in ("task_id", "cell_id", "tier", "handoff_lease_id", "arm_id", "dst_site", "dst_site_id", "dst_area")},
            "before_frames": (zone or {}).get("before_frames"), "work_dir": work_dir,
        }
        if cat_path is not None:
            payload["cat"] = str(cat_path)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except (OSError, KeyError, TypeError):
        pass


class RemeasureFailed(Exception):
    pass


def remeasure(task_id: str, entry: dict[str, Any], prep_dir: Path, *, now: float | None = None):
    """(owner-evidence body, /complete body) built from a fresh measurement of the placed result; the arm is not moved.

    Fresh top (and side) frames judge the placement again against the stored before frames; the fold is the live runner
    state AND the stored park readback (the arm has not moved since). Raises RemeasureFailed with the reason otherwise.
    """
    import cv2

    import cell_place_fit
    import cell_zone_verification as czv
    from cell_pipeline import FifoCell
    from cell_result_outbox import result_bodies
    from cell_task_exec import measured_fold, source_clearance

    complete = entry.get("complete") or {}
    stage, hw, receipt = (dict(complete.get(k) or {}) for k in ("stage_result", "hardware_telemetry", "receipt"))
    try:
        ctx = json.loads(context_path(prep_dir, task_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ctx = None
    if not ctx or not stage or not hw:
        raise RemeasureFailed("no stored context to measure again")
    handoff, work = ctx["handoff"], Path(ctx["work_dir"]).expanduser()
    config = cell_place_fit.with_tiers(json.loads(Path(ctx["cfg"]).read_text(encoding="utf-8")))[0]
    frames = ctx.get("before_frames") or {}
    top = cv2.imread(str(work / "zone-before" / str(frames.get("top")))) if frames.get("top") else None
    side = cv2.imread(str(work / "zone-before" / str(frames.get("side")))) if frames.get("side") else None
    if top is None:
        raise RemeasureFailed("the stored before frame is missing")
    cell = FifoCell(Path(config["io"]).expanduser(), config["cameras"])
    before_obs = {"camera": "top", "_reused": True, "image": top,
                  "before_side": {"camera": "side", "_reused": True, "image": side} if side is not None else None}
    dst_base = ctx["dst"].rsplit("-l", 1)[0]
    sites = config.get("sites") if isinstance(config.get("sites"), dict) else {}
    dst_cfg = sites.get(ctx["dst"]) if isinstance(sites.get(ctx["dst"]), dict) else (sites.get(dst_base) if isinstance(sites.get(dst_base), dict) else {})
    dst_roi = ctx.get("dst_roi") or dst_cfg.get("auto_roi")
    zone = czv.measure(cell, before_obs, config, ctx["dst"], ctx["src_site"], dst_roi)
    if not zone_acceptance(zone, handoff, ctx["dst"]):
        raise RemeasureFailed(f"the placement is not verified now: {zone.get('basis')}")
    if handoff.get("cell_id") == "cell_s" and isinstance(stage.get("source_clearance"), dict) and ctx.get("cat"):
        fresh_sc = source_clearance(Path(ctx["cfg"]), Path(ctx["cat"]), ctx["src_roi"], ctx["src_site"])
        if type(fresh_sc.get("objects")) is not int:
            raise RemeasureFailed(f"source clearance unmeasured: {fresh_sc.get('error')}")
        stage["source_clearance"] = fresh_sc
    live = measured_fold(ctx["arm_id"], Path(ctx["prep_dir"]), now)
    old_fold = (hw.get("stop_event") or {}).get("readback") or {}
    if not (live["folded"] and old_fold.get("folded")):
        raise RemeasureFailed("the arm is not folded now (live runner state or the stored park readback)")
    placement = (stage.get("verification") or {}).get("placement") or {}
    stage["verification"] = {**zone, "placement": placement}
    stage["task_verified"] = bool(placement.get("verified") is True and placement.get("inside") is True)
    hw = {**hw, "measured_at": time.time() if now is None else now,
          "stop_event": {**hw["stop_event"], "ok": True, "folded": True, "live": live}}
    digest = "sha256:" + hashlib.sha256(json.dumps({"task_id": task_id, "lease": handoff["handoff_lease_id"],
                                                   "stage_result": stage, "hardware_telemetry": hw},
                                                  sort_keys=True, default=str).encode()).hexdigest()
    receipt = {**receipt, "goal_evidence_digest": digest, "reason": "TRANSFER_CONFIRMED"}  # the result is released again
    return result_bodies(handoff, "RELEASED", digest, receipt, stage, hw)
