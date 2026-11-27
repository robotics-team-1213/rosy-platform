#!/usr/bin/env python3
"""Belt container pose for an ACT checkpoint that takes it as input (Panel L, 2026-11-27).

The checkpoint's observation.environment_state ends with BELT_NAMES: the container's offset from the nominal belt site in
the sim fixture frame, (x m / 0.01, y m / 0.01, long-axis yaw rad / 0.2), the yaw folded into +-90 deg. It is measured once
from one top frame before the run (arm home) and held for the episode, as the sim data holds it (make_panel_l.py,
eval_panel_l.py). Everything the reading needs comes from the checkpoint's ENV_STATE.json belt_reference, written at
training time by tools/sim/omx_env_state.py from the sim layout: the top camera model the training views were rendered
with, the belt site (omx_two_arm_sites.Layout(preset).sites["belt"]), the belt top height, the container size and the
footprint tolerances. The frame is back-projected through that camera onto the container top, so the result is in the
fixture frame directly: no arm frame, no cell calibration map, no tools/sim on the cell (cell_belt_vision is the cell copy
of the omx_real2sim detection). A missing reference, a failed read, no container, two or more, or a container-coloured blob
that is not the trained container is BELT_POSE_UNKNOWN; a value past the training range plus a margin is
BELT_POSE_OUT_OF_RANGE. Neither is clamped; either refuses the run before any motion.

The range is RANGE unless the bundle's belt_reference.range = {"dx_m": [lo, hi], "dy_m": [lo, hi], "yaw_rad": [lo, hi]}
declares the trained range plus margin (a newer training set, e.g. Panel N). A declared range that is malformed or past
CEILING is refused (NOT_AVAILABLE), never replaced by RANGE."""
from __future__ import annotations

import hashlib
import math

BELT_NAMES = ("belt_dx_cm", "belt_dy_cm", "belt_yaw_x5")
SCALE = (0.01, 0.01, 0.2)  # m, m, rad per feature unit (make_panel_l.py)
# Panel L/I collection: x -1..+13 mm, y +-8 mm, yaw +-12 deg; the gate adds 1 mm / 1 deg (task spec 2026-11-27)
RANGE = ((-0.002, 0.014), (-0.009, 0.009), (-math.radians(13.0), math.radians(13.0)))
# hard ceiling a bundle-declared range may not exceed: dx, |dy|, |yaw| (a bundle cannot widen the gate past this)
CEILING = ((-0.01, 0.04), (-0.035, 0.035), (-math.radians(20.0), math.radians(20.0)))
RANGE_KEYS = ("dx_m", "dy_m", "yaw_rad")
NEAR_M = 0.06  # a container-coloured blob this close to the belt site is a belt container
UNKNOWN, OUT_OF_RANGE = "BELT_POSE_UNKNOWN", "BELT_POSE_OUT_OF_RANGE"
CAMERA_KEYS = ("eye", "focus", "up", "f_px", "width", "height")


def _refuse(code: str, reason: str, **evidence) -> dict:
    return {"ok": False, "reason_code": code, "reason": reason, **evidence}


def _numbers(value, n: int, what: str, positive: bool = False) -> list[float]:
    vals = list(value) if isinstance(value, (list, tuple)) else None
    if (vals is None or len(vals) != n or not all(type(v) in (int, float) and math.isfinite(v) for v in vals)
            or (positive and min(vals) <= 0)):
        raise ValueError(f"belt_reference.{what} needs {n} finite{' positive' if positive else ''} numbers")
    return [float(v) for v in vals]


def _range(declared) -> tuple:
    """RANGE when the bundle declares none, else the declared (lo, hi) per axis; ValueError when malformed or past CEILING."""
    if declared is None:
        return RANGE
    if not isinstance(declared, dict) or set(declared) != set(RANGE_KEYS):
        raise ValueError(f"belt_reference.range needs exactly {', '.join(RANGE_KEYS)}")
    out = tuple(tuple(_numbers(declared[k], 2, f"range.{k}")) for k in RANGE_KEYS)
    for key, (lo, hi), (c_lo, c_hi) in zip(RANGE_KEYS, out, CEILING):
        if not c_lo <= lo <= hi <= c_hi:
            raise ValueError(f"belt_reference.range.{key} [{lo}, {hi}] must be lo <= hi inside the ceiling [{c_lo:.4f}, {c_hi:.4f}]")
    return out


