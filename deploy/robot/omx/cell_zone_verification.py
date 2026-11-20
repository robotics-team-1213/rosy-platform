"""D-1057: placement measured against the destination's predefined side and top target zones.

Run right after a placement: fresh frames from the cell's own camera path (`frame_receipt`, no device is opened here),
judged with the existing `cell_area_zones` measurements. The record is carried as `attempts[].zone_verification` and read by
`cell_task_exec`; a failed or stale frame is never verified.
"""
from __future__ import annotations

import json
import time
from typing import Any

from cell_area_zones import TOP_ROI_BY_COL_ROW, evaluate_zone, verify_stack_outcome, verify_stack_outcome_z_mm

BASIS = "predefined_side_and_top_target_zones"
TOP_ONLY_BASIS = "top_camera_only_target_zone"  # a cell without a side camera (cell S): never equals BASIS on purpose
MAX_FRAME_AGE_S = 2.0


def _plain(value: Any) -> Any:
    def convert(obj):
        if hasattr(obj, "tolist"):
            return obj.tolist()
        return obj.item() if hasattr(obj, "item") else str(obj)

    return json.loads(json.dumps(value, default=convert))


def _frame(source, camera: str, previous: dict | None = None) -> tuple[dict | None, str | None]:
    """(receipt, None) of a source frame no older than MAX_FRAME_AGE_S now, else (None, reason)."""
    try:
        receipt = source.frame_receipt(camera, previous=previous, max_age_s=MAX_FRAME_AGE_S)
        if time.time() - float(receipt["source_stamp"]) > MAX_FRAME_AGE_S:
            return None, f"{camera} frame older than {MAX_FRAME_AGE_S} s"
        return receipt, None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, f"{camera} frame unavailable: {exc}"


def _stamp(receipt: dict) -> dict:
    return {k: receipt.get(k) for k in ("camera", "source_seq", "source_stamp", "captured_at", "jpeg_sha256")}


def record(row: dict, tried: dict, cell, before_frame, config, dest_site, source_site, roi) -> None:
    """Measure, then put verify, transfer and zone_verification on the attempt row: cell_task_exec reads that row, which
    kept none of them before (they went only to the attempts ledger)."""
    tried["zone_verification"] = measure(cell, before_frame, config, dest_site, source_site, roi)
    row.update(verify=tried["verify"], zone_verification=tried["zone_verification"], transfer=tried["transfer"])


def measure(cell, before_frame: dict | None, config: dict, dest_site: str, source_site: str, roi) -> dict:
    """The zone verification record for the placement that just finished at `dest_site`."""
    source = getattr(cell, "cell", cell)
    site = (config.get("sites") or {}).get(dest_site) or {}
    area = dest_site.rsplit("-l", 1)[0]
    # cell_place_fit.with_tiers expands `pallet` into `pallet-l0..l2` with layer and tier; a site without them (belt) is tier 1.
    tier = int(site.get("tier", int(site.get("layer", 0)) + 1))
    col, row = site.get("col"), site.get("row")
    out: dict[str, Any] = {"basis": "unverified", "verified": False, "top": None,
                           "side": {"available": False, "reason": "no side camera in this cell"}}
    top, why = _frame(source, "top", before_frame)
    cameras = getattr(source, "cameras", None)
    # The real A/B configs list the side stream only under episodes.cameras: the same camera service, so use that address.
    episode_side = ((config.get("episodes") or {}).get("cameras") or {}).get("side")
    borrowed = isinstance(cameras, dict) and "side" not in cameras and isinstance(episode_side, str) and bool(episode_side)
    has_side = bool(cameras) and ("side" in cameras or borrowed)
    if borrowed:
        cameras["side"] = episode_side
    try:
        side, side_why = _frame(source, "side") if has_side else (None, None)
    finally:
        if borrowed:
            cameras.pop("side", None)
    out["measured_at"] = time.time()
    if top is not None:
        out["top"] = {"frame": _stamp(top)}
    if has_side:
        out["side"] = {"available": True, "frame": _stamp(side) if side is not None else None}
    failure = why or side_why or (None if type(col) is int and type(row) is int else "target slot col/row not in the site config (real cell configs name only the site place xy)")
    if failure:
        return {**out, "basis": f"unverified: {failure}"}
    place = {"area": area, "col": col, "row": row, "tier": tier}
    if not has_side:
        top_roi = tuple(roi) if roi is not None else TOP_ROI_BY_COL_ROW.get((col, row))
        zone = evaluate_zone(top["image"], top_roi, tol_u_px=24.0, tol_v_px=40.0, min_fill=0.15) if top_roi else None
        out["top"]["zone"] = _plain(zone)
        return _plain({**out, "basis": TOP_ONLY_BASIS, "verified": bool(zone and zone.get("within_zone"))})
    pick = {"area": (config.get("sites") or {}).get(source_site, {}).get("area") or source_site.rsplit("-l", 1)[0]}
    verify = verify_stack_outcome_z_mm if area == "pallet" else verify_stack_outcome
    stack = verify(before_side=None, after_side=side["image"], before_top=before_frame and before_frame.get("image"),
                   after_top=top["image"], pick=pick, place=place)
    return _plain({**out, **stack, "top": {**out["top"], "zone": (stack.get("place_slot") or {}).get("top_zone")}})
