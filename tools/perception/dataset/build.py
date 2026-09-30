"""Build a training dataset from a CVAT export.

    build.py <cvat_export.zip | dir> --frames <frames_dir>... --classes classes.yaml
             --out data/perception/datasets/<name> [--delete INDEX|SESSION/INDEX ...]

classes.yaml is the single source of truth for names and indices. Colours are
NOT trusted from it: CVAT may recolour labels, so the export's labelmap.txt maps
colour -> label name and classes.yaml maps name -> index. CVAT always exports the
background as the label "background", so the class with role "background" (exactly
one required) is matched by that label; every other label is matched by class name.

Mask PNGs (any depth under SegmentationClass/) are named "<session>__<index:06d>"
(prelabel.py) or by bare frame index when that is unambiguous. Frames without a
mask, or listed with --delete (SESSION__NNNNNN or SESSION/N), are left out.
Split is by session so neighbouring frames never straddle it.

    build.py --auto-labels <labels_dir>... --store <store> --name <name>

builds the same schema from autolabel.py outputs (D-379) into the D-373 store
layout <store>/datasets/<name>/<content_sha>/; classes come from the labels."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import cv2
import numpy as np

SCHEMA = "rosy.perception.dataset/1"
_SENSING = str(Path(__file__).resolve().parents[3] / "src" / "runtime" / "sensing")
if _SENSING not in sys.path:
    sys.path.insert(0, _SENSING)
from control.sensing.perception.learned.manifest import ROLES  # noqa: E402  the closed list
# Mask value for unlabelled pixels (manifest "ignore_index"): excluded from the
# loss, never a class. D-379 addendum 2026-10-01.
IGNORE_INDEX = 255
MIN_SESSIONS_MSG = "need at least 2 sessions for a session-level split"


class BuildError(ValueError):
    pass


def load_classes(path, require_color: bool = True) -> list[dict]:
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
        if color is None and not require_color:
            pass
        elif not (isinstance(color, (list, tuple)) and len(color) == 3):
            raise BuildError(f"classes.yaml: class {c.get('name')!r} needs color [r,g,b]")
        out.append({"index": int(c["index"]), "name": str(c["name"]), "role": str(c["role"]),
                    "color": None if color is None else [int(v) for v in color]})
    label_to_index(out)
    return out


def label_to_index(classes) -> dict[str, int]:
    """CVAT label name -> class index (background role is the label "background")."""
    unknown = sorted({c["role"] for c in classes} - set(ROLES))
    if unknown:
        raise BuildError(f"classes: unknown role {unknown}; the closed list is {ROLES}")
    if sum(c["role"] == "background" for c in classes) != 1:
        raise BuildError("classes: exactly one class with role background is required")
    if any(c["index"] == IGNORE_INDEX for c in classes):
        raise BuildError(f"classes: index {IGNORE_INDEX} is the manifest ignore_index, not a class")
    names = [c["name"] for c in classes]
    if len(set(names)) != len(names):
        raise BuildError("classes: duplicate class names")
    colors = [tuple(c["color"]) for c in classes if c.get("color") is not None]
    if len(set(colors)) != len(colors):
        raise BuildError("classes: duplicate colors")
    return {("background" if c["role"] == "background" else c["name"]): c["index"]
            for c in classes}


def parse_labelmap(path: Path, classes) -> dict[tuple[int, int, int], int]:
    """labelmap.txt -> colour -> class index. Unknown label name -> BuildError."""
    names = label_to_index(classes)
    lut, seen = {}, set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, _, rest = line.partition(":")
        try:
            color = tuple(int(v) for v in rest.split(":")[0].split(","))
        except ValueError:
            color = ()
        if len(color) != 3:
            raise BuildError(f"{Path(path).name}: bad line {line!r}")
        if name not in names:
            raise BuildError(f"{Path(path).name}: label {name!r} is not in classes.yaml")
        if name in seen:
            raise BuildError(f"{Path(path).name}: duplicate label {name!r}")
        if color in lut:
            raise BuildError(f"{Path(path).name}: duplicate colour {color}")
        seen.add(name)
        lut[color] = names[name]
    return lut


def colors_to_indices(rgb: np.ndarray, lut, source: str) -> np.ndarray:
    """(H,W,3) uint8 RGB -> (H,W) uint8 class index via lut {(r,g,b): index}."""
    keys = {(r << 16) | (g << 8) | b: i for (r, g, b), i in lut.items()}
    packed = ((rgb[..., 0].astype(np.uint32) << 16) | (rgb[..., 1].astype(np.uint32) << 8)
              | rgb[..., 2].astype(np.uint32))
    out = np.zeros(packed.shape, np.uint8)
    for value in np.unique(packed):
        v = int(value)
        if v not in keys:
            raise BuildError(
                f"{source}: unknown colour ({(v >> 16) & 255},{(v >> 8) & 255},{v & 255})")
        out[packed == value] = keys[v]
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


_DELETE_RE = re.compile(r"^(?P<session>.+?)(?:__|/)(?P<index>\d+)$")


def _normalise_deletes(entries, frames) -> set[tuple[str, int]]:
    out = set()
    for e in entries:
        m = _DELETE_RE.match(str(e))
        if not m:
            raise BuildError(f"--delete {e!r}: use SESSION__NNNNNN or SESSION/N "
                             "(a bare index is ambiguous across sessions)")
        key = (m["session"], int(m["index"]))
        if key not in frames:
            raise BuildError(f"--delete {e!r}: no such frame "
                             f"({key[0]}__{key[1]:06d}) in --frames")
        out.add(key)
    return out


def build_dataset(export, frame_dirs, classes, out, deleted_indexes=()) -> dict:
    """deleted_indexes: "session__index" or "session/index" strings."""
    out, export = Path(out), Path(export)
    frames = _read_frames(frame_dirs)
    deleted = _normalise_deletes(deleted_indexes, frames)
    labelmaps = sorted(export.rglob("labelmap.txt"))
    if not labelmaps:
        raise BuildError(f"{export}: labelmap.txt missing from the CVAT export")
    lut = parse_labelmap(labelmaps[0], classes)
    masks = sorted((export / "SegmentationClass").rglob("*.png"))
    if not masks:
        raise BuildError(f"{export}: no SegmentationClass/*.png")

    kept = []
    for p in masks:
        session, index = _resolve(p.stem, frames, p.name)
        if (session, index) in deleted:
            continue
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            raise BuildError(f"{p.name}: unreadable PNG")
        kept.append(((session, index), colors_to_indices(bgr[..., ::-1], lut, p.name)))
    splits = assign_splits(k[0] for k, _ in kept)

    entries, sources = [], []
    for (session, index), mask in kept:
        src, meta = frames[(session, index)]
        img_rel, mask_rel = (f"images/{session}/{session}__{index:06d}.jpg",
                             f"masks/{session}/{session}__{index:06d}.png")
        (out / img_rel).parent.mkdir(parents=True, exist_ok=True)
        (out / mask_rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out / img_rel)
        cv2.imwrite(str(out / mask_rel), mask)
        entries.append({"image": img_rel, "mask": mask_rel, "session": session,
                        "split": splits[session]})
        if meta is not None and meta not in sources:
            sources.append(meta)
    # CVAT paints every pixel background or a label, so a CVAT mask holds no
    # IGNORE_INDEX pixel; the field still states the schema's unlabelled value.
    manifest = {"schema": SCHEMA, "classes": classes, "frames": entries,
                "deleted_indexes": sorted(f"{s}__{i:06d}" for s, i in deleted),
                "sources": sources, "ignore_index": IGNORE_INDEX}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def content_sha(folder) -> str:
    """D-373 decision 8 store version: sha256 over sorted "relpath\\0filesha256\\n" lines.

    Minimal stand-in until tools/perception/store.py (feat/d373-learning-loop-lap2)
    lands on main; switch to it then and keep this layout."""
    folder = Path(folder)
    lines = []
    for p in folder.rglob("*"):
        if p.is_file():
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            lines.append(f"{p.relative_to(folder).as_posix()}\0{h.hexdigest()}\n")
    return hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()


def build_auto_dataset(label_dirs, store, name, min_labelled: float = 0.05) -> tuple[dict, Path]:
    """D-379: dataset from autolabel.py outputs, in the same schema, into
    <store>/datasets/<name>/<content_sha>/ (a version folder is never rewritten).

    Frames whose sources disagree (label record "conflict") are left out and listed in
    deleted_indexes and excluded[]; frames with less than min_labelled of their
    pixels labelled (not the ignore class) are left out too."""
    metas, entries, sources, excluded, versions = [], [], [], [], []
    classes = None
    for d in map(Path, label_dirs):
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if classes is None:
            classes = meta["classes"]
            label_to_index(classes)
        elif meta["classes"] != classes:
            raise BuildError(f"{d}: classes differ from {label_dirs[0]}")
        metas.append((d, meta))
    if classes is None:
        raise BuildError("no label folders")
    seen = {}
    for d, meta in metas:
        if meta["session"] in seen:
            raise BuildError(f"session {meta['session']!r} is in both {seen[meta['session']]} and {d}: "
                             "one label folder per session")
        seen[meta["session"]] = d
    # ignore_index: mask value for unlabelled pixels, masked out of the loss; it is
    # not a class (a class with role "ignore" is an output channel nobody reads).
    ignore = metas[0][1].get("ignore_index", IGNORE_INDEX)
    if any(m.get("ignore_index", IGNORE_INDEX) != ignore for _, m in metas):
        raise BuildError("label folders disagree on ignore_index")
    if ignore in {c["index"] for c in classes}:
        raise BuildError(f"ignore_index {ignore} is also a class index")
    allowed = {c["index"] for c in classes} | {ignore}
    # Argument order must not change the manifest, hence the content sha.
    metas.sort(key=lambda dm: dm[1]["session"])
    splits = assign_splits(m["session"] for _, m in metas)
    tmp = Path(store) / "datasets" / name / f".staging-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        for d, meta in metas:
            session = meta["session"]
            jl = d / "labels.jsonl"
            recs = sorted((json.loads(line) for line in jl.read_text(encoding="utf-8").splitlines()
                           if line.strip()), key=lambda r: int(r["index"]))
            # digest of the rows in index order, so row order in the file does not matter
            digest = hashlib.sha256("".join(json.dumps(r, sort_keys=True) + "\n"
                                            for r in recs).encode("utf-8")).hexdigest()
            versions.append({"session": session, "version": meta.get("version"),
                             "camera": meta.get("camera"), "labels_digest": digest})
            if meta.get("session_json") and meta["session_json"] not in sources:
                sources.append(meta["session_json"])
            for rec in recs:
                idx = int(rec["index"])
                key = f"{session}__{idx:06d}"
                mask = cv2.imread(str(d / "masks" / f"{idx:06d}.png"), cv2.IMREAD_UNCHANGED)
                if mask is None or mask.ndim != 2:
                    raise BuildError(f"{d}: mask {idx:06d}.png missing or not single-channel")
                bad = set(np.unique(mask).tolist()) - allowed
                if bad:
                    raise BuildError(f"{d}: mask {idx:06d}.png has values {sorted(bad)} that are "
                                     f"neither a class index nor ignore_index {ignore}")
                labelled = float((mask != ignore).mean())
                if rec.get("conflict"):
                    excluded.append({"frame": key, "reason": "sources disagree",
                                     "disagreement": rec.get("disagreement")})
                    continue
                if labelled < min_labelled:
                    excluded.append({"frame": key, "reason": f"labelled {labelled:.3f} < {min_labelled}"})
                    continue
                rel = {"image": f"images/{session}/{key}.jpg", "mask": f"masks/{session}/{key}.png",
                       "conf": f"conf/{session}/{key}.png"}
                for kind, src in (("image", d / "frames" / f"{idx:06d}.jpg"),
                                  ("mask", d / "masks" / f"{idx:06d}.png"),
                                  ("conf", d / "conf" / f"{idx:06d}.png")):
                    (tmp / rel[kind]).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, tmp / rel[kind])
                entries.append({**rel, "session": session, "split": splits[session],
                                "sources": rec.get("sources", []), "version": rec.get("version")})
        manifest = {"schema": SCHEMA, "classes": classes, "frames": entries,
                    "deleted_indexes": sorted(e["frame"] for e in excluded if e["reason"] == "sources disagree"),
                    "sources": sources, "ignore_index": ignore, "labels": versions,
                    "excluded": excluded, "builder": "build.py --auto-labels (D-379)"}
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        final = tmp.parent / content_sha(tmp)
        if final.exists():
            shutil.rmtree(tmp)
        else:
            os.replace(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return manifest, final


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("export", type=Path, nargs="?")
    ap.add_argument("--frames", type=Path, nargs="+")
    ap.add_argument("--classes", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--delete", nargs="*", default=[])
    ap.add_argument("--auto-labels", type=Path, nargs="+",
                    help="D-379: autolabel.py output folders instead of a CVAT export")
    ap.add_argument("--store", type=Path, help="with --auto-labels: store root (D-373 decision 8)")
    ap.add_argument("--name", help="with --auto-labels: dataset name")
    ap.add_argument("--min-labelled", type=float, default=0.05)
    args = ap.parse_args(argv)
    if args.auto_labels:
        if not (args.store and args.name):
            ap.error("--auto-labels needs --store and --name")
        try:
            manifest, final = build_auto_dataset(args.auto_labels, args.store, args.name,
                                                 args.min_labelled)
        except BuildError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{len(manifest['frames'])} frames ({len(manifest['excluded'])} left out) -> {final}")
        return 0
    if not (args.export and args.frames and args.classes and args.out):
        ap.error("a CVAT build needs export, --frames, --classes and --out")
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
