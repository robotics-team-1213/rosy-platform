#!/usr/bin/env python3
"""Belt container pose for an ACT checkpoint that takes it as input (Panel L, 2026-11-27).

The checkpoint's observation.environment_state ends with BELT_NAMES: the container's offset from the nominal belt site in
the sim fixture frame, (x m / 0.01, y m / 0.01, long-axis yaw rad / 0.2), the yaw folded into +-90 deg. It is measured once
from one top frame before the run (arm home) and held for the episode, as the sim data holds it (make_panel_l.py,
eval_panel_l.py). The frame is read through the bundle's own top camera model (the sim pinhole the training views were
rendered with, ENV_STATE.json belt_reference.top_camera) onto the container top above the belt, so the result is in the
fixture frame directly: no arm frame, no cell calibration map. The nominal site is the sim's: omx_two_arm_sites.Layout(preset)
.sites["belt"] (belt stop and centreline from the 11-14 top photo, BELT_PHOTO_1114, through the same kind of camera model).
Detection reuses omx_real2sim (blobs, lane_blobs). A missing reference, a failed read, no container, two or more, or a
container-coloured blob that is not the trained container is BELT_POSE_UNKNOWN; a value past the training range plus a
margin is BELT_POSE_OUT_OF_RANGE. Neither is clamped; either refuses the run before any motion."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import sys

BELT_NAMES = ("belt_dx_cm", "belt_dy_cm", "belt_yaw_x5")
SCALE = (0.01, 0.01, 0.2)  # m, m, rad per feature unit (make_panel_l.py)
# Panel L/I collection: x -1..+13 mm, y +-8 mm, yaw +-12 deg; the gate adds 1 mm / 1 deg (task spec 2026-11-27)
RANGE = ((-0.002, 0.014), (-0.009, 0.009), (-math.radians(13.0), math.radians(13.0)))
NEAR_M = 0.06  # a container-coloured blob this close to the belt site is a belt container
SITE_TOL = (0.0005, math.radians(0.5))  # declared belt site vs this checkout's Layout
UNKNOWN, OUT_OF_RANGE = "BELT_POSE_UNKNOWN", "BELT_POSE_OUT_OF_RANGE"
CAMERA_KEYS = ("eye", "focus", "up", "f_px", "width", "height")


def _refuse(code: str, reason: str, **evidence) -> dict:
    return {"ok": False, "reason_code": code, "reason": reason, **evidence}


def _reference(doc) -> tuple[dict, str, dict | None]:
    """(top camera, preset, declared belt site) from ENV_STATE.json belt_reference; ValueError names what is missing."""
    if not isinstance(doc, dict):
        raise ValueError("checkpoint ENV_STATE.json has no belt_reference")
    preset, cam = doc.get("preset"), doc.get("top_camera")
    if not isinstance(preset, str) or not preset:
        raise ValueError("belt_reference.preset (the sim layout the data was collected in) is missing")
    if not isinstance(cam, dict) or any(key not in cam for key in CAMERA_KEYS):
        raise ValueError(f"belt_reference.top_camera needs {', '.join(CAMERA_KEYS)}")
    flat = [*cam["eye"], *cam["focus"], *cam["up"], cam["f_px"], cam["width"], cam["height"]]
    if len(flat) != 12 or not all(type(v) in (int, float) and math.isfinite(v) for v in flat) or cam["f_px"] <= 0:
        raise ValueError("belt_reference.top_camera is not a finite pinhole")
    site = doc.get("belt_site")
    if site is not None and not (isinstance(site, dict) and len(site.get("xy") or ()) == 2
                                 and all(type(v) in (int, float) for v in (*site["xy"], site.get("yaw")))):
        raise ValueError("belt_reference.belt_site must be {xy: [x, y], yaw}")
    return cam, preset, site


def measure(frame, reference) -> dict:
    """One BGR top frame -> {ok, features, ...evidence} or a refusal {ok: False, reason_code, reason, ...}."""
    try:
        cam_doc, preset, declared = _reference(reference)
    except ValueError as error:
        return _refuse(UNKNOWN, f"NOT_AVAILABLE: {error}")
    if frame is None or getattr(frame, "ndim", 0) != 3 or frame.shape[2] != 3:
        return _refuse(UNKNOWN, "no top frame")
    if tuple(frame.shape[:2]) != (int(cam_doc["height"]), int(cam_doc["width"])):
        return _refuse(UNKNOWN, f"top frame {frame.shape[1]}x{frame.shape[0]} is not the reference camera's "
                                f"{cam_doc['width']}x{cam_doc['height']}")
    sim_tools = str(Path(__file__).resolve().parents[3] / "tools/sim")
    if sim_tools not in sys.path:
        sys.path.insert(0, sim_tools)
    import omx_two_arm_sites as sites
    from omx_real2sim_helpers import LANE, SIZE_TOL, Camera, blobs, fold, lane_blobs, rect

    try:
        layout = sites.Layout(preset=preset)
    except (KeyError, ValueError) as error:
        return _refuse(UNKNOWN, f"NOT_AVAILABLE: sim preset {preset!r}: {error}")
    site = layout.sites["belt"]
    if declared is not None and (math.dist(declared["xy"], site["xy"]) > SITE_TOL[0]
                                 or abs(fold(declared["yaw"] - site["yaw"])) > SITE_TOL[1]):
        return _refuse(UNKNOWN, f"NOT_AVAILABLE: trained belt site {declared} differs from this checkout's "
                                f"{preset} site {site['xy']}, yaw {site['yaw']}")
    box_h = sites.CONTAINER[layout.choices["ship_source"]][2]
    cam = Camera(cam_doc, frame.shape[:2])
    evidence = {"frame_sha256": hashlib.sha256(frame.tobytes()).hexdigest(), "preset": preset,
                "belt_site_mm": [round(v * 1000, 1) for v in site["xy"]]}
    near = lambda xy: math.dist(xy, site["xy"]) < NEAR_M  # noqa: E731
    seen = [rect(cam.to_plane(px, layout.belt_top + box_h)) for kind, px in blobs(frame) if kind == "container"]
    seen = [s for s in seen if near(s[0])]
    found = [b for b in lane_blobs(frame, cam, layout.belt_top, box_h) if b["kind"] == "container" and near(b["xy"])]
    if not seen:
        return _refuse(UNKNOWN, "no container at the belt end in the top frame", **evidence)
    if len(seen) != len(found) or any(b["partial"] for b in found):
        return _refuse(UNKNOWN, "a container-coloured blob at the belt end is not the trained container footprint "
                                f"{[[round(v * 1000, 1) for v in s[2]] for s in seen]} mm", **evidence)
    if len(found) > 1:
        return _refuse(UNKNOWN, f"{len(found)} containers at the belt end", **evidence)
    b = found[0]
    offset = (b["xy"][0] - site["xy"][0], b["xy"][1] - site["xy"][1], fold(b["yaw"] - site["yaw"]))
    # score: 1 at the trained footprint, 0 at lane_blobs' own acceptance edge
    size_err = (abs(b["size"][0] - LANE[0]) / SIZE_TOL[0], abs(b["size"][1] - LANE[1]) / (SIZE_TOL[1] + 0.004))
    evidence.update(centre_mm=[round(v * 1000, 1) for v in b["xy"]], offset_mm=[round(v * 1000, 1) for v in offset[:2]],
                    yaw_deg=round(math.degrees(offset[2]), 1), size_mm=[round(v * 1000, 1) for v in b["size"]],
                    score=round(max(0.0, 1.0 - max(size_err)), 3),
                    features=[round(v / s, 4) for v, s in zip(offset, SCALE)], names=list(BELT_NAMES))
    outside = [name for name, v, (lo, hi) in zip(BELT_NAMES, offset, RANGE) if not lo <= v <= hi]
    if outside:
        return _refuse(OUT_OF_RANGE, f"{', '.join(outside)} past the training range (dx -2..14 mm, dy +-9 mm, "
                                     f"yaw +-13 deg): offset {evidence['offset_mm']} mm, yaw {evidence['yaw_deg']} deg",
                       **evidence)
    return {"ok": True, **evidence}


def measure_cell(cell, reference, max_age_s: float = 2.0) -> dict:
    """A fresh top frame (source-stamped receipt when the cell has one) through measure(); a camera error, an old or
    unstamped frame reads as unknown, never as a pose."""
    try:
        if hasattr(cell, "frame_receipt"):
            receipt = cell.frame_receipt("top", max_age_s=max_age_s, timeout_s=3.0)
            frame, source = receipt["image"], {"source_seq": receipt.get("source_seq"), "source_stamp": receipt.get("source_stamp")}
        else:
            frame, source = cell.frame("top"), {}
    except Exception as error:  # noqa: BLE001 - any camera failure is a refusal, not a crash mid-start
        return _refuse(UNKNOWN, f"top camera: {str(error)[:120]}")
    return {**measure(frame, reference), **source}
