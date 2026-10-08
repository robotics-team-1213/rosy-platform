"""D-512 amendment 2: prove the robot pixel the tether check uses is the target robot.

On 2026-10-08 the agent took another (charging) robot in the overhead frame for 9dfk, and the
tether check and the position judgment were made against it. Here CORE blinks the target's lamp
(D-472 4, `POST /host/lamp/identify`, <= 6 s) while overhead frames are captured; the per-pixel
change against the pre-blink frame must form a blob at the picked robot, and nowhere else.
Anything unclear refuses: no identify, no blob, a blob elsewhere or a second strong blob.
"""
from __future__ import annotations

import hashlib
import math

from core_common.robot_body import PINKY_PRO

CAPTURE_S = 6.0             # D-472 4: the identify blink lasts at most 6 s
PERIOD_S = 0.2              # one overhead frame every 0.2 s (as the 2026-10-08 manual check)
COOLDOWN_S = 10.5           # CORE HW_TEST_COOLDOWN_S 10 s; one retry after it
DIFF_LEVEL = 60             # max channel difference per pixel that counts as a lamp change (JPEG noise < 60)
JOIN_PX = 15                # changed pixels closer than this belong to one blob (lamp + its glow)
MIN_FRAMES = 3              # a blob must change in at least 3 frames (>= 0.6 s of blink), else weak
STRONG_SHARE = 0.5          # any blob changing in >= half the frames of the best one is a candidate
RADIUS_M = 1.5 * PINKY_PRO.rotation_radius_m   # body circle plus pick tolerance, at the calibration scale


class Refused(ValueError):
    """Identity not shown; the message says why and to confirm identity another way."""


def _refuse(why):
    raise Refused(f"identity: {why}; confirm the robot another way (lamp by eye, hostname card, lift-and-see) "
                  "and pick again; the tether check is refused, no guess")


def radius_px(map_to_image, floor_xy, project):
    """RADIUS_M in pixels at floor_xy (the largest of four directions through the calibration)."""
    x, y = floor_xy
    u, v = project(map_to_image, x, y)
    return max(math.hypot(a - u, b - v) for a, b in (project(map_to_image, x + dx, y + dy) for dx, dy in (
        (RADIUS_M, 0), (-RADIUS_M, 0), (0, RADIUS_M), (0, -RADIUS_M))))


def blobs(pre, frames):
    """Blobs of change against pre: [{center, bbox, pixels, frames}] strongest first."""
    import cv2
    import numpy as np
    masks = [np.abs(f.astype(np.int16) - pre.astype(np.int16)).max(axis=2) > DIFF_LEVEL for f in frames]
    union = np.any(masks, axis=0).astype(np.uint8) if masks else np.zeros(pre.shape[:2], np.uint8)
    n, labels = cv2.connectedComponents(cv2.dilate(union, np.ones((JOIN_PX, JOIN_PX), np.uint8)))
    out = []
    for k in range(1, n):
        comp = labels == k
        ys, xs = np.nonzero(comp & union.astype(bool))
        out.append({"center": [round(float(xs.mean()), 1), round(float(ys.mean()), 1)],
                    "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], "pixels": int(len(xs)),
                    "frames": sum(bool((m & comp).any()) for m in masks)})
    return sorted(out, key=lambda b: (b["frames"], b["pixels"]), reverse=True)


def judge(found, pick, radius, n_frames):
    """The evidence dict when one strong blob (or several, all at the pick) sits within radius."""
    if not found or found[0]["frames"] < MIN_FRAMES:
        _refuse(f"no lamp change seen ({found[0]['frames'] if found else 0} of {n_frames} frames changed, "
                f"need {MIN_FRAMES})")
    best = found[0]
    strong = [b for b in found if b["frames"] >= max(MIN_FRAMES, STRONG_SHARE * best["frames"])]
    for b in strong:
        b["distance_px"] = round(math.hypot(b["center"][0] - pick[0], b["center"][1] - pick[1]), 1)
        x0, y0, x1, y1 = b["bbox"]
        if b["distance_px"] > radius or math.hypot(x1 - x0, y1 - y0) > 2 * radius:
            _refuse(f"{'the lamp blob' if b is best else 'another strong change'} at {b['center']} "
                    f"(bbox {b['bbox']}, {b['frames']} frames) is {b['distance_px']} px from the picked robot "
                    f"{[round(c, 1) for c in pick]}, over {radius:.0f} px or larger than the body")
    return {"blob_center": best["center"], "blob_bbox": best["bbox"], "pixel_count": best["pixels"],
            "blob_frames": best["frames"], "distance_px": best["distance_px"], "radius_px": round(radius, 1),
            "others": [{k: b[k] for k in ("center", "frames", "pixels")} for b in found[1:4]]}


def identify(robot, pick, radius, out_dir):
    """Blink the target's lamp, capture, judge. Saves identify_NN.jpg; returns tether.identity."""
    import cv2
    import numpy as np

    def grab():
        data = robot.overhead()
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
        if img is None:
            _refuse("no overhead frame")
        name = f"identify_{len(saved):02d}.jpg"
        (out_dir / name).write_bytes(data)
        saved[name] = "sha256:" + hashlib.sha256(data).hexdigest()
        return img

    saved = {}
    pre = grab()
    for attempt in (1, 2):
        s, body = robot.core.call("POST", "/host/lamp/identify", {})
        if s != 429 or attempt == 2:
            break
        robot.sleep(COOLDOWN_S)                              # HW_TEST_COOLDOWN: wait once, retry once
        pre = grab()
    code = ((body or {}).get("error") or {}).get("code") if isinstance(body, dict) else None
    if s != 200 or not isinstance(body, dict) or not body.get("accepted"):
        _refuse(f"lamp identify unavailable (HTTP {s}{', ' + code if code else ''})")
    frames, t0 = [], robot.now()
    while robot.now() - t0 < CAPTURE_S:
        robot.sleep(PERIOD_S)
        frames.append(grab())
    if any(f.shape != pre.shape for f in frames):
        _refuse("overhead frame size changed during the blink")
    evidence = judge(blobs(pre, frames), pick, radius, len(frames))
    return {"request_id": body.get("request_id"), "color": body.get("color"), "pick_px": [round(c, 1) for c in pick],
            **evidence, "frames": saved}
