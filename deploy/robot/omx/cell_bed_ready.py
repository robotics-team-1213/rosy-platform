#!/usr/bin/env python3
"""Cell S bed readiness from the top camera (D-1057 2-9): READY / NOT_READY / UNKNOWN, judged right before a claim.

Reads only: camera frames over the camera service (FifoCell.frame_receipt, no device is opened), the arm's last runner state,
the cell config and calibration. READY needs every check below; a measured negative is NOT_READY; anything that could not
be measured (missing config, reference, frame, calibration, fold, observation error, any exception) is UNKNOWN, which
Fleet never turns into bed_ready (a named operator's bed-confirm is the fallback).

C1 3 top frames, advancing, first to last >= 1.0 s, each <= 2 s old, read within 3 s
C2 calibration check: camera unmoved against its reference frame
C3 arm_s measured folded (fresh)
C4 the bed edge band of the registered docking reference (sites.pinky.bed_reference) found with normalized correlation
   >= min_score, offset <= 2 cm in pixels of the pinky map
C5 the bed holds still over the frames: best offsets within 2 px, normalized polygon difference <= still_mean_max
C6 an unload task (src pinky): >= 1 catalogue-matched object, every centre inside surface_px
The ROI is the config's sites.pinky auto_roi and surface_px only: the code default ROI of cell_task_exec is never used.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

SITE = "pinky"
CAMERA = "top"
FRAMES = 3
SPAN_S = 1.0  # Fleet's STILL_MIN_S
READ_S = 3.0
FRESH_S = 2.0  # cell_belt_occupancy.FRESH_S
BED_MOVE_M = 0.02  # Fleet's BED_MOVE_LIMIT_M
STILL_PX = 2.0
BAND_PX = 8


def _out(verdict: str, reason: str | None = None, **extra) -> dict:
    return {"verdict": verdict, "reasons": [reason] if reason else [], "site": SITE, **extra}


def read_frames(cell, now=time.time) -> list | None:
    """3 advancing top frames spread over >= SPAN_S, all read before one READ_S deadline; None when that fails."""
    from cell_zone_verification import _frame

    deadline = now() + READ_S
    first, _ = _frame(cell, CAMERA, deadline=deadline)
    if first is None:
        return None
    frames = [first]
    for i in range(1, FRAMES):
        got, _ = _frame(cell, CAMERA, previous=frames[-1], after=float(first["source_stamp"]) + SPAN_S * i / (FRAMES - 1),
                        deadline=deadline)
        if got is None:
            return None
        frames.append(got)
    return frames


def _gray(image) -> np.ndarray:
    import cv2

    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def band_mask(shape, polygon, band_px: int, ignore=()) -> np.ndarray:
    """The polygon's edge +-band_px, without the scene_ignore_px boxes."""
    import cv2

    mask = np.zeros(shape[:2], np.uint8)
    cv2.polylines(mask, [np.int32(polygon)], True, 1, thickness=2 * int(band_px) + 1)
    for x0, y0, x1, y1 in ignore:
        mask[int(y0):int(y1), int(x0):int(x1)] = 0
    return mask.astype(bool)


def match_band(ref: np.ndarray, gray: np.ndarray, mask: np.ndarray, search_px: int) -> tuple[float, tuple[int, int]]:
    """Best zero-mean normalized correlation of the reference band pixels against the frame, shifted within +-search_px.
    (Same measure as cv2.matchTemplate TM_CCOEFF_NORMED with a mask, written out so it does not depend on the OpenCV build.)"""
    ys, xs = np.nonzero(mask)
    a = ref[ys, xs].astype(np.float64)
    a -= a.mean()
    na = float(np.linalg.norm(a))
    h, w = gray.shape[:2]
    best = (-1.0, (0, 0))
    if na == 0 or not len(ys):
        return best
    for dy in range(-search_px, search_px + 1):
        for dx in range(-search_px, search_px + 1):
            yy, xx = ys + dy, xs + dx
            if yy.min() < 0 or xx.min() < 0 or yy.max() >= h or xx.max() >= w:
                continue
            b = gray[yy, xx].astype(np.float64)
            b -= b.mean()
            nb = float(np.linalg.norm(b))
            if nb and (score := float(a @ b) / (na * nb)) > best[0]:
                best = (score, (dx, dy))
    return best


