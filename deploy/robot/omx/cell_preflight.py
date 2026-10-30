#!/usr/bin/env python3
"""Checks before an autonomous run on a cell someone else may have used (2026-10-28: after another session the top
camera had been re-mounted ~7 deg / 20-45 px, the gripper camera was on another USB port and channel, and the
follower caps were left raised). Read only: no arm motion, no register writes.

  cell_preflight.py --config cell-auto.json [--viewer http://127.0.0.1:8767] [--max-shift-px 6]
Exit 0 only when every check passes; each failure says what to do.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import cell_params as prm


def lights(frames: dict, params=None) -> list:
    """(name, ok, why) per camera frame. A frame this dark means the room lights are off or the lens is covered, and
    no detection, look or place check works (2026-10-30 00:40: top mean 1.4, wrist 0.1, still 1.4 at 200 ms exposure
    and gain 7 - not the camera)."""
    floor, out = prm.get(params, "preflight.min_mean"), []
    for name, img in frames.items():
        mean = None if img is None else float(img.mean())
        ok = mean is not None and mean >= floor
        why = "no frame" if mean is None else f"mean {mean:.1f}" + ("" if ok else f" < {floor}: the room lights are off or the lens is covered - a person turns them on")
        out.append((f"light {name}", ok, why))
    return out


def camera_shift_px(reference, current) -> dict:
    """Largest displacement of the image grid between the map's reference frame and now (ORB + RANSAC homography)."""
    import cv2
    import numpy as np

    orb = cv2.ORB_create(3000)
    k1, d1 = orb.detectAndCompute(reference, None)
    k2, d2 = orb.detectAndCompute(current, None)
    if d1 is None or d2 is None:
        return {"ok": False, "why": "no features"}
    matches = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda m: m.distance)[:600]
    if len(matches) < 30:
        return {"ok": False, "why": f"{len(matches)} matches"}
    H, inliers = cv2.findHomography(np.float32([k1[m.queryIdx].pt for m in matches]),
                                    np.float32([k2[m.trainIdx].pt for m in matches]), cv2.RANSAC, 3.0)
    h, w = reference.shape[:2]
    grid = np.float32([[[x, y]] for x in (0.1 * w, 0.5 * w, 0.9 * w) for y in (0.1 * h, 0.5 * h, 0.9 * h)])
    moved = np.linalg.norm(cv2.perspectiveTransform(grid, H) - grid, axis=2)
    return {"ok": True, "max_px": round(float(moved.max()), 1), "inliers": int(inliers.sum())}


def checks(config: dict, viewer: str, max_shift_px: float, fetch=None, run=subprocess.run) -> list:
    import cv2
    import numpy as np

    fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=5).read())
    out = []
    try:
        state = json.loads(fetch(f"{viewer}/state.json"))
    except OSError as exc:
        state = {}
        out.append(("viewer", False, f"no viewer state ({exc}); start rosy-omx-camera-view"))
    for label in config.get("episodes", {}).get("cameras", {"top": None, "front": None}):
        fresh = bool(state.get(label, {}).get("fresh"))
        out.append((f"camera {label}", fresh, "fresh" if fresh else
                    "not fresh: check the camera's USB device (by-path ports change) and which channel the viewer reads"))
    try:
        cur = cv2.imdecode(np.frombuffer(fetch(f"{viewer}/frame/top.jpg"), np.uint8), cv2.IMREAD_GRAYSCALE)
    except OSError:
        cur = None
    out += lights({"top": cur}, config.get("params"))
    ref_path = (config.get("preflight") or {}).get("reference_top")
    if cur is not None and ref_path and Path(ref_path).expanduser().exists():
        ref = cv2.imread(str(Path(ref_path).expanduser()), cv2.IMREAD_GRAYSCALE)
        shift = camera_shift_px(ref, cur)
        ok = shift["ok"] and shift["max_px"] <= max_shift_px
        out.append(("top camera pose", ok, f"{shift}" + ("" if ok else ": the map is stale - remap (layout_map) and re-pivot before any motion")))
    else:
        out.append(("top camera pose", False, "no reference frame for this map (preflight.reference_top): save one right after mapping"))
    busy = run(["bash", "-c", "ps -eo cmd | grep '[r]ecord_session.py' | grep -vc -- '--io chunk-io'"], capture_output=True, text=True).stdout.strip()
    out.append(("other arm session", busy in ("", "0"), "none" if busy in ("", "0") else f"{busy} running: wait"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--viewer", default="http://127.0.0.1:8767")
    ap.add_argument("--max-shift-px", type=float, default=6.0)
    args = ap.parse_args(argv)
    rows = checks(json.loads(args.config.read_text(encoding="utf-8")), args.viewer, args.max_shift_px)
    for name, ok, why in rows:
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {why}")
    print("follower caps: record_session refuses raised caps; restore with commissioning_limits.py --baseline (torque OFF)")
    return 0 if all(ok for _, ok, _ in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
