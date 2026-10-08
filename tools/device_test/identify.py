"""D-512 amendment 2: prove the robot pixel the tether check uses is the target robot.

On 2026-10-08 the agent took another (charging) robot in the overhead frame for 9dfk, and the
tether check and the position judgment were made against it. Here overhead frames are captured
for 2 s before and 6 s after CORE blinks the target's lamp (D-472 4, `POST /host/lamp/identify`);
the per-pixel change against the first frame must form a blob at the picked robot, nowhere else,
that did not already change before the request (steady LEDs, charge lights, a moving peer).
Anything unclear refuses: no identify, no blob, a blob elsewhere, a second strong blob, a blob
already changing, a saturated blob of the wrong colour, or a radius that is not a number.
"""
from __future__ import annotations

import hashlib
import math

from core_common.robot_body import PINKY_PRO

BASELINE_S = 2.0            # frames before the request: what changes without the blink
CAPTURE_S = 6.0             # D-472 4: the identify blink lasts at most 6 s
PERIOD_S = 0.2              # one overhead frame every 0.2 s (as the 2026-10-08 manual check)
COOLDOWN_S = 10.5           # CORE HW_TEST_COOLDOWN_S 10 s; one retry after it, with a fresh baseline
DIFF_LEVEL = 60             # max channel difference per pixel that counts as a lamp change (JPEG noise < 60)
JOIN_PX = 15                # changed pixels closer than this belong to one blob (lamp + its glow)
MIN_FRAMES = 3              # a blob must change in at least 3 frames (>= 0.6 s of blink), else weak
STRONG_SHARE = 0.5          # any blob changing in >= half the frames of the best one is a candidate
RADIUS_M = 1.5 * PINKY_PRO.rotation_radius_m   # body circle plus pick tolerance, at the calibration scale
# Colour (OpenCV hue 0-180). On 2026-10-08 the ceiling camera saw the lit lamp nearly white:
# saturation 8-44 of 255 (median ~18), hue 43-74 scattered, so the hue said nothing and a hue
# gate would have refused the true robot. The hue is judged only when the blob is clearly
# coloured (median saturation >= COLOUR_MIN_S); then it must lie within HUE_TOL of the colour
# CORE says it blinked. Below that the colour is recorded as not judged.
HUES = {"blue": 120, "amber": 15}
HUE_TOL = 20
COLOUR_MIN_S = 60


class Refused(ValueError):
    """Identity not shown; the message says why. `evidence` is what was seen up to then."""
    evidence: dict = {}


def _refuse(why):
    raise Refused(f"identity: {why}; confirm the robot another way (lamp by eye, hostname card, lift-and-see) "
                  "and pick again; the tether check is refused, no guess")


def radius_px(map_to_image, floor_xy, project):
    """RADIUS_M in pixels at floor_xy (the largest of four directions; NaN past the horizon)."""
    x, y = floor_xy
    u, v = project(map_to_image, x, y)
    return max(math.hypot(a - u, b - v) for a, b in (project(map_to_image, x + dx, y + dy) for dx, dy in (
        (RADIUS_M, 0), (-RADIUS_M, 0), (0, RADIUS_M), (0, -RADIUS_M))))


def blobs(ref, baseline, frames):
    """Blobs of change against ref in the blink frames, strongest first: center, bbox, pixels,
    frames (blink frames changed), before (baseline frames changed there), hue/sat medians."""
    import cv2
    import numpy as np

    def changed(f):
        return np.abs(f.astype(np.int16) - ref.astype(np.int16)).max(axis=2) > DIFF_LEVEL
    masks, before = [changed(f) for f in frames], [changed(f) for f in baseline]
    hsv = [cv2.cvtColor(f, cv2.COLOR_BGR2HSV) for f in frames]
    union = np.any(masks, axis=0) if masks else np.zeros(ref.shape[:2], bool)
    n, labels = cv2.connectedComponents(cv2.dilate(union.astype(np.uint8), np.ones((JOIN_PX, JOIN_PX), np.uint8)))
    out = []
    for k in range(1, n):
        comp = labels == k
        ys, xs = np.nonzero(comp & union)
        lit = np.concatenate([h[m & comp] for h, m in zip(hsv, masks)])
        out.append({"center": [round(float(xs.mean()), 1), round(float(ys.mean()), 1)],
                    "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], "pixels": int(len(xs)),
                    "frames": sum(bool((m & comp).any()) for m in masks),
                    "before": sum(bool((m & comp).any()) for m in before),
                    "hue": int(np.median(lit[:, 0])), "sat": int(np.median(lit[:, 1]))})
    return sorted(out, key=lambda b: (b["frames"], b["pixels"]), reverse=True)


