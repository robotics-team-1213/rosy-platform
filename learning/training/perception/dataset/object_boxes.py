"""D-423 §2.5: candidate object boxes from LiDAR clusters, and a review step where people win.

lidar_object_boxes  short runs of scan returns (scan_segments, the D-379 wall labeller's
                    splitter) that are too small to be a wall become candidate boxes:
                    columns from the run's points, the bottom row at their floor contact,
                    the top at the scan-plane height -- a lower bound, since the LiDAR only
                    proves the object reaches its plane. No class: a person names it.
merge_review        human boxes win; a human box labelled "none" rejects the auto boxes
                    it overlaps; auto boxes no person touched stay unlabelled (queue).
to_yolo_lines       labelled boxes in the object_det contract class order (manifest
                    OBJECT_CLASSES), normalised centre-size.

CLI: object_boxes.py <labels.jsonl> --human <human.jsonl> --out <new-dir> --size W H
writes <dir>/<index>.txt only for review_status="approved", complete_frame_review=true
and an explicit boxes list. An empty file means "nothing there", which only a person's
complete approved review may claim. Other rows remain in review_queue.jsonl.
These review flags describe annotation completion, not authenticated reviewer identity."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
for _p in (HERE, ROOT / "src" / "runtime" / "sensing",
           ROOT / "src" / "contracts" / "foundation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from labels import scan_segments  # noqa: E402
from control.sensing.perception.learned.manifest import OBJECT_CLASSES  # noqa: E402

MAX_OBJECT_EXTENT_M = 0.45  # longer runs are walls (the D-379 wall labeller owns them)
MIN_POINTS = 3
MIN_BOX_PX = 4
REVIEW_IOU = 0.3
REJECT = "none"


def lidar_object_boxes(cam, xy, *, lidar_height_m, frame_size=None):
    """Candidate boxes (bbox_xyxy, distance_m, n_points, source, label=None, top) per small run."""
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    w, h = frame_size or (int(round(2 * cam.cx)), int(round(2 * cam.cy)))
    boxes = []
    for run in scan_segments(xy):
        pts = xy[run]
        if len(pts) < MIN_POINTS or np.ptp(pts, axis=0).max() > MAX_OBJECT_EXTENT_M:
            continue
        ground = np.column_stack([pts, np.zeros(len(pts))])
        top = np.column_stack([pts, np.full(len(pts), lidar_height_m)])
        u, v, depth = cam.project(np.concatenate([ground, top]))
        if not np.all(depth > 0):
            continue
        x0, x1 = max(0.0, float(u.min())), min(float(w), float(u.max()))
        y0, y1 = max(0.0, float(v.min())), min(float(h), float(v.max()))
        if x1 - x0 < MIN_BOX_PX or y1 - y0 < MIN_BOX_PX:
            continue
        boxes.append({"bbox_xyxy": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                      "distance_m": round(float((pts[:, 0] - cam.x_offset_m).min()), 4),
                      "n_points": int(len(pts)), "source": "lidar_cluster", "label": None,
                      "top": "scan_plane_lower_bound"})
    return boxes


def _iou(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    inter = max(w, 0) * max(h, 0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _check_human_box(box):
    """A review row: {bbox_xyxy: four finite numbers with x0 < x1, y0 < y1, label}."""
    if not isinstance(box, dict):
        raise ValueError(f"human row must be an object, got {box!r}")
    xyxy = box.get("bbox_xyxy")
    if (not isinstance(xyxy, (list, tuple)) or len(xyxy) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                       for v in xyxy)
            or not (xyxy[0] < xyxy[2] and xyxy[1] < xyxy[3])):
        raise ValueError(f"human row bbox_xyxy must be [x0, y0, x1, y1] with x0<x1, y0<y1: {xyxy!r}")


def merge_review(auto, human, min_iou=REVIEW_IOU):
    """Human boxes (labelled) first, then auto boxes no human box overlaps."""
    for box in human:
        _check_human_box(box)
        if box.get("label") not in OBJECT_CLASSES + (REJECT,):
            raise ValueError(f"unknown class {box.get('label')!r}; one of {OBJECT_CLASSES} or {REJECT!r}")
    kept = [dict(box, source="human") for box in human if box["label"] != REJECT]
    rest = [dict(box) for box in auto
            if not any(_iou(box["bbox_xyxy"], h["bbox_xyxy"]) >= min_iou for h in human)]
    return kept + rest


def needs_review(boxes):
    return [box for box in boxes if box.get("label") is None]


def to_yolo_lines(boxes, size):
    w, h = size
    lines = []
    for box in boxes:
        if box.get("label") not in OBJECT_CLASSES:
            continue
        x0, y0, x1, y1 = box["bbox_xyxy"]
        lines.append(f"{OBJECT_CLASSES.index(box['label'])} {(x0 + x1) / 2 / w:.6f} {(y0 + y1) / 2 / h:.6f} "
                     f"{(x1 - x0) / w:.6f} {(y1 - y0) / h:.6f}")
    return lines


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _indexed_rows(path):
    rows = {}
    for row in _rows(path):
        if not isinstance(row, dict) or type(row.get("index")) is not int or row["index"] < 0:
            raise ValueError("review/source index must be a nonnegative integer")
        if row["index"] in rows:
            raise ValueError("duplicate review/source index")
        rows[row["index"]] = row
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("labels", help="autolabel labels.jsonl (rows carry 'objects' with --object-boxes)")
    ap.add_argument("--human", help='rows: {index, review_status:"approved", complete_frame_review:true, '
                                   'boxes:[{bbox_xyxy,label}]} (pending/partial rows stay queued)')
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, nargs=2, required=True, metavar=("W", "H"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        raise ValueError("new output directory required; prior labels are never reused or overwritten")
    if any(v <= 0 for v in args.size):
        raise ValueError("positive image size required")
    source = _indexed_rows(args.labels)
    human = _indexed_rows(args.human) if args.human else {}
    if set(human) - set(source):
        raise ValueError("human review index absent from source labels")
    queue, exports = [], {}
    for row in source.values():
        auto = row.get("objects", [])
        review = human.get(row["index"])
        if (review is None or review.get("review_status") != "approved"
                or review.get("complete_frame_review") is not True):
            queue.append({"index": row["index"], "objects": auto, "review": review,
                          "reason": "complete_approved_review_required"})
            continue
        if not isinstance(review.get("boxes"), list):
            raise ValueError("complete approved review requires an explicit boxes list")
        for box in review["boxes"]:
            _check_human_box(box)
            x0, y0, x1, y1 = box["bbox_xyxy"]
            if not (0 <= x0 < x1 <= args.size[0] and 0 <= y0 < y1 <= args.size[1]):
                raise ValueError("review box outside image bounds")
        merged = merge_review(auto, review["boxes"])
        if needs_review(merged):
            queue.append({"index": row["index"], "objects": merged, "review": review,
                          "reason": "unlabelled_candidate_boxes"})
            continue
        for box in merged:
            _check_human_box(box)
            x0, y0, x1, y1 = box["bbox_xyxy"]
            if not (0 <= x0 < x1 <= args.size[0] and 0 <= y0 < y1 <= args.size[1]):
                raise ValueError("review box outside image bounds")
        exports[row["index"]] = to_yolo_lines(merged, args.size)
    out.mkdir(parents=True, exist_ok=False)
    for index, lines in exports.items():
        (out / f"{index:06d}.txt").write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    (out / "review_queue.jsonl").write_text("".join(json.dumps(q) + "\n" for q in queue), encoding="utf-8")
    print(f"{len(exports)} complete approved frames exported, {len(queue)} waiting in {out / 'review_queue.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
