"""Pre-label frames with a learned lane model and pack a CVAT import zip.

    prelabel.py <frames_dir> --model <model_folder> --classes classes.yaml --out <dir>

Writes into <dir>:
  cvat_import.zip   CVAT "Segmentation mask 1.1": labelmap.txt (colours from
                    classes.yaml; DEFAULT_PALETTE only for a class without color),
                    SegmentationClass/<name>.png, ImageSets/Segmentation/default.txt
  images/<name>.jpg the frames under the exact names used in the zip; upload THESE
                    to the CVAT task, then import the zip
  masks/, preview/  grey index masks and colour previews
  ranking.csv       most uncertain first
<name> is "<session>__<index:06d>". The background-role class is exported under the
CVAT label "background" (build.py maps it back by role)."""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

import build

ROOT = Path(__file__).resolve().parents[4]
_SENSING = str(ROOT / "src" / "runtime" / "sensing")
_FOUNDATION = str(ROOT / "src" / "contracts" / "foundation")  # core_common (D-424)
for _p in (_SENSING, _FOUNDATION):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from control.recording import SHADOW_TOPIC as SHADOW_KEY  # noqa: E402  extract.py's side key
LANE_MIN_FRACTION = 0.02  # below this share of lane pixels the frame is suspect
# RGB fallback for classes.yaml entries without a color, by class index.
DEFAULT_PALETTE = ((0, 0, 0), (230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200),
                   (245, 130, 48), (145, 30, 180), (70, 240, 240), (240, 50, 230))


def resolve_classes(yaml_classes, model_classes) -> list[dict]:
    """classes.yaml must describe the model's classes; fill missing colours."""
    build.label_to_index([dict(c, color=None) for c in yaml_classes])  # closed roles, one background
    got = [(c["index"], c["name"], c["role"]) for c in yaml_classes]
    want = [(c.index, c.name, c.role) for c in model_classes]
    if sorted(got) != sorted(want):
        raise build.BuildError(f"classes.yaml does not match the model manifest classes "
                               f"({sorted(got)} vs {sorted(want)})")
    out = []
    for c in sorted(yaml_classes, key=lambda c: c["index"]):
        color = c["color"]
        if color is None:
            color = list(DEFAULT_PALETTE[c["index"] % len(DEFAULT_PALETTE)])
        out.append(dict(c, color=color))
    colors = [tuple(c["color"]) for c in out]
    if len(set(colors)) != len(colors):
        raise build.BuildError("classes: duplicate colors (after default-palette fill)")
    return out


def score_frame(logits: np.ndarray, classes, side: dict, model_revision: str) -> dict:
    """One formula for every row, from the current model: (1 - confidence) + mean
    normalised pixel entropy + lane-pixel shortage. |error_delta| is added only when
    the recorded shadow payload came from this same model revision."""
    from control.sensing.perception.learned.lane_mask import lane_evidence
    ev = lane_evidence(logits, classes)
    z = logits[0].astype(np.float64)
    z -= z.max(axis=0, keepdims=True)
    p = np.exp(z)
    p /= p.sum(axis=0, keepdims=True)
    entropy = float(-(p * np.log(np.clip(p, 1e-12, None))).sum(axis=0).mean()
                    / math.log(len(classes)))
    lane = sum(ev.class_fractions[c.name] for c in classes if c.role == "lane_marking")
    shortage = max(0.0, 1.0 - lane / LANE_MIN_FRACTION)
    rec = (side or {}).get(SHADOW_KEY)
    rec = rec if isinstance(rec, dict) else {}  # extract keeps non-JSON text as a str
    delta = rec.get("error_delta") if rec.get("model_revision") == model_revision else None
    score = (1.0 - ev.confidence) + entropy + shortage + (abs(delta) if delta is not None else 0.0)
    return {"score": score, "confidence": ev.confidence, "error_delta": delta,
            "entropy": entropy, "lane_shortage": shortage, "recorded": delta is not None}


def frame_name(session: str, index: int) -> str:
    return f"{session}__{index:06d}"


def labelmap_text(classes) -> str:
    """classes: resolved dicts. Background role is exported as label "background"."""
    lines = ["# label:color_rgb:parts:actions"]
    for c in classes:
        name = "background" if c["role"] == "background" else c["name"]
        lines.append(f"{name}:{c['color'][0]},{c['color'][1]},{c['color'][2]}::")
    return "\n".join(lines) + "\n"


def colorize(mask: np.ndarray, classes) -> np.ndarray:
    """Index mask -> BGR image using the class colours."""
    lut = np.zeros((256, 3), np.uint8)
    for c in classes:
        lut[c["index"]] = c["color"][::-1]
    return lut[mask]


def write_upload_image(out: Path, name: str, bgr: np.ndarray, src: Path | None) -> Path:
    """The JPEG CVAT sees. Copy the original bytes when the source is a .jpg."""
    path = Path(out) / "images" / f"{name}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    if src is not None and Path(src).suffix.lower() in (".jpg", ".jpeg"):
        shutil.copyfile(src, path)
    elif not cv2.imwrite(str(path), bgr):
        raise RuntimeError(f"cannot write {path}")
    return path


def write_cvat_zip(path: Path, classes, items) -> None:
    """items: [(name, index_mask)]. Layout of CVAT 'Segmentation mask 1.1'."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("labelmap.txt", labelmap_text(classes))
        z.writestr("ImageSets/Segmentation/default.txt",
                   "".join(f"{n}\n" for n, _ in items))
        for name, mask in items:
            ok, buf = cv2.imencode(".png", colorize(mask, classes))
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
    ap.add_argument("--classes", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    from control.sensing.perception.learned.lane_mask import preprocess
    model, session = _open_model(args.model)
    try:
        classes = resolve_classes(build.load_classes(args.classes, require_color=False),
                                  model.manifest.classes)
    except build.BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
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
        cv2.imwrite(str(args.out / "preview" / f"{name}.png"), colorize(mask, classes))
        write_upload_image(args.out, name, bgr,
                           args.frames_dir / "frames" / f"{index:06d}.jpg")
        ranking.append((name, score_frame(logits, model.manifest.classes, row.get("side"),
                                          model.model_revision)))
        items.append((name, mask))

    ranking.sort(key=lambda r: r[1]["score"], reverse=True)
    cols = ["score", "confidence", "error_delta", "entropy", "lane_shortage", "recorded"]
    with open(args.out / "ranking.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name"] + cols)
        w.writerows([n] + [r[c] for c in cols] for n, r in ranking)
    write_cvat_zip(args.out / "cvat_import.zip", classes, items)
    print(f"prelabelled {len(items)} frames -> {args.out}")
    print(f"Upload {args.out / 'images'}/*.jpg to the CVAT task (names must stay as they "
          f"are), then import {args.out / 'cvat_import.zip'} as 'Segmentation mask 1.1'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
