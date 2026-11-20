"""D-1057: placement measured against the destination's predefined side and top target zones.

Run right after a placement: fresh frames from the cell's own camera path (`frame_receipt`, no device is opened here),
judged with the existing `cell_area_zones` measurements. The record is carried as `attempts[].zone_verification` and read by
`cell_task_exec`. Nothing is verified without: a configured layer/col/row inside the supported range, a before and an after
frame of both cameras, both after frames taken after the placement and no older than MAX_FRAME_AGE_S at the common judging time.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import time
from typing import Any

from cell_area_zones import evaluate_zone, verify_stack_outcome, verify_stack_outcome_z_mm

BASIS = "predefined_side_and_top_target_zones"
TOP_ONLY_BASIS = "top_camera_only_target_zone"  # a cell without a side camera (cell S): never equals BASIS on purpose
MAX_FRAME_AGE_S = 2.0
FRAME_WAIT_S = 3.0  # how long to wait for a frame captured after the placement
SLOT_COLS, SLOT_ROWS, LAYERS = (1, 2, 3), (1, 2), (0, 1, 2)
DEPTH_WAIT_S = 5.0  # a Z16 capture skips 12 frames at 6 fps first
DEPTH_DEVICE = "/dev/v4l/by-id/rosy-realsense-d435-depth"


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
    """(receipt, None) of a frame captured at or after `after` (waiting up to FRAME_WAIT_S for one), else (None, reason).
    The wait is a hard limit: each HTTP read gets only the time that is left."""
    deadline, reason = time.time() + FRAME_WAIT_S, "no frame"
    while True:
        try:
            receipt = source.frame_receipt(camera, previous=previous, max_age_s=MAX_FRAME_AGE_S,
                                           timeout_s=max(0.2, deadline - time.time()))
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


def _depth_after(config: dict, after: float):
    """(depth array, receipt, None) from the existing D435 Z16 capture, exposed after `after`, else (None, None, reason).

    cell_depth.capture_top_depth_z16_receipt is the depth source the cell already has (V4L2 depth node, not the colour stream
    that the camera service holds). Its receipt carries the start-of-exposure wall time."""
    import tempfile

    import cell_depth

    top = (config.get("cameras") or {}).get("top") or {}
    device = top.get("depth_device") or DEPTH_DEVICE
    try:
        raw = Path(tempfile.mkdtemp(prefix="zone-depth-")) / "depth.raw"
        got = cell_depth.capture_top_depth_z16_receipt(device, raw, timeout_s=DEPTH_WAIT_S)
    except (OSError, ValueError) as exc:
        return None, None, f"depth capture failed: {exc}"
    if got is None:
        return None, None, "depth capture unavailable"
    depth, receipt = got
    if float(receipt.get("exposure_wall_estimate_s", 0.0)) < after:
        return None, None, "depth frame was exposed before the placement finished"
    return depth, receipt, None


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


def _top_target(config: dict, dest_site: str, roi):
    """Cell S (top camera only, user decision 2026-11-20): the target zone is the destination site's own ROI, tier 1."""
    site = (config.get("sites") or {}).get(dest_site) or {}
    if not (isinstance(roi, (list, tuple)) and len(roi) == 4 and all(type(v) in (int, float) for v in roi)):
        return None, "destination site has no auto_roi"
    if site.get("layer", 0) != 0:
        return None, "top-camera-only check is for tier 1"
    return {"site": dest_site, "area": dest_site.rsplit("-l", 1)[0], "roi": [int(v) for v in roi], "tier": 1}, None


def measure(cell, before_frame: dict | None, config: dict, dest_site: str, source_site: str, roi) -> dict:
    """The zone verification record for the placement that just finished at `dest_site`."""
    placed_at = time.time()  # the release finished before this call: a frame captured after it shows the placed result
    source = getattr(cell, "cell", cell)
    out: dict[str, Any] = {"basis": "unverified", "verified": False, "target": None, "top": None,
                           "side": {"available": False, "reason": "no side camera in this cell"}}
    # The pallet height gate needs calibrated depth. The slow Z16 capture goes first so the RGB frames taken after it stay fresh.
    depth = depth_receipt = depth_why = None
    if dest_site.rsplit("-l", 1)[0] == "pallet":
        depth, depth_receipt, depth_why = _depth_after(config, placed_at)
    top, why = _frame(source, "top", before_frame, placed_at)
    with _side_camera(source, config) as has_side:
        side, side_why = _frame(source, "side", None, placed_at) if has_side else (None, None)
    target, bad_target = _target(config, dest_site) if has_side else _top_target(config, dest_site, roi)
    out["target"] = target
    judged_at = out["measured_at"] = time.time()
    if depth_receipt is not None:
        out["depth"] = {k: depth_receipt.get(k) for k in ("source_seq", "exposure_wall_estimate_s", "valid_depth_ratio", "raw_sha256")}
        if judged_at - float(depth_receipt["exposure_wall_estimate_s"]) > MAX_FRAME_AGE_S:
            depth_why = "depth frame older than the common judging time allows"
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
    failure = why or side_why or depth_why or bad_target or stale or missing_before
    if failure:
        return {**out, "basis": f"unverified: {failure}"}
    place = {k: target[k] for k in ("area", "col", "row", "tier") if k in target}
    if not has_side:
        # The same before/after test as the top part of the two-camera check: the zone is occupied now and filled up since before.
        top_roi = tuple(target["roi"])
        after_zone = evaluate_zone(top["image"], top_roi, tol_u_px=24.0, tol_v_px=40.0, min_fill=0.15)
        before_zone = evaluate_zone(before_frame["image"], top_roi, min_fill=0.15)
        grown = float(after_zone.get("fill_ratio") or 0.0) - float(before_zone.get("fill_ratio") or 0.0) >= 0.15
        out["top"].update(zone=_plain(after_zone), before_zone=_plain(before_zone))
        return _plain({**out, "basis": TOP_ONLY_BASIS, "verified": bool(after_zone.get("within_zone") and grown)})
    pick = {"area": (config.get("sites") or {}).get(source_site, {}).get("area") or source_site.rsplit("-l", 1)[0]}
    verify = verify_stack_outcome_z_mm if target["area"] == "pallet" else verify_stack_outcome
    extra = {"after_depth": depth, "z_profile": config.get("z_profile")} if target["area"] == "pallet" else {}
    stack = verify(before_side=before_side_frame["image"], after_side=side["image"], before_top=before_frame["image"],
                   after_top=top["image"], pick=pick, place=place, strict_target=True, **extra)
    top_zone = (stack.get("place_slot") or {}).get("top_zone")
    # verify_stack_outcome leaves top_orientation_ok True when it measured nothing on top: an unmeasured top zone is not verified.
    top_ok = bool(isinstance(top_zone, dict) and top_zone.get("within_zone") and top_zone.get("orientation_ok") is True)
    return _plain({**out, **stack, "verified": bool(stack.get("verified")) and top_ok,
                   "top": {**out["top"], "zone": top_zone}})
