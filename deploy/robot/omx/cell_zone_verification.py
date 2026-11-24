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
import re
import time

import numpy as np
from typing import Any

from cell_area_zones import evaluate_zone, verify_stack_outcome, verify_stack_outcome_z_mm
import cell_depth_lock
import cell_site_target

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


def _frame(source, camera: str, previous: dict | None = None, after: float | None = None, deadline: float | None = None):
    """(receipt, None) of a frame captured at or after `after`, else (None, reason).

    `deadline` (wall time; default now + FRAME_WAIT_S) is one hard limit for all the reads that share it: each socket gets only
    the time that is left, and a read that returns after it is refused."""
    deadline = time.time() + FRAME_WAIT_S if deadline is None else deadline
    reason = "no frame"
    prev_arg = None if isinstance(previous, dict) and previous.get("_reused") else previous
    while True:
        try:
            left = deadline - time.time()
            if left <= 0.02:
                return None, f"{camera} frame read exceeded the {FRAME_WAIT_S} s limit" + ("" if reason == "no frame" else f" ({reason})")
            receipt = source.frame_receipt(camera, previous=prev_arg, max_age_s=MAX_FRAME_AGE_S, timeout_s=left)
            if time.time() > deadline:
                return None, f"{camera} frame read took longer than {FRAME_WAIT_S} s"
            if after is None or float(receipt["source_stamp"]) >= after:
                return receipt, None
            reason = f"{camera} frame was captured before the placement finished"
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            reason = f"{camera} frame unavailable: {exc}"
        if time.time() >= deadline:
            return None, reason
        time.sleep(min(0.05, max(0.0, deadline - time.time())))


def _stamp(receipt: dict) -> dict:
    return {k: receipt.get(k) for k in ("camera", "source_seq", "source_stamp", "captured_at", "jpeg_sha256")}


def zone_check_enabled(config: dict) -> bool:
    """True when placement zone verification is required (Fleet task or direct `--verify-zones`)."""
    return bool(config.get("_fleet_task") or config.get("_verify_zones"))


def _depth_after(config: dict, after: float):
    """(depth map, receipt, None) of the pallet depth after `after`, else (None, None, reason).

    `config["depth_frames"]` (default 5, 1-9) consecutive Z16 frames are taken in one stream inside DEPTH_BURST_S and reduced
    to the per-pixel median (more than half of the frames must be valid at a pixel), which lowers the frame noise of the
    relative height. One frame uses the existing single-frame capture. Nothing else about the depth source changes.
    """
    import tempfile

    import cell_depth
    import cell_depth_slots

    top = (config.get("cameras") or {}).get("top") or {}
    device = top.get("depth_device") or DEPTH_DEVICE
    n = config.get("depth_frames", 5)
    if type(n) is not int or not 1 <= n <= 9:
        return None, None, "depth_frames must be an integer from 1 to 9"
    try:
        with cell_depth_lock.hold_depth_lock(timeout_s=DEPTH_WAIT_S):
            with tempfile.TemporaryDirectory(prefix="zone-depth-") as scratch:  # raw frames, receipt and lock go with the directory
                if n == 1:
                    got = cell_depth.capture_top_depth_z16_receipt(device, Path(scratch) / "depth.raw", timeout_s=DEPTH_WAIT_S)
                    got = None if got is None else (np.array(got[0]), dict(got[1]))
                else:
                    frames, receipt = cell_depth_slots.capture_depth_frames(device, n, Path(scratch) / "depth.raw")
                    if frames is None:
                        return None, None, receipt
                    depth, valid = cell_depth_slots.median_depth(frames)
                    got = (depth, {**receipt, "valid_depth_ratio": valid, "source_seq": receipt["source_seq_last"], "reduction": "median"})
    except TimeoutError:
        return None, None, "depth-d435.lock busy"
    except (OSError, ValueError) as exc:
        return None, None, f"depth capture failed: {exc}"
    if got is None:
        return None, None, "depth capture unavailable"
    depth, receipt = got
    if float(receipt.get("first_exposure_wall_estimate_s", receipt.get("exposure_wall_estimate_s", 0.0))) < after:
        return None, None, "depth frame was exposed before the placement finished"  # the first kept frame of a burst, too
    return depth, receipt, None


