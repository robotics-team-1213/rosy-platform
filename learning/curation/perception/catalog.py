"""D-379 session catalog: data/perception/catalog.jsonl, one row per real session.

    catalog.py scan   [--root data/perception] [--video-dir DIR ...] [--store DIR]
    catalog.py add    <session_dir> [--driver human|logic|claude-scripted] [--tags a,b]
    catalog.py update-tags <session> [--add a,b] [--remove c] [--driver X] [--error D-378/E1]
    catalog.py list   [--tag T]

A row holds who drove, scene tags, duration, the topics present, sha256 of every
raw file, the derived artefacts (compressed video + sidecar from bag_to_video.py,
extracted frames, auto labels, dataset membership) and D-378 error references.
scan finds raw sessions under <root>/raw and refreshes their derived artefacts;
hashes are reused while a file's size and mtime are unchanged. Hand-set fields
(driver, tags, errors, notes) are never overwritten by scan.
The catalog lives in data/, which is gitignored: it never goes into the repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

SCHEMA = "rosy.perception.catalog/1"
REPO = Path(__file__).resolve().parents[3]
DRIVERS = ("human", "logic", "claude-scripted")
SCENE_TAGS = ("straight", "curve", "intersection", "stop_line", "crosswalk", "signal", "wall",
              "obstacle", "parking", "off_track")
HAND_FIELDS = ("driver", "driver_inferred", "scene_tags", "errors", "notes")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in sorted(rows, key=lambda r: r["session"]):
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def infer_driver(reason: str | None) -> str:
    text = (reason or "").lower()
    if "claude" in text:
        return "claude-scripted"
    if "logic" in text or "auto" in text:
        return "logic"
    return "human"


def _files(folder: Path, root: Path, old: dict) -> list[dict]:
    """sha256 per file; reuse the old hash while size and mtime match."""
    prev = {f["path"]: f for f in old.get("files", [])}
    out = []
    for p in sorted(x for x in folder.rglob("*") if x.is_file()):
        rel = p.relative_to(root).as_posix()
        st = p.stat()
        o = prev.get(rel)
        if o and o.get("bytes") == st.st_size and o.get("mtime_ns") == st.st_mtime_ns:
            out.append(o)
            continue
        out.append({"path": rel, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha256(p)})
    return out


def _topics(session: Path, meta: dict) -> dict:
    """relative topic name -> message count (bag metadata.yaml, else session.json list)."""
    md = session / "bag" / "metadata.yaml"
    if md.is_file():
        try:
            import yaml
            doc = yaml.safe_load(md.read_text(encoding="utf-8"))["rosbag2_bagfile_information"]
            ns = re.compile(r"^/[^/]+/")
            return {ns.sub("", t["topic_metadata"]["name"]).lstrip("/"): int(t["message_count"])
                    for t in doc.get("topics_with_message_count", [])}
        except (ImportError, KeyError, TypeError, ValueError):
            pass
    return {t: None for t in meta.get("topics", [])}


def _duration(meta: dict, session: Path) -> float | None:
    md = session / "bag" / "metadata.yaml"
    if md.is_file():
        m = re.search(r"duration:\s*\n\s*nanoseconds:\s*(\d+)", md.read_text(encoding="utf-8"))
        if m:
            return round(int(m.group(1)) / 1e9, 1)
    try:
        a = datetime.fromisoformat(meta["started_at"])
        b = datetime.fromisoformat(meta["ended_at"])
        return round((b - a).total_seconds(), 1)
    except (KeyError, TypeError, ValueError):
        return None


def _stamp(session_name: str) -> str | None:
    m = re.match(r"(\d{8}T\d{6}Z)", session_name)
    return m.group(1) if m else None


def derived(session_name: str, device: str, root: Path, video_dirs, store: Path | None) -> dict:
    """Artefacts made from a session, found by their naming conventions."""
    out = {"video": [], "frames": [], "labels": [], "datasets": []}
    stamp = _stamp(session_name)
    dev = re.sub(r"[^A-Za-z0-9_.-]", "-", device or "unknown")
    for d in map(Path, video_dirs):
        if not stamp or not d.is_dir():
            continue
        stem = f"teleop_{dev}_{stamp}"  # bag_to_video.output_stem
        mp4 = d / f"{stem}.mp4"
        if mp4.is_file():
            item = {"video": str(mp4)}
            for key, ext in (("sidecar", ".jsonl"), ("meta", ".json"), ("scan", ".scan.npz")):
                p = d / f"{stem}{ext}"
                if p.is_file():
                    item[key] = str(p)
            item["sha256"] = {k: sha256(Path(v)) for k, v in item.items()}
            out["video"].append(item)
    for fj in sorted((root / "frames").glob("*/frames.jsonl")):
        with open(fj, encoding="utf-8") as fh:
            first = fh.readline()
        try:
            if json.loads(first).get("session") == session_name:
                out["frames"].append(fj.parent.relative_to(root).as_posix())
        except ValueError:
            continue
    lm = root / "labels" / session_name / "meta.json"
    if lm.is_file():
        meta = json.loads(lm.read_text(encoding="utf-8"))
        jl = lm.parent / "labels.jsonl"
        out["labels"].append({"path": lm.parent.relative_to(root).as_posix(),
                              "version": meta.get("version"), "camera": meta.get("camera"),
                              "frames": (meta.get("totals") or {}).get("frames"),
                              "labels_sha256": sha256(jl) if jl.is_file() else None})
    if store is not None:
        for mf in sorted(store.glob("datasets/*/*/manifest.json")):
            doc = json.loads(mf.read_text(encoding="utf-8"))
            splits = {f["split"] for f in doc.get("frames", []) if f.get("session") == session_name}
            if splits:
                out["datasets"].append({"name": mf.parent.parent.name, "version": mf.parent.name,
                                        "split": sorted(splits)[0] if len(splits) == 1 else sorted(splits)})
    return out


def session_row(session: Path, root: Path, video_dirs=(), store: Path | None = None,
                old: dict | None = None) -> dict:
    old = old or {}
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    row = {
        "schema": SCHEMA,
        "session": session.name,
        "device": meta.get("device"),
        "reason": meta.get("reason"),
        "started_at": meta.get("started_at"),
        "ended_at": meta.get("ended_at"),
        "duration_s": _duration(meta, session),
        "topics": _topics(session, meta),
        "raw": session.relative_to(root).as_posix() if session.is_relative_to(root) else str(session),
        "files": _files(session, root if session.is_relative_to(root) else session.parent, old),
        "derived": derived(session.name, meta.get("device"), root, video_dirs, store),
        "driver": infer_driver(meta.get("reason")),
        "driver_inferred": True,
        "scene_tags": [],
        "errors": [],
        "notes": "",
    }
    row["has_scan"] = "scan" in row["topics"]
    for k in HAND_FIELDS:
        if k in old:
            row[k] = old[k]
    return row


def _split(text) -> list[str]:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO / "data" / "perception")
    ap.add_argument("--catalog", type=Path, help="default <root>/catalog.jsonl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--video-dir", type=Path, action="append", default=None)
    sc.add_argument("--store", type=Path)
    ad = sub.add_parser("add")
    ad.add_argument("session_dir", type=Path)
    ad.add_argument("--driver", choices=DRIVERS)
    ad.add_argument("--tags")
    ad.add_argument("--video-dir", type=Path, action="append", default=None)
    ad.add_argument("--store", type=Path)
    up = sub.add_parser("update-tags")
    up.add_argument("session")
    up.add_argument("--add")
    up.add_argument("--remove")
    up.add_argument("--driver", choices=DRIVERS)
    up.add_argument("--error", action="append", default=[], help="e.g. D-378/E1")
    up.add_argument("--note")
    ls = sub.add_parser("list")
    ls.add_argument("--tag")
    args = ap.parse_args(argv)
    root = args.root
    path = args.catalog or root / "catalog.jsonl"
    rows = {r["session"]: r for r in load(path)}

    def store_of(a):
        return a.store if a.store is not None else root / "store"

    def videos_of(a):
        return a.video_dir or [REPO / "data" / "teleop" / "learning"]

    if args.cmd == "scan":
        for sj in sorted((root / "raw").glob("*/session.json")):
            s = sj.parent
            rows[s.name] = session_row(s, root, videos_of(args), store_of(args), rows.get(s.name))
            print(f"{s.name}: {len(rows[s.name]['files'])} files, driver {rows[s.name]['driver']}")
    elif args.cmd == "add":
        s = args.session_dir.resolve()
        if not (s / "session.json").is_file():
            print(f"{s}: no session.json", file=sys.stderr)
            return 1
        row = session_row(s, root, videos_of(args), store_of(args), rows.get(s.name))
        if args.driver:
            row["driver"], row["driver_inferred"] = args.driver, False
        row["scene_tags"] = sorted(set(row["scene_tags"]) | set(_split(args.tags)))
        rows[s.name] = row
    elif args.cmd == "update-tags":
        row = rows.get(args.session)
        if row is None:
            print(f"{args.session}: not in {path}", file=sys.stderr)
            return 1
        unknown = [t for t in _split(args.add) if t not in SCENE_TAGS]
        if unknown:
            print(f"warning: tags outside {SCENE_TAGS}: {unknown}", file=sys.stderr)
        row["scene_tags"] = sorted((set(row["scene_tags"]) | set(_split(args.add))) - set(_split(args.remove)))
        if args.driver:
            row["driver"], row["driver_inferred"] = args.driver, False
        row["errors"] = sorted(set(row.get("errors", [])) | set(args.error))
        if args.note is not None:
            row["notes"] = args.note
    else:
        for r in sorted(rows.values(), key=lambda r: r["session"]):
            if args.tag and args.tag not in r.get("scene_tags", []):
                continue
            d = r.get("derived", {})
            print(f"{r['session']}  {r.get('driver'):15s} {r.get('duration_s')}s "
                  f"scan={'y' if r.get('has_scan') else 'n'} tags={','.join(r.get('scene_tags', []))} "
                  f"video={len(d.get('video', []))} labels={len(d.get('labels', []))} "
                  f"datasets={','.join(x['name'] for x in d.get('datasets', []))} "
                  f"errors={','.join(r.get('errors', []))}")
        return 0
    save(path, list(rows.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
