"""D-1057: placement measured against the destination's predefined side and top target zones.

Run right after a placement: fresh frames from the cell's own camera path (`frame_receipt`, no device is opened here),
judged with the existing `cell_area_zones` measurements. The record is carried as `attempts[].zone_verification` and read by
`cell_task_exec`. Nothing is verified without: a configured layer/col/row inside the supported range, a before and an after
frame of both cameras, both after frames taken after the placement and no older than MAX_FRAME_AGE_S at the common judging time.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import time
from typing import Any

from cell_area_zones import TOP_ROI_BY_COL_ROW, evaluate_zone, verify_stack_outcome, verify_stack_outcome_z_mm

BASIS = "predefined_side_and_top_target_zones"
TOP_ONLY_BASIS = "top_camera_only_target_zone"  # a cell without a side camera (cell S): never equals BASIS on purpose
MAX_FRAME_AGE_S = 2.0
FRAME_WAIT_S = 3.0  # how long to wait for a frame captured after the placement
SLOT_COLS, SLOT_ROWS, LAYERS = (1, 2, 3), (1, 2), (0, 1, 2)


def _plain(value: Any) -> Any:
    def convert(obj):
        if hasattr(obj, "tolist"):
            return obj.tolist()
        return obj.item() if hasattr(obj, "item") else str(obj)

    return json.loads(json.dumps(value, default=convert))


@contextmanager
def _side_camera(source, config: dict):
    """Yield whether a side stream exists. The real A/B configs list it only under episodes.cameras (same camera service),
    so that address is lent to the cell's camera map for the duration of the frame calls."""
    cameras = getattr(source, "cameras", None)
    episode_side = ((config.get("episodes") or {}).get("cameras") or {}).get("side")
    borrowed = isinstance(cameras, dict) and "side" not in cameras and isinstance(episode_side, str) and bool(episode_side)
    if borrowed:
        cameras["side"] = episode_side
    try:
        yield bool(cameras) and "side" in cameras
    finally:
        if borrowed:
            cameras.pop("side", None)


def _frame(source, camera: str, previous: dict | None = None, after: float | None = None):
    """(receipt, None) of a frame captured at or after `after` (waiting up to FRAME_WAIT_S for one), else (None, reason)."""
    deadline, reason = time.time() + FRAME_WAIT_S, "no frame"
    while True:
        try:
            receipt = source.frame_receipt(camera, previous=previous, max_age_s=MAX_FRAME_AGE_S)
            if after is None or float(receipt["source_stamp"]) >= after:
                return receipt, None
            reason = f"{camera} frame was captured before the placement finished"
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            reason = f"{camera} frame unavailable: {exc}"
        if time.time() >= deadline:
            return None, reason
        time.sleep(0.05)


def _stamp(receipt: dict) -> dict:
    return {k: receipt.get(k) for k in ("camera", "source_seq", "source_stamp", "captured_at", "jpeg_sha256")}


def before_side(cell, config: dict) -> dict | None:
    """The side frame to take with the before top frame, or None (no side camera, or no frame: the two-camera basis is then
    not available)."""
    source = getattr(cell, "cell", cell)
    with _side_camera(source, config) as has_side:
        return _frame(source, "side")[0] if has_side else None


def record(row: dict, tried: dict, cell, before_frame, config, dest_site, source_site, roi) -> None:
    """Measure, then put verify, transfer and zone_verification on the attempt row: cell_task_exec reads that row, which
    kept none of them before (they went only to the attempts ledger)."""
    tried["zone_verification"] = measure(cell, before_frame, config, dest_site, source_site, roi)
    row.update(verify=tried["verify"], zone_verification=tried["zone_verification"], transfer=tried["transfer"])


def _target(config: dict, dest_site: str):
    """(target dict, None) from the destination site's own layer/col/row, or (None, reason). No default slot or tier."""
    site = (config.get("sites") or {}).get(dest_site) or {}
    layer, col, row = site.get("layer"), site.get("col"), site.get("row")
    if type(layer) is not int or layer not in LAYERS:
        return None, "destination layer not in the site config or outside 0-2"
    if type(col) is not int or col not in SLOT_COLS or type(row) is not int or row not in SLOT_ROWS:
        return None, "target slot col/row not in the site config (real cell configs name only the site place xy) or outside 1-3/1-2"
    if "tier" in site and site["tier"] != layer + 1:
        return None, "site tier and layer disagree"
    return {"site": dest_site, "area": dest_site.rsplit("-l", 1)[0], "col": col, "row": row, "tier": layer + 1}, None


def measure(cell, before_frame: dict | None, config: dict, dest_site: str, source_site: str, roi) -> dict:
    """The zone verification record for the placement that just finished at `dest_site`."""
    placed_at = time.time()  # the release finished before this call: a frame captured after it shows the placed result
    source = getattr(cell, "cell", cell)
    target, bad_target = _target(config, dest_site)
    out: dict[str, Any] = {"basis": "unverified", "verified": False, "target": target, "top": None,
                           "side": {"available": False, "reason": "no side camera in this cell"}}
    top, why = _frame(source, "top", before_frame, placed_at)
    with _side_camera(source, config) as has_side:
        side, side_why = _frame(source, "side", None, placed_at) if has_side else (None, None)
    judged_at = out["measured_at"] = time.time()
    if top is not None:
        out["top"] = {"frame": _stamp(top)}
    if has_side:
        out["side"] = {"available": True, "frame": _stamp(side) if side is not None else None}
    stale = next((f"{f['camera']} frame older than {MAX_FRAME_AGE_S} s at the judging time" for f in (top, side)
                  if f is not None and judged_at - float(f["source_stamp"]) > MAX_FRAME_AGE_S), None)
    before_side_frame = (before_frame or {}).get("before_side")
    missing_before = None
    if before_frame is None or before_frame.get("image") is None:
        missing_before = "no before top frame"
    elif has_side and (before_side_frame or {}).get("image") is None:
        missing_before = "no before side frame"
    failure = why or side_why or bad_target or stale or missing_before
    if failure:
        return {**out, "basis": f"unverified: {failure}"}
    place = {k: target[k] for k in ("area", "col", "row", "tier")}
    if not has_side:
        top_roi = tuple(roi) if roi is not None else TOP_ROI_BY_COL_ROW.get((target["col"], target["row"]))
        zone = evaluate_zone(top["image"], top_roi, tol_u_px=24.0, tol_v_px=40.0, min_fill=0.15) if top_roi else None
        out["top"]["zone"] = _plain(zone)
        return _plain({**out, "basis": TOP_ONLY_BASIS, "verified": bool(zone and zone.get("within_zone"))})
    pick = {"area": (config.get("sites") or {}).get(source_site, {}).get("area") or source_site.rsplit("-l", 1)[0]}
    verify = verify_stack_outcome_z_mm if target["area"] == "pallet" else verify_stack_outcome
    stack = verify(before_side=before_side_frame["image"], after_side=side["image"], before_top=before_frame["image"],
                   after_top=top["image"], pick=pick, place=place)
    top_zone = (stack.get("place_slot") or {}).get("top_zone")
    # verify_stack_outcome leaves top_orientation_ok True when it measured nothing on top: an unmeasured top zone is not verified.
    top_ok = bool(isinstance(top_zone, dict) and top_zone.get("within_zone") and top_zone.get("orientation_ok") is True)
    return _plain({**out, **stack, "verified": bool(stack.get("verified")) and top_ok,
                   "top": {**out["top"], "zone": top_zone}})