def before_side(cell, config: dict) -> dict | None:
    """The side frame to take with the before top frame, or None (no side camera, or no frame: the two-camera basis is then
    not available)."""
    source = getattr(cell, "cell", cell)
    with _side_camera(source, config) as has_side:
        return _frame(source, "side")[0] if has_side else None


def _save_before(config: dict, before_frame: dict | None) -> dict | None:
    """Keep the before frames (JPEG, relative names) in the work directory so a stale result can be measured again later."""
    import cv2

    task = config.get("_fleet_task")
    if (not isinstance(task, str) or not task) and config.get("_verify_zones"):
        task = "direct"
    if not isinstance(task, str) or not task or before_frame is None or not config.get("work_dir"):
        return None
    folder = Path(config["work_dir"]).expanduser() / "zone-before"
    names = {}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for key, image in (("top", before_frame.get("image")), ("side", (before_frame.get("before_side") or {}).get("image"))):
            if image is not None and cv2.imwrite(str(folder / f"{task}-{key}.jpg"), image):
                names[key] = f"{task}-{key}.jpg"
    except OSError:
        return None
    return names or None


def record(row: dict, tried: dict, cell, before_frame, config, dest_site, source_site, roi) -> None:
    """Measure, then put verify, transfer and zone_verification on the attempt row: cell_task_exec reads that row, which
    kept none of them before (they went only to the attempts ledger)."""
    # Fleet tasks and `--verify-zones` `:8781` runs record zone verification; other carries skip the extra reads.
    tried["zone_verification"] = (measure(cell, before_frame, config, dest_site, source_site, roi) if zone_check_enabled(config)
                                  else {"basis": "unverified: not a Fleet task", "verified": False})
    row.update(verify=tried["verify"], zone_verification=tried["zone_verification"], transfer=tried["transfer"])


def _zone_rois(config: dict):
    """(zone_rois or None, None) from the cell config's `zone_rois`, or (None, reason) when it is malformed. A malformed
    override refuses the measurement instead of falling back to the shared tables."""
    raw = config.get("zone_rois")
    if raw is None:
        return None, None
    shapes = {"top": re.compile(r"(?:c[1-3]r[1-2]|stand|ship-h[12]r[0-2]|tmp-[ab]-[1-3])\Z"), "side": re.compile(r"c[1-3]t[1-3]\Z")}
    if not isinstance(raw, dict) or set(raw) - set(shapes) - {"floor", "floor_depth_mm"}:
        return None, "zone_rois must be an object with top, side and floor tables"

    def valid(roi) -> bool:
        return (isinstance(roi, list) and len(roi) == 4 and all(type(v) is int for v in roi)
                and 0 <= roi[0] < roi[2] <= 640 and 0 <= roi[1] < roi[3] <= 480)

    floor = raw.get("floor")
    if floor is not None and (not isinstance(floor, list) or not floor or not all(valid(r) for r in floor)):
        return None, "zone_rois.floor must be a list of [x1,y1,x2,y2] pallet floor ROIs"
    depths = raw.get("floor_depth_mm")
    if floor is not None and (not isinstance(depths, list) or len(depths) != len(floor)
                              or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in depths)):
        return None, "zone_rois.floor_depth_mm must record the floor depth (mm) of every floor patch"
    for kind, table in raw.items():
        if kind in ("floor", "floor_depth_mm"):
            continue
        if not isinstance(table, dict):
            return None, f"zone_rois.{kind} must be an object"
        for key, roi in table.items():
            if (not shapes[kind].match(str(key)) or not isinstance(roi, list) or len(roi) != 4
                    or any(type(v) is not int for v in roi) or not (0 <= roi[0] < roi[2] <= 640 and 0 <= roi[1] < roi[3] <= 480)):
                return None, f"zone_rois.{kind}.{key} is not a valid [x1,y1,x2,y2] in the 640x480 frame"
    return raw, None


