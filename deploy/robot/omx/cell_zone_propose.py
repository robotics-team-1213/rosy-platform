#!/usr/bin/env python3
"""Propose the zone table of one cell from its own frames (D-1057). Read-only: it never touches a cell config.

    python3 cell_zone_propose.py --top top.jpg --side side.jpg --out zone-proposal.json \
        --top-png zone-proposal-top.png --side-png zone-proposal-side.png

Top frame: the bright tray is found as the largest bright blob, and its dark grooves (thin lines darker than their
surroundings) split it into 3 columns x 2 rows. Side frame: the pallet ends and column dividers are found as strong vertical
edges, the tier bands as horizontal edges above the base. A slot whose boundary was not seen clearly is null with the reason.
`zone_rois` in the output is in the form the cell config's `zone_rois` takes, with only the confident slots; a person looks at
the pictures before anything is written to a config. The shared tables of `cell_area_zones` are drawn in red for comparison.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

# the adapter package that cell_area_zones imports lives in the repository next to deploy/
_ADAPTER = Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter"
if _ADAPTER.is_dir() and str(_ADAPTER) not in sys.path:
    sys.path.insert(0, str(_ADAPTER))

from cell_area_zones import SIDE_ROI_BY_COL_TIER, TOP_ROI_BY_COL_ROW

GROOVE_MIN = 8.0       # mean darkness (grey levels) along a top groove
SIDE_EDGE_RATIO = 0.2  # an interior side divider must be this fraction of the strongest vertical edge
MIN_GAP_PX = 15


def _peaks(profile: np.ndarray, offset: int, threshold: float, gap: int = MIN_GAP_PX) -> list[tuple[int, float]]:
    """Local maxima above `threshold`, strongest first, at least `gap` apart: [(position, strength)]."""
    found = []
    for i in range(2, len(profile) - 2):
        if profile[i] >= threshold and profile[i] == profile[max(0, i - gap):i + gap + 1].max():
            if not found or offset + i - found[-1][0] >= gap:  # a flat top is one peak
                found.append((offset + i, round(float(profile[i]), 1)))
    return sorted(found, key=lambda p: -p[1])


def tray_bbox(gray: np.ndarray) -> list[int] | None:
    """Bounding box [x0, y0, x1, y1] of the largest bright blob (the white tray), or None."""
    level = 0.8 * float(np.percentile(gray, 99))  # the white tray is the brightest large thing; dull surfaces stay below this
    count, labels, stats, _ = cv2.connectedComponentsWithStats((gray > level).astype(np.uint8), connectivity=8)
    if count < 2:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, _ = stats[best]
    blob = labels[:, x:x + w] == best
    # A thin bright bridge can stretch the blob: keep the longest run of rows that are mostly tray, then the columns in it.
    runs = _longest_run(blob.mean(axis=1) >= 0.6)
    if runs is None:
        return None
    y0, y1 = runs
    cols = _longest_run((labels[y0:y1, :] == best).mean(axis=0) >= 0.6)
    return None if cols is None else [int(cols[0]), int(y0), int(cols[1]), int(y1)]


def _longest_run(flags: np.ndarray) -> tuple[int, int] | None:
    best, start = None, None
    for i, on in enumerate(list(flags) + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            best = (start, i) if best is None or i - start > best[1] - best[0] else best
            start = None
    return best


def propose_top(image: np.ndarray) -> dict:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    box = tray_bbox(gray)
    out: dict = {"tray_bbox": box, "rois": {f"c{c}r{r}": None for c in (1, 2, 3) for r in (1, 2)}, "reasons": {}, "evidence": {}}
    if box is None:
        out["reasons"] = {k: "no bright tray found" for k in out["rois"]}
        return out
    x0, y0, x1, y1 = box
    inner = gray[y0 + 4:y1 - 4, x0 + 4:x1 - 4].astype(float)
    darkness = cv2.GaussianBlur(inner, (0, 0), 9) - inner  # thin dark lines stand out from their surroundings
    cols = _peaks(darkness.mean(axis=0), x0 + 4, GROOVE_MIN)
    rows = _peaks(darkness.mean(axis=1), y0 + 4, GROOVE_MIN)
    out["evidence"] = {"vertical_grooves": cols[:6], "horizontal_grooves": rows[:6]}
    if len(cols) < 2:
        out["reasons"].update({k: "fewer than 2 vertical grooves seen" for k in out["rois"]})
        return out
    xs = [x0] + sorted(p for p, _ in cols[:2]) + [x1]
    if len(rows) < 1:
        out["reasons"].update({k: "no horizontal groove seen" for k in out["rois"]})
        return out
    ys = [y0, rows[0][0], y1]
    for c in (1, 2, 3):
        for r in (1, 2):
            out["rois"][f"c{c}r{r}"] = [xs[c - 1], ys[r - 1], xs[c], ys[r]]
    heights = [ys[1] - ys[0], ys[2] - ys[1]]
    if max(heights) > 1.4 * min(heights):
        out["notes"] = [f"the two rows are unequal ({heights[0]} and {heights[1]} px): the one horizontal groove is trusted, "
                        "but a second groove may be hidden"]
    return out


def propose_side(image: np.ndarray) -> dict:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(float)
    signed = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gx, gy = np.abs(signed), np.abs(cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3))
    band = gx[100:330, :].mean(axis=0)
    direction = np.convolve(signed[100:330, :].mean(axis=0), np.ones(3) / 3, "same")  # > 0 dark to light going right
    smooth = np.convolve(band, np.ones(3) / 3, "same")
    out: dict = {"rois": {f"c{c}t{t}": None for c in (1, 2, 3) for t in (1, 2, 3)}, "reasons": {}, "evidence": {}}
    # The pallet is a light block on a darker background: a rising edge (left end) and a falling edge (right end) 170-320 px
    # apart (about 250 px in this view). Take the pair with the largest combined strength.
    rising = _peaks(np.clip(direction, 0, None), 0, 5.0, gap=20)
    falling = _peaks(np.clip(-direction, 0, None), 0, 5.0, gap=20)
    pairs = sorted(((min(sl, sr), l, r) for l, sl in rising for r, sr in falling if 170 <= r - l <= 320), reverse=True)
    out["evidence"] = {"end_candidates": [{"left": l, "right": r, "score": round(float(s), 1)} for s, l, r in pairs[:4]]}
    if len(pairs) > 1 and pairs[1][0] >= 0.8 * pairs[0][0]:
        out["reasons"] = {k: f"pallet ends ambiguous: {pairs[0][1:]} and {pairs[1][1:]} score alike" for k in out["rois"]}
        return out
    if not pairs:
        out["reasons"] = {k: "pallet ends (a rising and a falling vertical edge 170-320 px apart) not found" for k in out["rois"]}
        return out
    _, left, right = pairs[0]
    strongest = max(s for p, s in _peaks(smooth, 0, 1.0, gap=20) if p in (left, right) or abs(p - right) < 4 or abs(p - left) < 4)
    inner = [(p, s) for p, s in _peaks(np.convolve(band, np.ones(3) / 3, "same"), 0, strongest * SIDE_EDGE_RATIO, gap=20)
             if left + 25 < p < right - 25]
    horizontal = gy[:, left:right].mean(axis=1)
    horizontal = np.convolve(horizontal, np.ones(3) / 3, "same")
    base_edges = _peaks(horizontal, 0, float(horizontal.mean()) * 1.5, gap=10)
    out["evidence"].update(pallet_ends_x=[left, right], interior_vertical_edges=inner[:6], horizontal_edges=base_edges[:8])
    thirds = [left + (right - left) * k / 3 for k in (1, 2)]
    dividers = [next((p for p, _ in inner if abs(p - t) <= 14), None) for t in thirds]
    base = base_edges[0][0] if base_edges else None
    above = sorted(p for p, s in base_edges if base is not None and p < base - 20 and s >= base_edges[0][1] * 0.4)
    why = []
    if None in dividers:
        why.append("column dividers not seen at the third points of the pallet: " + str([d for d in dividers]))
    if len(above) < 3:  # a boundary that was not observed is not guessed
        why.append(f"tier boundaries not seen: base edge y={base}, edges above it {above} (need three observed)")
    out["reasons"] = {k: "; ".join(why) or "not implemented for this layout" for k in out["rois"]}
    if not why:  # both kinds of boundary found: cut the pallet into the three columns and the tier bands above the base
        xs = [left] + [int(d) for d in dividers] + [right]
        tops = above[-3:]
        ys = [int(v) for v in sorted(tops + [base])]
        for c in (1, 2, 3):
            for t in (1, 2, 3):
                out["rois"][f"c{c}t{t}"] = [xs[c - 1], ys[3 - t], xs[c], ys[4 - t]]
                out["reasons"].pop(f"c{c}t{t}", None)
    return out


def _draw(image: np.ndarray, constants: dict, proposed: dict, label) -> np.ndarray:
    out = image.copy()
    for key, roi in constants.items():
        cv2.rectangle(out, tuple(roi[:2]), tuple(roi[2:]), (0, 0, 255), 1)
        cv2.putText(out, label(key), (roi[0] + 2, roi[1] + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)
    for key, roi in proposed.items():
        if roi is not None:
            cv2.rectangle(out, tuple(roi[:2]), tuple(roi[2:]), (0, 220, 0), 2)
            cv2.putText(out, key, (roi[0] + 3, roi[3] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 0), 1)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", required=True, type=Path)
    ap.add_argument("--side", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--top-png", required=True, type=Path)
    ap.add_argument("--side-png", required=True, type=Path)
    args = ap.parse_args(argv)
    top, side = cv2.imread(str(args.top)), cv2.imread(str(args.side))
    if top is None or side is None:
        print("refused: cannot read a frame", file=sys.stderr)
        return 2
    t, s = propose_top(top), propose_side(side)
    doc = {"schema": "rosy.zone-proposal.v1", "frames": {"top": str(args.top.name), "side": str(args.side.name),
                                                         "size": [top.shape[1], top.shape[0]]},
           "top": t, "side": s,
           "zone_rois": {"top": {k: v for k, v in t["rois"].items() if v}, "side": {k: v for k, v in s["rois"].items() if v}},
           "not_applied": "nothing is written to any cell config; review the pictures first"}
    for path in (args.out, args.top_png, args.side_png):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    cv2.imwrite(str(args.top_png), _draw(top, {f"c{c}r{r}": list(v) for (c, r), v in TOP_ROI_BY_COL_ROW.items()}, t["rois"], str))
    cv2.imwrite(str(args.side_png), _draw(side, {f"c{c}t{k}": list(v) for (c, k), v in SIDE_ROI_BY_COL_TIER.items()}, s["rois"], str))
    print(json.dumps({"out": str(args.out), "top_confident": len(doc["zone_rois"]["top"]), "side_confident": len(doc["zone_rois"]["side"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