def judge(found, pick, radius, n_frames, color):
    """The evidence when every strong blob sits at the pick, did not change before, and is not
    clearly the wrong colour. Refused otherwise."""
    if not (math.isfinite(radius) and radius > 0):
        _refuse(f"radius {radius} px is not a positive number (calibration past the horizon?)")
    if not found or found[0]["frames"] < MIN_FRAMES:
        _refuse(f"no lamp change seen ({found[0]['frames'] if found else 0} of {n_frames} frames changed, "
                f"need {MIN_FRAMES})")
    best = found[0]
    for b in [b for b in found if b["frames"] >= max(MIN_FRAMES, STRONG_SHARE * best["frames"])]:
        b["distance_px"] = round(math.hypot(b["center"][0] - pick[0], b["center"][1] - pick[1]), 1)
        x0, y0, x1, y1 = b["bbox"]
        what = f"{'the lamp blob' if b is best else 'another strong change'} at {b['center']} (bbox {b['bbox']}, " \
               f"{b['frames']} frames)"
        if not math.isfinite(b["distance_px"]) or b["distance_px"] > radius or math.hypot(x1 - x0, y1 - y0) > 2 * radius:
            _refuse(f"{what} is {b['distance_px']} px from the picked robot {[round(c, 1) for c in pick]}, "
                    f"over {radius:.0f} px or larger than the body")
        if b["before"]:
            _refuse(f"{what} already changed in {b['before']} frames before the identify request "
                    "(a steady LED, a charge light or something moving)")
    if color not in HUES:
        _refuse(f"CORE blinked colour {color!r}, not one of {sorted(HUES)}")
    off = abs((best["hue"] - HUES[color] + 90) % 180 - 90)
    if best["sat"] >= COLOUR_MIN_S and off > HUE_TOL:
        _refuse(f"the lamp blob has hue {best['hue']} (saturation {best['sat']}), {off} from {color} "
                f"{HUES[color]} (tolerance {HUE_TOL})")
    return {"blob_center": best["center"], "blob_bbox": best["bbox"], "pixel_count": best["pixels"],
            "blob_frames": best["frames"], "distance_px": best["distance_px"], "radius_px": round(radius, 1),
            "colour_check": f"hue {best['hue']} sat {best['sat']}: " + (
                f"within {HUE_TOL} of {color}" if best["sat"] >= COLOUR_MIN_S else "not judged (unsaturated)"),
            "others": [{k: b[k] for k in ("center", "frames", "before", "pixels")} for b in found[1:4]]}


def identify(robot, pick, radius, out_dir):
    """Baseline, blink, judge. Saves identify_NN.jpg; returns tether.identity. Refused carries the
    evidence so far (frames, phase and time of each, the refusal) for the verdict."""
    import cv2
    import numpy as np
    ev, t_start = {"pick_px": [round(c, 1) for c in pick], "radius_px": radius, "frames": []}, robot.now()

    def grab(phase):
        data = robot.overhead()
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
        if img is None:
            _refuse("no overhead frame")
        name = f"identify_{len(ev['frames']):02d}.jpg"
        (out_dir / name).write_bytes(data)
        ev["frames"].append({"name": name, "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                             "t": round(robot.now() - t_start, 2), "phase": phase})
        return img

    def window(phase, seconds):
        shots = [grab(phase)]
        for _ in range(round(seconds / PERIOD_S)):
            robot.sleep(PERIOD_S)
            shots.append(grab(phase))
        return shots

    try:
        if not (math.isfinite(radius) and radius > 0):
            judge([], pick, radius, 0, None)                 # refuses before anything is sent
        for attempt in (1, 2):
            baseline = window("baseline", BASELINE_S)        # fresh after a cooldown wait too
            s, body = robot.core.call("POST", "/host/lamp/identify", {})
            if s != 429 or attempt == 2:
                break
            robot.sleep(COOLDOWN_S)                          # HW_TEST_COOLDOWN: wait once, retry once
        code = ((body or {}).get("error") or {}).get("code") if isinstance(body, dict) else None
        if s != 200 or not isinstance(body, dict) or not body.get("accepted"):
            _refuse(f"lamp identify unavailable (HTTP {s}{', ' + code if code else ''})")
        ev.update(request_id=body.get("request_id"), color=body.get("color"))
        frames = window("blink", CAPTURE_S)
        if any(f.shape != baseline[0].shape for f in baseline + frames):
            _refuse("overhead frame size changed during the check")
        ev.update(judge(blobs(baseline[0], baseline[1:], frames), pick, radius, len(frames), body.get("color")))
        return ev
    except Refused as exc:
        exc.evidence = {**ev, "radius_px": str(radius) if not math.isfinite(radius) else radius, "refused": str(exc)}
        raise
