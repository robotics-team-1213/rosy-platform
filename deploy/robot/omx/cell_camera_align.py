"""Where the top camera stands against a reference image it was calibrated with, so a person can put it back by hand.

2026-11-27: the A/B top camera moved about 33 px (2.2 deg, scale 0.95) while a USB hub was replugged; the check only
said "camera_moved". This reads the live frame against the current map reference or an older one kept beside it
(backups, generations/, calibration-history/), and returns the displacement per grid point for an overlay.
"""
from __future__ import annotations

import math
import os
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()  # camera_shift_px keeps ORB state in module globals; the web server is threaded
_CACHE: dict = {}  # resolved reference -> (time, rows): the listing walks the folder once per CACHE_S, not per poll
CACHE_S = 10.0

PATTERNS = ("reference-top", )  # reference-top.jpg, reference-top-arms.jpg
SUFFIXES = (".jpg", ".jpeg", ".png")
MAX_DEPTH, MAX_REFS = 3, 12


def references(ref_path) -> list[dict]:
    """The current reference first, then older reference images under its folder (newest first, at most MAX_REFS)."""
    if not ref_path or not Path(ref_path).is_file():
        return []
    ref = Path(ref_path).resolve()
    hit = _CACHE.get(ref)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    root = ref.parent
    found = []
    for folder, dirs, files in os.walk(root):
        depth = len(Path(folder).relative_to(root).parts)
        if depth >= MAX_DEPTH:
            dirs[:] = []
        in_history = Path(folder).parent.name == "calibration-history"
        for name in files:
            if not name.lower().endswith(SUFFIXES) or not (name.startswith(PATTERNS) or in_history):
                continue
            p = Path(folder) / name
            if not p.is_symlink() and p.resolve() != ref:  # a linked file could point outside the folder
                found.append(p)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    rows = [_row("current", "현재 지도 기준", ref)]
    rows += [_row(p.relative_to(root).as_posix(), p.parent.relative_to(root).as_posix() or ".", p) for p in found[:MAX_REFS - 1]]
    _CACHE[ref] = (time.monotonic(), rows)
    return rows


def _row(ref_id: str, where: str, path: Path) -> dict:
    stamp = time.strftime("%m-%d %H:%M", time.localtime(path.stat().st_mtime))
    return {"id": ref_id, "label": f"{stamp} · {where}", "path": path}


def reference_path(ref_path, ref_id: str) -> Path | None:
    """The file for `ref_id` among references(), so a request can only name an image the listing offers."""
    return next((r["path"] for r in references(ref_path) if r["id"] == ref_id), None)


def align(reference_bytes: bytes, live_bytes: bytes, limit_px: float) -> dict:
    """Displacement of the live frame against the reference: per-grid arrows, mean shift, rotation and scale."""
    import cv2
    import numpy as np
    import cell_preflight

    ref = cv2.imdecode(np.frombuffer(reference_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    cur = cv2.imdecode(np.frombuffer(live_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if ref is None or cur is None:
        return {"ok": False, "why": "unreadable image"}
    if ref.shape != cur.shape:
        return {"ok": False, "why": f"size {ref.shape[1]}x{ref.shape[0]} vs {cur.shape[1]}x{cur.shape[0]}"}
    with _LOCK:
        shift = cell_preflight.camera_shift_px(ref, cur, include_transform=True)
    if not shift.get("ok"):
        return {"ok": False, "why": shift.get("why") or "no match"}
    H = np.array(shift["reference_to_current"], dtype=np.float64)
    h, w = ref.shape
    grid = np.float32([[[x, y]] for y in np.linspace(0.1 * h, 0.9 * h, 4) for x in np.linspace(0.1 * w, 0.9 * w, 5)])
    moved = cv2.perspectiveTransform(grid, H)
    d = (moved - grid).reshape(-1, 2)
    mags = np.linalg.norm(d, axis=1)
    return {
        "ok": True, "size": [int(w), int(h)], "inliers": shift.get("inliers"), "limit_px": float(limit_px),
        "max_px": round(float(mags.max()), 1), "median_px": round(float(np.median(mags)), 1),
        "shift_px": [round(float(v), 1) for v in d.mean(axis=0)],
        "rotation_deg": round(math.degrees(math.atan2(H[1, 0], H[0, 0])), 2),
        "scale": round(float(math.hypot(H[0, 0], H[1, 0])), 4),
        "aligned": bool(mags.max() <= limit_px),
        "arrows": [[round(float(a), 1), round(float(b), 1), round(float(c), 1), round(float(e), 1)]
                   for (a, b), (c, e) in zip(grid.reshape(-1, 2), moved.reshape(-1, 2))],
    }