def _target(config: dict, dest_site: str):
    """(target dict, None) from the destination site's own layer/col/row, or (None, reason). No default slot or tier."""
    canon = cell_site_target.resolve_cell_ab_site(dest_site, None, allow_belt_temp=False)
    site_map = config.get("sites") or {}
    if canon is not None and not canon["is_legacy_pallet"]:
        site = site_map.get(dest_site)
        if not isinstance(site, dict):
            return None, f"destination site {dest_site!r} not in the site config"
        layer = site.get("layer")
        implicit_t1 = (layer is None and canon["tier"] == 1 and dest_site == canon["base_site"]
                       and "place" in site and "surface_z" in site)
        if not implicit_t1 and (type(layer) is not int or layer != canon["tier"] - 1):
            return None, "destination layer missing or disagrees with canonical tier"
        if (("col" in site and (type(site["col"]) is not int or site["col"] != canon["col"]))
                or ("row" in site and (type(site["row"]) is not int or site["row"] != canon["row"]))
                or ("tier" in site and (type(site["tier"]) is not int or site["tier"] != canon["tier"]))):
            return None, "site col/row/tier disagrees with canonical site"
        return {
            "site": dest_site, "site_id": canon["site_id"], "base_site": canon["base_site"],
            "area": canon["area"], "col": canon["col"], "row": canon["row"], "tier": canon["tier"],
        }, None
    site = site_map.get(dest_site) or {}
    area_raw = dest_site.split(":", 1)[0].rsplit("-l", 1)[0]
    area = "belt" if area_raw == "belt_center" else area_raw
    single_slot = area in ("stand", "temp_plate_a", "temp_plate_b") and bool(site)
    layer = site.get("layer", 0 if single_slot else None)
    col = site.get("col", 1 if single_slot else None)
    row = site.get("row", 1 if single_slot else None)
    if type(layer) is not int or layer not in LAYERS:
        return None, "destination layer not in the site config or outside 0-2"
    if type(col) is not int or col not in SLOT_COLS or type(row) is not int or row not in SLOT_ROWS:
        return None, "target slot col/row not in the site config (real cell configs name only the site place xy) or outside 1-3/1-2"
    if "tier" in site and site["tier"] != layer + 1:
        return None, "site tier and layer disagree"
    return {"site": dest_site, "area": area, "col": col, "row": row, "tier": layer + 1}, None


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
                           "before_frames": _save_before(config, before_frame),
                           "side": {"available": False, "reason": "no side camera in this cell"}}
    # The Z16 capture (slow, so it goes first and the RGB frames taken after it stay fresh) is taken only when the cell config
    # has floor ROIs: that is the one case where the zone check uses it.
    rois, bad_rois = _zone_rois(config)
    depth = depth_receipt = depth_why = None
    dest_canon = cell_site_target.resolve_cell_ab_site(dest_site, None, allow_belt_temp=True)
    dest_area = dest_canon["area"] if (dest_canon and not dest_canon["is_legacy_pallet"]) else dest_site.rsplit("-l", 1)[0]
    if rois is not None and rois.get("floor") and dest_area in cell_site_target.STACKING_AREAS:
        depth, depth_receipt, depth_why = _depth_after(config, placed_at)
    rgb_deadline = time.time() + FRAME_WAIT_S  # one limit for the whole RGB read, top and side together
    top, why = _frame(source, "top", before_frame, placed_at, rgb_deadline)
    with _side_camera(source, config) as has_side:
        side, side_why = _frame(source, "side", None, placed_at, rgb_deadline) if has_side else (None, None)
    target, bad_target = _target(config, dest_site) if has_side else _top_target(config, dest_site, roi)
    out["target"] = target
    judged_at = out["measured_at"] = time.time()
    if depth_receipt is not None:
        out["depth"] = {k: depth_receipt.get(k) for k in ("source_seq", "exposure_wall_estimate_s", "valid_depth_ratio", "raw_sha256")}
        if judged_at - float(depth_receipt.get("first_exposure_wall_estimate_s", depth_receipt["exposure_wall_estimate_s"])) > MAX_FRAME_AGE_S:
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
    slot_key = target and (target.get("base_site") or f"c{target.get('col')}r{target.get('row')}")
    no_slot_roi = (f"zone_rois.top has no cell-specific ROI for {slot_key}"
                   if has_side and rois is not None and rois.get("floor") and target and cell_site_target.top_slot_roi(rois, target) is None else None)
    failure = why or side_why or depth_why or bad_target or bad_rois or no_slot_roi or stale or missing_before
    if failure:
        return {**out, "basis": f"unverified: {failure}"}
    canon_fields = ("area", "col", "row", "tier", "base_site", "site") if "site_id" in target else ("area", "col", "row", "tier")
    place = {k: target[k] for k in canon_fields if k in target}
    if not has_side:
        # The same before/after test as the top part of the two-camera check: the zone is occupied now and filled up since before.
        top_roi = tuple(target["roi"])
        after_zone = evaluate_zone(top["image"], top_roi, tol_u_px=24.0, tol_v_px=40.0, min_fill=0.15)
        before_zone = evaluate_zone(before_frame["image"], top_roi, min_fill=0.15)
        grown = float(after_zone.get("fill_ratio") or 0.0) - float(before_zone.get("fill_ratio") or 0.0) >= 0.15
        out["top"].update(zone=_plain(after_zone), before_zone=_plain(before_zone))
        return _plain({**out, "basis": TOP_ONLY_BASIS, "verified": bool(after_zone.get("within_zone") and grown)})
    src_canon = cell_site_target.resolve_cell_ab_site(source_site, None, allow_belt_temp=True)
    pick_area = (config.get("sites") or {}).get(source_site, {}).get("area") or (
        src_canon["area"] if src_canon and not src_canon["is_legacy_pallet"] else source_site.rsplit("-l", 1)[0])
    pick = {"area": pick_area, **({"col": src_canon["col"], "row": src_canon["row"], "tier": src_canon["tier"]}
                                   if src_canon and not src_canon["is_legacy_pallet"] else {})}
    verify = verify_stack_outcome_z_mm if target["area"] in cell_site_target.STACKING_AREAS else verify_stack_outcome
    extra = {"after_depth": depth, "z_profile": config.get("z_profile")} if depth is not None else {}
    if rois is not None:
        extra["zone_rois"] = out["zone_rois"] = rois  # the cell's own zone table, for this check only
    stack = verify(before_side=before_side_frame["image"], after_side=side["image"], before_top=before_frame["image"],
                   after_top=top["image"], pick=pick, place=place, strict_target=True, **extra)
    top_zone = (stack.get("place_slot") or {}).get("top_zone")
    # verify_stack_outcome leaves top_orientation_ok True when it measured nothing on top: an unmeasured top zone is not verified.
    top_ok = bool(isinstance(top_zone, dict) and top_zone.get("within_zone") and top_zone.get("orientation_ok") is True)
    if stack.get("depth_reference") is not None:  # D-1057: with floor ROIs the depth map decides; colour/side are auxiliary
        top_ok = True
    z_gate = stack.get("z_gate") if "z_gate" in stack else ({"verdict": "NOT_APPLICABLE"} if target["area"] not in cell_site_target.STACKING_AREAS else None)
    return _plain({**out, **stack, **({"z_gate": z_gate} if z_gate is not None else {}),
                   "verified": bool(stack.get("verified")) and top_ok, "top": {**out["top"], "zone": top_zone}})