def _px_per_m(record: dict, at) -> float:
    from cell_calibration import to_arm

    h = record["homography"]
    origin = to_arm(h, at)
    step = [math.dist(origin, to_arm(h, (at[0] + dx, at[1] + dy))) for dx, dy in ((1, 0), (0, 1))]
    return 2.0 / sum(step)


def _normalized(gray: np.ndarray, inside: np.ndarray) -> np.ndarray:
    v = gray[inside].astype(np.float64)
    return (v - v.mean()) / (v.std() or 1.0)  # global brightness and contrast removed


def judge(cell, config: dict, calibration: dict, catalog: list, task: dict, *, fold: dict, check=None, observe=None,
          config_sha256: str | None = None) -> dict:
    """One bed judgement. `check(frame) -> dict` is cell_calibrate.check, `observe` cell_auto_pick_plan.observe."""
    try:
        return _judge(cell, config, calibration, catalog, task, fold=fold, check=check, observe=observe,
                      config_sha256=config_sha256)
    except Exception as exc:  # a fault proves nothing: the operator fallback stays
        return _out("UNKNOWN", "OBSERVATION_FAILED", error=f"{type(exc).__name__}: {exc}"[:200])


def _judge(cell, config, calibration, catalog, task, *, fold, check, observe, config_sha256) -> dict:
    import cv2

    site = (config.get("sites") or {}).get(SITE) or {}
    roi, polygon, ref_cfg = site.get("auto_roi"), site.get("surface_px"), site.get("bed_reference")
    if not roi or not polygon:
        return _out("UNKNOWN", "NO_SITE_ROI")  # never the code default ROI (90,150,560,450): it misses the bed
    base = {"roi": [int(v) for v in roi], "config_sha256": config_sha256}
    if (not isinstance(ref_cfg, dict) or not ref_cfg.get("image") or not ref_cfg.get("sha256")
            or not isinstance(ref_cfg.get("min_score"), (int, float)) or not isinstance(ref_cfg.get("still_mean_max"), (int, float))):
        return _out("UNKNOWN", "NO_BED_REFERENCE", **base)
    if str(task.get("src_site") or "").rsplit("-l", 1)[0] != SITE:
        return _out("UNKNOWN", "LOAD_DIRECTION_UNSUPPORTED", **base)  # C6 is defined for unloading the Pinky only
    raw = Path(str(ref_cfg["image"])).expanduser().read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref_cfg["sha256"]:
        return _out("UNKNOWN", "BED_REFERENCE_MISMATCH", **base)
    ref = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    import cell_pivot

    record = cell_pivot.map_record(calibration, SITE)
    if ref is None or record is None:
        return _out("UNKNOWN", "NO_BED_REFERENCE", **base)
    if not fold.get("folded"):  # C3
        return _out("UNKNOWN", "ARM_NOT_FOLDED", **base)
    frames = read_frames(cell)  # C1
    now = time.time()
    if (frames is None or frames[-1]["source_stamp"] - frames[0]["source_stamp"] < SPAN_S
            or any(not -0.25 <= now - f["source_stamp"] <= FRESH_S for f in frames)):
        return _out("UNKNOWN", "NO_FRESH_FRAMES", **base)
    base["frames"] = [{k: f[k] for k in ("source_seq", "source_stamp", "jpeg_sha256")} for f in frames]
    if check is None:
        import cell_calibrate

        def check(frame):
            return cell_calibrate.check(config, calibration, [], frame, config.get("params"))
    cal = check(frames[-1]["image"]) or {}  # C2, the gate of cell_belt_occupancy
    if cal.get("camera_moved") is not False or not cal.get("camera_shift") or cal.get("no_reference"):
        return _out("UNKNOWN", "CALIBRATION_UNVERIFIED", **base)
    grays = [_gray(f["image"]) for f in frames]
    if any(g.shape != ref.shape for g in grays):
        return _out("UNKNOWN", "NO_BED_REFERENCE", **base)
    mask = band_mask(ref.shape, polygon, int(ref_cfg.get("band_px", BAND_PX)), config.get("scene_ignore_px") or ())
    centre = np.mean(np.asarray(polygon, float), axis=0)
    tol_px = BED_MOVE_M * _px_per_m(record, centre)
    matches = [match_band(ref, g, mask, int(math.ceil(tol_px)) + 2) for g in grays]  # C4 on each frame
    score, offset = min(m[0] for m in matches), matches[-1][1]
    base["bed"] = {"score": round(score, 4), "offset_px": list(offset), "tol_px": round(tol_px, 2)}
    if score < float(ref_cfg["min_score"]):
        return _out("NOT_READY", "BED_NOT_SEEN", **base)
    if any(math.hypot(*m[1]) > tol_px for m in matches):
        return _out("NOT_READY", "BED_OFF_POSE", **base)
    inside = np.zeros(ref.shape, np.uint8)
    cv2.fillPoly(inside, [np.int32(polygon)], 1)
    inside = inside.astype(bool)
    spread = max(math.dist(a[1], b[1]) for a in matches for b in matches)  # C5
    change = float(np.mean(np.abs(_normalized(grays[0], inside) - _normalized(grays[-1], inside))))
    base["bed"]["still_mean"] = round(change, 4)
    if spread > STILL_PX or change > float(ref_cfg["still_mean_max"]):
        return _out("NOT_READY", "BED_MOVING", **base)
    if observe is None:
        from cell_auto_pick_plan import observe
    _img, _mask, objects, error = observe(cell, config, calibration, SITE, roi, catalog, image=frames[-1]["image"])  # C6
    if error:
        return _out("UNKNOWN", "OBSERVATION_FAILED", error=str(error)[:200], **base)
    matched = [o for o in objects if o.get("matched")]
    base["objects"] = len(matched)
    if not matched:
        return _out("NOT_READY", "BED_EMPTY", **base)
    poly = np.asarray(polygon, np.float32)
    for o in matched:
        hull = np.asarray(o.get("hull_px") or [], float).reshape(-1, 2)
        if not len(hull) or cv2.pointPolygonTest(poly, tuple(float(v) for v in hull.mean(axis=0)), False) < 0:
            return _out("NOT_READY", "OBJECT_OFF_BED", **base)
    return _out("READY", None, **base)


