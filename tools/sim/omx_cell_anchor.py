"""Has the top camera moved since a snapshot? Measuring through a moved camera gives believable wrong numbers.

2026-11-10 the D435 was re-plugged for USB3 and its frame shifted -56 / -17 px, turned 2.8 deg and grew 1.6 %; the
ship and belt then "moved" 48 and 60 mm the same way and every plate fit fell apart. The pad-size check missed it: the
plates had moved too, so no clean pad was left in view. Here the frame is matched to the snapshot's own top frame on
the far band (table edge, belt, floor), where nothing of the cell's layout moves, and a similarity transform says
whether the camera did.

Real-cell photos stay out of Git, so the reference frames live in a local store keyed by their sha256 (the snapshot
records that digest): ROSY_REAL2SIM_FRAMES, default ~/.local/state/rosy/real2sim-frames.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import shutil

import numpy as np

BAND = (0., .31)              # rows of the frame, as a share of its height: the far table, the belt and the floor
LIMITS = dict(shift_px=3., rotation_deg=.3, scale=.005)  # D-947's 3 px; a 0.3 deg turn moves the far corners 2-3 px


def store() -> Path:
    return Path(os.environ.get("ROSY_REAL2SIM_FRAMES", Path.home() / ".local/state/rosy/real2sim-frames"))


def digest(path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def remember(path, root: Path | None = None) -> str:
    """Keep a top frame by its digest (the name the snapshot records) and return that digest."""
    root = root or store()
    root.mkdir(parents=True, exist_ok=True)
    name = digest(path)
    target = root / (name.split(":", 1)[1] + Path(path).suffix)
    if not target.exists():
        shutil.copyfile(path, target)
    return name


def reference(name: str, root: Path | None = None) -> Path | None:
    hits = sorted((root or store()).glob(name.split(":", 1)[-1] + ".*"))
    return hits[0] if hits else None


def motion(old, new) -> dict | None:
    """Similarity transform taking the old frame's far band onto the new one, or None when too little matches."""
    import cv2

    def gray(img):
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

    a, b = gray(old), gray(new)
    mask = np.zeros_like(a)
    mask[int(BAND[0] * a.shape[0]):int(BAND[1] * a.shape[0]), :] = 255
    orb = cv2.ORB_create(3000)
    ka, da = orb.detectAndCompute(a, mask)
    kb, db = orb.detectAndCompute(b, mask)
    if da is None or db is None:
        return None
    pairs = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db), key=lambda m: m.distance)[:300]
    if len(pairs) < 12:
        return None
    pa = np.float32([ka[m.queryIdx].pt for m in pairs])
    pb = np.float32([kb[m.trainIdx].pt for m in pairs])
    M, inliers = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None or int(inliers.sum()) < 10:
        return None
    return dict(dx_px=round(float(M[0, 2]), 1), dy_px=round(float(M[1, 2]), 1),
                rotation_deg=round(math.degrees(math.atan2(M[1, 0], M[0, 0])), 2),
                scale=round(float(math.hypot(M[0, 0], M[1, 0])), 4), inliers=int(inliers.sum()))


def moved(m: dict) -> bool:
    return (math.hypot(m["dx_px"], m["dy_px"]) > LIMITS["shift_px"] or abs(m["rotation_deg"]) > LIMITS["rotation_deg"]
            or abs(m["scale"] - 1) > LIMITS["scale"])