def _reference(doc) -> dict:
    """The belt_reference fields as numbers; ValueError names what is missing (the run is then NOT_AVAILABLE)."""
    if not isinstance(doc, dict):
        raise ValueError("checkpoint ENV_STATE.json has no belt_reference")
    cam, site, box, tol = (doc.get(k) or {} for k in ("top_camera", "belt_site", "container", "footprint_tol_m"))
    if not isinstance(cam, dict) or any(key not in cam for key in CAMERA_KEYS):
        raise ValueError(f"belt_reference.top_camera needs {', '.join(CAMERA_KEYS)}")
    _numbers([*cam["eye"], *cam["focus"], *cam["up"]], 9, "top_camera eye/focus/up")
    _numbers([cam["f_px"], cam["width"], cam["height"]], 3, "top_camera f_px/width/height", positive=True)
    return {"camera": cam, "preset": doc.get("preset"),
            "site_xy": _numbers(site.get("xy"), 2, "belt_site.xy"), "site_yaw": _numbers([site.get("yaw")], 1, "belt_site.yaw")[0],
            "belt_top": _numbers([doc.get("belt_top_m")], 1, "belt_top_m")[0],
            "box": _numbers([box.get(k) for k in ("length_m", "width_m", "height_m")], 3, "container", positive=True),
            "range": _range(doc.get("range")),
            "tol": _numbers([tol.get(k) for k in ("length", "width", "partial_min")], 3, "footprint_tol_m", positive=True)}


def measure(frame, reference) -> dict:
    """One BGR top frame -> {ok, features, ...evidence} or a refusal {ok: False, reason_code, reason, ...}."""
    try:
        ref = _reference(reference)
    except (ValueError, TypeError, AttributeError) as error:
        return _refuse(UNKNOWN, f"NOT_AVAILABLE: {error}")
    cam_doc, site_xy = ref["camera"], ref["site_xy"]
    if frame is None or getattr(frame, "ndim", 0) != 3 or frame.shape[2] != 3:
        return _refuse(UNKNOWN, "no top frame")
    if tuple(frame.shape[:2]) != (int(cam_doc["height"]), int(cam_doc["width"])):
        return _refuse(UNKNOWN, f"top frame {frame.shape[1]}x{frame.shape[0]} is not the reference camera's "
                                f"{cam_doc['width']}x{cam_doc['height']}")
    from cell_belt_vision import Camera, containers, fold

    box, tol = ref["box"], ref["tol"]
    evidence = {"frame_sha256": hashlib.sha256(frame.tobytes()).hexdigest(), "preset": ref["preset"],
                "belt_site_mm": [round(v * 1000, 1) for v in site_xy]}
    near = lambda xy: math.dist(xy, site_xy) < NEAR_M  # noqa: E731
    seen, found = containers(frame, Camera(cam_doc, frame.shape[:2]), ref["belt_top"], box, tol)
    seen, found = [s for s in seen if near(s[0])], [b for b in found if near(b["xy"])]
    if not seen:
        return _refuse(UNKNOWN, "no container at the belt end in the top frame", **evidence)
    if len(seen) != len(found) or any(b["partial"] for b in found):
        return _refuse(UNKNOWN, "a container-coloured blob at the belt end is not the trained container footprint "
                                f"{[[round(v * 1000, 1) for v in s[2]] for s in seen]} mm", **evidence)
    if len(found) > 1:
        return _refuse(UNKNOWN, f"{len(found)} containers at the belt end", **evidence)
    b = found[0]
    offset = (b["xy"][0] - site_xy[0], b["xy"][1] - site_xy[1], fold(b["yaw"] - ref["site_yaw"]))
    # score: 1 at the trained footprint, 0 at the footprint tolerance edge
    size_err = (abs(b["size"][0] - box[0]) / tol[0], abs(b["size"][1] - box[1]) / tol[1])
    evidence.update(centre_mm=[round(v * 1000, 1) for v in b["xy"]], offset_mm=[round(v * 1000, 1) for v in offset[:2]],
                    yaw_deg=round(math.degrees(offset[2]), 1), size_mm=[round(v * 1000, 1) for v in b["size"]],
                    score=round(max(0.0, 1.0 - max(size_err)), 3),
                    features=[round(v / s, 4) for v, s in zip(offset, SCALE)], names=list(BELT_NAMES))
    lim = ref["range"]
    outside = [name for name, v, (lo, hi) in zip(BELT_NAMES, offset, ref["range"]) if not lo <= v <= hi]
    if outside:
        return _refuse(OUT_OF_RANGE, f"{', '.join(outside)} past the training range (dx {lim[0][0] * 1000:.1f}..{lim[0][1] * 1000:.1f} mm, "
                                     f"dy {lim[1][0] * 1000:.1f}..{lim[1][1] * 1000:.1f} mm, yaw {math.degrees(lim[2][0]):.1f}.."
                                     f"{math.degrees(lim[2][1]):.1f} deg): offset {evidence['offset_mm']} mm, yaw {evidence['yaw_deg']} deg",
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
