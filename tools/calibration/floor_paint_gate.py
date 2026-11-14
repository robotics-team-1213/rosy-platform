"""One robot's pink bay-tape gate from its own front-camera frames, as a floor_paint calibration record.

    floor_paint_gate.py measure FRAME.jpg [...]                     the gate and the tape's HSV percentiles
    floor_paint_gate.py add ROBOT FRAME.jpg [...] [--root R]          the same, added as a candidate record

The tape's colour depends on the camera (2026-11-14: rosy_42 read it H 172-175, S 49-78; the ceiling phone
H 167-172, S 40-74). The gate covers the tape's 1st-99th percentile with a margin, and down to half its
darkest brightness so a shadowed line stays in (the D-1013 reason for a colour source). Accept the record with
store_cli.py accept ROBOT floor_paint RECORD --actor NAME and sync it to the robot; lane_keep_lines.pink_gate
reads it at the next start. Frames: a robot looking at a bay line (/<ns>/camera/preview/raw/compressed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "contracts" / "foundation"))
from core_common.calibration_store import FLOOR_PINK_H_MIN, CalibrationStore, check_values  # noqa: E402

MIN_TAPE_PX = 300  # about a tape-width line over 0.3 m in a 320x240 frame; fewer is not a measurement
MIN_PART_PX = 60   # specks and the odd pink pixel on a robot are not tape


def tape_pixels(bgr: np.ndarray) -> np.ndarray:
    """HSV rows of the pink tape: hue past H 140 (wrapping at 180 kept above 179), coloured, lit, line-sized parts."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, sat, val = (hsv[..., i].astype(int) for i in range(3))
    seed = ((hue >= 140) | (hue <= 5)) & (sat >= 25) & (val >= 100)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(seed.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= MIN_PART_PX
    mask = keep[labels]
    return np.column_stack([np.where(hue[mask] <= 5, hue[mask] + 180, hue[mask]), sat[mask], val[mask]])


def gate(frames) -> dict:
    rows = np.vstack([tape_pixels(f) for f in frames])
    if len(rows) < MIN_TAPE_PX:
        raise ValueError(f"only {len(rows)} tape pixels (need {MIN_TAPE_PX}): point the camera at a bay line")
    h1, h99 = np.percentile(rows[:, 0], [1, 99])
    s2, v2 = np.percentile(rows[:, 1], 2), np.percentile(rows[:, 2], 2)
    values = {"pink_h_low": int(max(FLOOR_PINK_H_MIN, h1 - 5)), "pink_h_high": int(min(179, h99 + 3)),
              "pink_min_saturation": int(max(25, s2 - 10)), "pink_min_value": int(max(30, v2 / 2))}
    why = check_values("floor_paint", values)
    if why:
        raise ValueError(why)
    stats = {f"{k}_p": [round(float(x), 1) for x in np.percentile(rows[:, i], [1, 10, 50, 90, 99])]
             for i, k in enumerate(("h", "s", "v"))}
    return {"values": values, "pixels": int(len(rows)), "percentiles_1_10_50_90_99": stats,
            "wrapped_past_179": float(np.mean(rows[:, 0] > 179))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    me = sub.add_parser("measure")
    me.add_argument("frames", nargs="+", type=Path)
    ad = sub.add_parser("add")
    ad.add_argument("robot")
    ad.add_argument("frames", nargs="+", type=Path)
    ad.add_argument("--root", type=Path, help="store root (default: the PC mirror data/calibration/)")
    args = ap.parse_args(argv)
    frames = [cv2.imread(str(p)) for p in args.frames]
    if any(f is None for f in frames):
        ap.error("a frame could not be read")
    try:
        result = gate(frames)
    except ValueError as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    if args.verb == "add":
        if args.root is None:
            from data_paths import data_root
            args.root = data_root() / "calibration"
        result["record"] = CalibrationStore(args.root).add(
            args.robot, "floor_paint", result["values"], sessions=[p.name for p in args.frames],
            method="floor_paint_gate/1 (tape p1-p99 hue +-, S p2-10, V p2/2)",
            intervals={k: v for k, v in result.items() if k != "values"})
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
