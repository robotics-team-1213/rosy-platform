"""Drivable branch replay (D-597): run a learned drivable model and the keep-mode way finder
(learned/drivable_paint.drivable_target, through LaneSegModel.infer_drivable's logits) on recorded
robot frames, and write per-frame branch counts, the way's steering target, overlays and contact
sheets. Recordings and results stay outside the public repository (D-226): --out inside it is refused.

  python tools/drivable_branch_replay.py --model X:/.../lane-seg-20261010-71edcb6d \
      --frames X:/DevTemp/v13-drive/frames --video teleop_x.mp4 --every-s 1 --out X:/DevTemp/dbr/run1

Per frame (frames.csv): reason/branches/near_fraction from drivable_target; target_x is the way's
centre column at its middle row (the steering target), error = (target_x - centre) / half width,
positive right; far_x is the way's centre over its top 5 rows (where the chosen branch goes).
split_row is the lowest row where the way split (>= 2 wide runs). Overlay: left the camera frame,
right the model's drivable (+ignore) floor dim cyan, lane marking blue/red, the chosen way green,
the rest of the filled region (the branches not taken) magenta, split rows yellow ticks at the
left edge, target white dot. Sheets: sheet-multi-*.jpg (branches >= 2) and
sheet-all-*.jpg, 48 tiles each, captioned with the frame's row number in frames.csv.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "middleware" / "perception"))
sys.path.insert(0, str(REPO / "contracts" / "foundation"))

from control.sensing.perception.learned.drivable_paint import (  # noqa: E402
    MIN_BRANCH_WIDTH_FRACTION, _runs, drivable_target, fill_holes)
from control.sensing.perception.learned.lane_mask import _row_runs, lane_bounded_drivable  # noqa: E402
from control.sensing.perception.learned.runner import LaneSegModel  # noqa: E402

FRAME_W, FRAME_H = 320, 240
TILES = 48


def frames(args):
    """(source name, frame id, bgr) at FRAME_W x FRAME_H."""
    for folder in args.frames:
        for path in sorted(Path(folder).glob("*.jpg")):
            yield Path(folder).name, path.stem, cv2.imread(str(path))
    for video in args.video:
        cap = cv2.VideoCapture(str(video))
        step = max(1, round((cap.get(cv2.CAP_PROP_FPS) or 10.0) * args.every_s))
        index = 0
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            if index % step == 0:
                yield Path(video).stem, str(index), bgr
            index += 1


def region_and_splits(labels, classes, way, ignore_top):
    """The filled region drivable_target chose the way from (its steps repeated here, since it
    returns only the way) and the rows where the way split: >= 2 wide runs touching the way below."""
    roles = {}
    for c in classes:
        roles.setdefault(c.role, []).append(c.index)
    names = {c.name: c.index for c in classes}
    labels = np.where(np.isin(labels, roles.get("ignore", [])), roles["drivable"][0], labels)
    region = fill_holes(lane_bounded_drivable(
        labels, roles["drivable"][0], roles.get("lane_marking", ()), ignore_top=ignore_top,
        max_row_growth=float("inf"),
        boundary=(names["lane_left"], names["lane_right"]) if {"lane_left", "lane_right"} <= set(names) else None))
    splits = []
    for row in range(way.shape[0] - 1):
        below = way[row + 1]
        if not below.any() or not way[row].any():
            continue
        cols = np.flatnonzero(below)
        runs = _runs(_row_runs(region[row], below))
        if sum(r[1] - r[0] + 1 >= MIN_BRANCH_WIDTH_FRACTION * (cols[-1] - cols[0] + 1) for r in runs) >= 2:
            splits.append(row)
    return region, splits


def overlay(bgr, labels, classes, way, target, region=None, splits=()):
    view = bgr.copy()
    roles = {c.index: c.role for c in classes}
    names = {c.index: c.name for c in classes}
    colours = []
    for idx, role in roles.items():
        if role in ("drivable", "ignore"):
            colours.append((labels == idx, (160, 120, 0)))
        elif role == "lane_marking":
            colours.append((labels == idx, (255, 0, 0) if names[idx] == "lane_left" else (0, 0, 255)))
    if way is not None:
        colours.append((way, (0, 220, 0)))
        colours.append((region & ~way, (220, 0, 220)))  # region left out of the way: other branches
    for mask, colour in colours:
        view[mask] = (bgr[mask] * 0.4 + np.asarray(colour) * 0.6).astype(np.uint8)
    if target is not None:
        cv2.circle(view, target, 4, (255, 255, 255), -1)
    for row in splits:
        view[row, :12] = (0, 255, 255)
    return np.hstack([bgr, view])


def sheet(tiles, path):
    width = tiles[0][1].shape[1]
    tiles = [cv2.putText(t.copy(), cap, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
             for cap, t in tiles]
    tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 3)
    rows = [np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)]
    image = np.vstack(rows)
    cv2.imwrite(str(path), cv2.resize(image, (width * 3 // 2, image.shape[0] // 2)), [cv2.IMWRITE_JPEG_QUALITY, 85])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, type=Path, help="model folder with model_manifest.json")
    ap.add_argument("--frames", action="append", default=[], help="folder of .jpg frames (all used)")
    ap.add_argument("--video", action="append", default=[], help="camera mp4 (320x240 raw recording)")
    ap.add_argument("--every-s", type=float, default=1.0, help="video sampling interval")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args(argv)
    if args.out.resolve().is_relative_to(REPO):
        ap.error("--out must be outside the repository (D-226)")
    (args.out / "overlay").mkdir(parents=True, exist_ok=True)
    model = LaneSegModel.open(args.model, threads=args.threads)
    classes = model.manifest.classes
    crop = model.manifest.input.crop
    rows, multi, every = [], [], []
    for source, frame_id, bgr in frames(args):
        bgr = cv2.resize(bgr, (FRAME_W, FRAME_H))
        logits = model._logits(bgr)  # the same logits infer_drivable uses
        way, info = drivable_target(logits, classes, ignore_top=crop[2] if crop is not None else 0)
        labels = logits[0].argmax(axis=0)
        row = dict(n=len(rows), source=source, frame=frame_id, reason=info["reason"],
                   branches=info["branches"], near_fraction=info["near_fraction"],
                   target_x="", error="", far_x="", split_row="")
        target, region, splits = None, None, []
        if way is not None:
            region, splits = region_and_splits(labels, classes, way, crop[2] if crop is not None else 0)
            ys = np.flatnonzero(way.any(axis=1))
            mid = int(ys[len(ys) // 2])
            tx = float(np.flatnonzero(way[mid]).mean())
            far = way[ys[0]:ys[0] + 5]
            row.update(target_x=round(tx, 1), error=round((tx - (FRAME_W - 1) / 2) / (FRAME_W / 2), 3),
                       far_x=round(float(np.nonzero(far)[1].mean()), 1), split_row=splits[-1] if splits else "")
            target = (int(round(tx)), mid)
        name = f"{row['n']:05d}_{source}_{frame_id}.jpg"
        tile = overlay(bgr, labels, classes, way, target, region, splits)
        cv2.imwrite(str(args.out / "overlay" / name), tile, [cv2.IMWRITE_JPEG_QUALITY, 90])
        caption = f"#{row['n']} b{row['branches']}"
        every.append((caption, tile))
        if row["branches"] >= 2:
            multi.append((caption, tile))
        rows.append(row)
    with open(args.out / "frames.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for tag, tiles in (("multi", multi), ("all", every)):
        for k in range(0, len(tiles), TILES):
            sheet(tiles[k:k + TILES], args.out / f"sheet-{tag}-{k // TILES:02d}.jpg")
    counts = np.bincount([r["branches"] for r in rows])
    print(f"{len(rows)} frames; branches histogram {dict(enumerate(counts.tolist()))}; out {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
