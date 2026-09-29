"""Pre-label frames with a learned lane model and pack a CVAT import zip.

    prelabel.py <frames_dir> --model <model_folder> --out <dir>

Writes masks/<name>.png (grey class index), preview/<name>.png (colour),
ranking.csv (most uncertain first) and cvat_import.zip (Segmentation mask 1.1).
<name> is "<session>__<index:06d>" so build.py can find the frame again."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
_SENSING = str(ROOT / "src" / "runtime" / "sensing")
if _SENSING not in sys.path:
    sys.path.insert(0, _SENSING)

SHADOW_KEY = "perception/learned/shadow"
# RGB, indexed by class index; index 0 is black (CVAT background).
PALETTE = ((0, 0, 0), (230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200),
           (245, 130, 48), (145, 30, 180), (70, 240, 240), (240, 50, 230))


def class_color(index: int) -> tuple[int, int, int]:
    return PALETTE[index % len(PALETTE)]


def rank_score(confidence: float, error_delta: float | None) -> float:
    """Higher = more worth a human's time."""
    return (1.0 - confidence) + (abs(error_delta) if error_delta is not None else 0.0)


def frame_name(session: str, index: int) -> str:
    return f"{session}__{index:06d}"


def labelmap_text(classes) -> str:
    lines = ["# label:color_rgb:parts:actions"]
    for c in classes:
        r, g, b = class_color(c.index)
        lines.append(f"{c.name}:{r},{g},{b}::")
    return "\n".join(lines) + "\n"


def colorize(mask: np.ndarray) -> np.ndarray:
    """Index mask -> BGR image using PALETTE."""
    lut = np.array([class_color(i)[::-1] for i in range(256)], np.uint8)
    return lut[mask]


def write_cvat_zip(path: Path, classes, items) -> None:
    """items: [(name, index_mask)]. Layout of CVAT 'Segmentation mask 1.1'."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("labelmap.txt", labelmap_text(classes))
        z.writestr("ImageSets/Segmentation/default.txt",
                   "".join(f"{n}\n" for n, _ in items))
        for name, mask in items:
            ok, buf = cv2.imencode(".png", colorize(mask))
            if not ok:
                raise RuntimeError(f"cannot encode {name}")
            z.writestr(f"SegmentationClass/{name}.png", buf.tobytes())


def _open_model(folder):
    """LaneSegModel plus the raw session it validated (for per-pixel logits)."""
    from control.sensing.perception.learned.runner import LaneSegModel
    sessions = []

    def factory(path, threads):
        import onnxruntime as ort  # lazy
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        s = ort.InferenceSession(str(path), sess_options=opts,
                                 providers=["CPUExecutionProvider"])
        in_name = s.get_inputs()[0].name

        class _Session:
            def run(self, x):
                return s.run(None, {in_name: x})[0]
        sessions.append(_Session())
        return sessions[-1]

    return LaneSegModel.open(folder, session_factory=factory), sessions[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("frames_dir", type=Path)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    from control.sensing.perception.learned.lane_mask import lane_evidence, preprocess
    model, session = _open_model(args.model)
    spec = model.manifest.input
    rows = [json.loads(line) for line in
            (args.frames_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    (args.out / "masks").mkdir(parents=True, exist_ok=True)
    (args.out / "preview").mkdir(exist_ok=True)

    items, ranking = [], []
    for row in rows:
        index = int(row["index"])
        bgr = cv2.imread(str(args.frames_dir / "frames" / f"{index:06d}.jpg"))
        if bgr is None:
            print(f"skip {index}: unreadable", file=sys.stderr)
            continue
        logits = session.run(preprocess(bgr, spec))
        mask = logits[0].argmax(axis=0).astype(np.uint8)
        mask = cv2.resize(mask, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
        name = frame_name(str(row.get("session") or args.frames_dir.name), index)
        cv2.imwrite(str(args.out / "masks" / f"{name}.png"), mask)
        cv2.imwrite(str(args.out / "preview" / f"{name}.png"), colorize(mask))
        side = (row.get("side") or {}).get(SHADOW_KEY) or {}
        confidence = side.get("confidence")
        if confidence is None:
            confidence = lane_evidence(logits, model.manifest.classes).confidence
        delta = side.get("error_delta")
        ranking.append((name, rank_score(float(confidence), delta), float(confidence), delta))
        items.append((name, mask))

    ranking.sort(key=lambda r: r[1], reverse=True)
    with open(args.out / "ranking.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "score", "confidence", "error_delta"])
        w.writerows(ranking)
    write_cvat_zip(args.out / "cvat_import.zip", model.manifest.classes, items)
    print(f"prelabelled {len(items)} frames -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