def send_bed_observation(request_fn, observe_fn, task: dict) -> None:
    """The worker's step before a cell S claim: judge and POST .../bed-observation whatever the verdict (Fleet keeps NOT_READY
    and UNKNOWN too). Only Fleet turns a READY into bed_ready; a failure here leaves the operator fallback and never stops
    the poll. Cell A/B tasks are never observed."""
    if task.get("cell_id") != "cell_s" or observe_fn is None:
        return
    try:
        verdict = observe_fn(task)
    except Exception as exc:
        verdict = _out("UNKNOWN", "OBSERVATION_FAILED", error=f"{type(exc).__name__}: {exc}"[:200])
    if not isinstance(verdict, dict):
        verdict = _out("UNKNOWN", "OBSERVATION_FAILED")
    try:
        request_fn("POST", f"/api/fleet/pipeline/cell-tasks/{task['task_id']}/bed-observation",
                   {**verdict, "robot_id": task.get("robot_id")})
    except Exception:
        pass


def observe_bed(prep_dir: Path, task: dict) -> dict:
    """judge() with arm_s's live config, calibration, catalogue and measured fold; any failure is UNKNOWN."""
    try:
        import cell_pipeline as cp
        from cell_task_exec import _arm_run_spec, measured_fold

        _wrapper, cfg, cat, _default_roi, _src = _arm_run_spec("arm_s", Path(prep_dir))  # _default_roi is never used
        raw = cfg.read_bytes()
        config = json.loads(raw)
        calibration = json.loads(Path(config["calibration_path"]).expanduser().read_text(encoding="utf-8"))
        catalog = json.loads(cat.read_text(encoding="utf-8"))
        catalog = catalog.get("objects", catalog) if isinstance(catalog, dict) else catalog
        cell = cp.FifoCell(Path(config["io"]).expanduser(), config["cameras"])
        return judge(cell, config, calibration, catalog, task, fold=measured_fold("arm_s", Path(prep_dir)),
                     config_sha256=hashlib.sha256(raw).hexdigest())
    except Exception as exc:
        return _out("UNKNOWN", "OBSERVATION_FAILED", error=f"{type(exc).__name__}: {exc}"[:200])
