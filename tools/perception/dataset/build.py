"""Build a training dataset from a CVAT export.

    build.py <cvat_export.zip | dir> --frames <frames_dir>... --classes classes.yaml
             --out data/perception/datasets/<name> [--delete INDEX|SESSION/INDEX ...]

Mask PNGs are named "<session>__<index:06d>" (prelabel.py) or by bare frame
index when that is unambiguous. Frames without a mask, or listed with --delete,
are left out. Split is by session so neighbouring frames never straddle it."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import cv2
import numpy as np

SCHEMA = "rosy.perception.dataset/1"
MIN_SESSIONS_MSG = "need at least 2 sessions for a session-level split"


class BuildError(ValueError):
    pass


def load_classes(path) -> list[dict]:
    try:
        import yaml
    except ImportError as exc:
        raise BuildError("PyYAML is required to read classes.yaml (pip install pyyaml)") from exc
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    classes = doc.get("classes") if isinstance(doc, dict) else None
    if not classes:
        raise BuildError("classes.yaml: no classes")
    out = []
    for c in classes:
        color = c.get("color")
        if not (isinstance(color, (list, tuple)) and len(color) == 3):
            raise BuildError(f"classes.yaml: class {c.get('name')!r} needs color [r,g,b]")
        out.append({"index": int(c["index"]), "name": str(c["name"]),
                    "role": str(c["role"]), "color": [int(v) for v in color]})
    return out


def colors_to_indices(rgb: np.ndarray, classes, source: str) -> np.ndarray:
    """(H,W,3) uint8 RGB -> (H,W) uint8 class index. Unknown colour -> BuildError."""
    lut = {(c["color"][0] << 16) | (c["color"][1] << 8) | c["color"][2]: c["index"]
           for c in classes}
    packed = ((rgb[..., 0].astype(np.uint32) << 16) | (rgb[..., 1].astype(np.uint32) << 8)
              | rgb[..., 2].astype(np.uint32))
    out = np.zeros(packed.shape, np.uint8)
    for value in np.unique(packed):
        v = int(value)
        if v not in lut:
            raise BuildError(
                f"{source}: unknown colour ({(v >> 16) & 255},{(v >> 8) & 255},{v & 255})")
        out[packed == value] = lut[v]
    return out


def assign_splits(sessions) -> dict[str, str]:
    ordered = sorted(set(sessions))
    if len(ordered) < 2:
        raise BuildError(MIN_SESSIONS_MSG)
    return {s: ("val" if i % 5 == 0 else "train") for i, s in enumerate(ordered)}


def _read_frames(dirs) -> dict[tuple[str, int], tuple[Path, dict | None]]:
    """(session, index) -> (jpg path, session.json contents or None)."""
    found = {}
    for d in map(Path, dirs):
        sj = d / "session.json"
        meta = json.loads(sj.read_text(encoding="utf-8")) if sj.is_file() else None
        for line in (d / "frames.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            key = (str(row.get("session") or d.name), int(row["index"]))
            found[key] = (d / "frames" / f"{int(row['index']):06d}.jpg", meta)
    return found


def _resolve(stem: str, frames, source: str) -> tuple[str, int]:
    if "__" in stem:
        session, _, idx = stem.rpartition("__")
        if idx.isdigit() and (session, int(idx)) in frames:
            return (session, int(idx))
    elif stem.isdigit():
        hits = [k for k in frames if k[1] == int(stem)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise BuildError(f"{source}: frame index {stem} is ambiguous across --frames dirs")
    raise BuildError(f"{source}: no matching frame for {stem!r}")


def build_dataset(export, frame_dirs, classes, out, deleted_indexes=()) -> dict:
    """deleted_indexes: ints (any session) or "session/index" strings."""
    out = Path(out)
    frames = _read_frames(frame_dirs)
    deleted = {str(d) for d in deleted_indexes}
    masks = sorted((Path(export) / "SegmentationClass").glob("*.png"))
    if not masks:
        raise BuildError(f"{export}: no SegmentationClass/*.png")

    kept = []
    for p in masks:
        session, index = _resolve(p.stem, frames, p.name)
        if str(index) in deleted or f"{session}/{index}" in deleted:
            continue
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            raise BuildError(f"{p.name}: unreadable PNG")
        kept.append(((session, index), colors_to_indices(bgr[..., ::-1], classes, p.name)))
    splits = assign_splits(k[0] for k, _ in kept)

    entries, sources = [], []
    for (session, index), mask in kept:
        src, meta = frames[(session, index)]
        img_rel, mask_rel = f"images/{session}/{index}.jpg", f"masks/{session}/{index}.png"
        (out / img_rel).parent.mkdir(parents=True, exist_ok=True)
        (out / mask_rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out / img_rel)
        cv2.imwrite(str(out / mask_rel), mask)
        entries.append({"image": img_rel, "mask": mask_rel, "session": session,
                        "split": splits[session]})
        if meta is not None and meta not in sources:
            sources.append(meta)
    manifest = {"schema": SCHEMA, "classes": classes, "frames": entries,
                "deleted_indexes": sorted(deleted), "sources": sources}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("export", type=Path)
    ap.add_argument("--frames", type=Path, nargs="+", required=True)
    ap.add_argument("--classes", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--delete", nargs="*", default=[])
    args = ap.parse_args(argv)
    try:
        classes = load_classes(args.classes)
        if args.export.is_file():
            with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(args.export) as z:
                z.extractall(tmp)
                manifest = build_dataset(tmp, args.frames, classes, args.out, args.delete)
        else:
            manifest = build_dataset(args.export, args.frames, classes, args.out, args.delete)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{len(manifest['frames'])} frames -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
