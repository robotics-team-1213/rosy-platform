"""Fresh camera evidence used before an OMX automatic transfer."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import uuid

import numpy as np

import cell_params as prm
import cell_attempts
from cell_auto_pick_plan import observe, save_frame_receipt
from cell_observe import predicted_pixel
import cell_pivot
import cell_scene_guard
import cell_site_track


def bound_map_error(bound, config, reference_bytes):
    """Check the reference and map as one stored calibration generation."""
    if not all(isinstance(bound.get(key), str) for key in (
            "reference_top_sha256", "reference_map_sha", "reference_geometry_sha")):
        return "top camera map binding unavailable"
    if hashlib.sha256(reference_bytes).hexdigest() != bound["reference_top_sha256"]:
        return "top camera map reference changed"
    if cell_attempts.digest(bound.get("sites")) != bound["reference_map_sha"]:
        return "top camera calibration changed"
    geometry = {name: {key: site.get(key) for key in ("auto_roi", "surface_px", "map_from")}
                for name, site in config["sites"].items() if not site.get("tier_of")}
    if cell_attempts.digest(geometry) != bound["reference_geometry_sha"]:
        return "top camera map site geometry changed"
    return None


def bound_reference_image(calibration, config, ref_path):
    """Read the exact bound JPEG before a map repair can publish a new generation."""
    import cv2

    try:
        raw = ref_path.read_bytes() if ref_path else b""
    except OSError:
        raw = b""
    error = bound_map_error(calibration, config, raw)
    if error:
        return None, error
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
    return (image, None) if image is not None else (None, "reference unavailable; remap required")


def map_pose_preflight(cell, config, calibration, calibration_path: Path, work: Path, dry_run, out):
    """Hold hardware before planning if the live top JPEG disagrees with the map reference."""
    if dry_run:
        return None
    state = cell.act("state")
    if not isinstance(state, dict) or state.get("ok") is not True:
        return "state unavailable before camera map check"
    if (state.get("operating_context") or {}).get("scope") != "hardware":
        return None  # explicit simulation; Gate still checks its operating context before motion
    import cv2
    import cell_preflight

    try:
        receipt = cell.frame_receipt("top")
        out["map_pose_frame"] = save_frame_receipt(work / "frames" / f"{uuid.uuid4().hex}-map-pose.jpg", receipt)
        ref_path = (config.get("preflight") or {}).get("reference_top")
        reference_bytes = Path(ref_path).expanduser().read_bytes() if ref_path else b""
        reference = (cv2.imdecode(np.frombuffer(reference_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
                     if reference_bytes else None)
        if reference is None:
            return "top camera map reference unavailable"
        bound = json.loads(Path(calibration_path).read_text(encoding="utf-8"))
        error = bound_map_error(bound, config, reference_bytes)
        if error:
            return error
        active_sites = {name: site for name, site in calibration["sites"].items()
                        if not (config["sites"].get(name) or {}).get("tier_of")}
        if cell_attempts.digest(active_sites) != bound["reference_map_sha"]:
            return "top camera calibration changed"
        for name, site in config["sites"].items():
            parent = site.get("tier_of")
            if parent:
                base = (config["sites"].get(parent) or {}).get("map_from", parent)
                if calibration["sites"].get(name) != calibration["sites"].get(base):
                    return "top camera calibration changed"
        image = cv2.cvtColor(receipt["image"], cv2.COLOR_BGR2GRAY)
        shift = cell_preflight.camera_shift_px(reference, image)
        out["map_pose_check"] = shift
        if not shift.get("ok") or shift.get("max_px", float("inf")) > prm.get(
                config.get("params"), "calibrate.max_shift_px"):
            return "top camera moved since map reference"
    except (AttributeError, OSError, ValueError, KeyError, TypeError, cv2.error):
        return "top camera map check unavailable"
    return None


def bias_map_error(config, calibration, bias_data, site, xy):
    """A stored hardware bias must name the exact currently loaded site map."""
    region = cell_pivot.bias_at(bias_data, site, xy, params=config.get("params"))
    if region is None:
        return None
    record = cell_pivot.map_record(calibration, site)
    if record is None or region.get("map_sha") != cell_attempts.digest(record):
        return "stored pivot bias belongs to another map"
    return None


def track_sites(cell, config, calibration, source, dest, roi, work: Path, dry_run, out):
    """Track moving sites using a saved source frame for each non-simulated update."""
    for site in {source, dest} & {k for k, v in config["sites"].items() if v.get("track")}:
        if dry_run:
            image = cell.frame("top")
        else:
            try:
                receipt = cell.frame_receipt("top")
                out.setdefault("track_frames", {})[site] = save_frame_receipt(
                    work / "frames" / f"{uuid.uuid4().hex}-track-{site}.jpg", receipt)
                image = receipt["image"]
            except (AttributeError, OSError, ValueError, KeyError, TypeError):
                return config, roi, f"held: {site}: fresh tracking frame unavailable"
        config, out[f"track_{site}"] = cell_site_track.follow(
            config, site, image, lambda q, s=site: predicted_pixel(config, calibration, s, q), work)
        if not out[f"track_{site}"]["tracked"]:
            return config, roi, f"refused: {site}: {out[f'track_{site}'].get('why')}"
        roi = config["sites"][site]["auto_roi"] if site == source else roi
    return config, roi, None


def source_frame(cell, path: Path):
    receipt_fn = getattr(cell, "frame_receipt", None)
    try:
        receipt = receipt_fn("top") if callable(receipt_fn) else None
        if receipt is None:
            raise ValueError("fresh camera source unavailable")
        return receipt, save_frame_receipt(path, receipt), None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, None, str(exc)


def destination_view(cell, config, calibration, dest_site, dest_roi, source, catalog, image):
    if dest_roi is None or dest_site == source:
        return None, None
    _, mask, _, error = observe(cell, config, calibration, dest_site, dest_roi, catalog, image=image)
    return (None if error else (mask, dest_roi)), error


def scene_guard(guarded, config, calibration, source, roi, source_xy, image):
    return cell_scene_guard.hook(
        guarded, config, image, roi,
        predicted_pixel(config, calibration, source, (0.0, 0.0)),
        predicted_pixel(config, calibration, source, source_xy))


def pre_motion_frame(cell, config, calibration, catalog, source, source_roi, source_xy,
                     object_id, dest_site, dest_roi, place_xy, bias_data, source_frame, path: Path):
    """Bind pick and free destination to the same advancing, persisted JPEG."""
    frame_receipt = getattr(cell, "frame_receipt", None)
    try:
        before = frame_receipt("top", previous=source_frame)
        frame = save_frame_receipt(path, before)
    except (OSError, ValueError, KeyError, TypeError):
        return None, None, "fresh camera frame unavailable"
    _, _, current_source, error = observe(cell, config, calibration, source, source_roi, catalog,
                                          image=before["image"])
    tolerance = min(5.0, float(config.get("verify_tol_mm", 10.0)))
    if error or not any(seen.get("object") == object_id and
                        1000 * math.dist(seen["raw_m"], source_xy) <= tolerance for seen in current_source):
        return before, frame, "source moved before transfer"
    record = cell_pivot.map_record(calibration, dest_site)
    if dest_roi is None or record is None or "z_view" in record:
        return before, frame, "destination ROI or fine map missing"
    _, _, current_dest, error = observe(cell, config, calibration, dest_site, dest_roi, catalog,
                                        image=before["image"])
    region = cell_pivot.bias_at(bias_data, dest_site, place_xy, params=config.get("params"))
    bx, by = region["bias_mm"] if region else (0.0, 0.0)
    if error or any(1000 * math.dist((seen["raw_m"][0] - bx / 1000,
                                      seen["raw_m"][1] - by / 1000), place_xy)
                    <= config.get("verify_tol_mm", 10.0) for seen in current_dest):
        return before, frame, "destination unavailable or occupied"
    return before, frame, None
