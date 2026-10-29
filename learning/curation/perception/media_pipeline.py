"""Disk stage in front of a learning job.

Usage: media_pipeline.py [--root data/perception] [--video-dir data/teleop/learning]
                         [--out receipt.json] [--shrink] [--apply]

Stages, in order: scan, video, verify, reclaim, receipt.
scan reads both raw layouts. video runs bag_to_video for a stem that has no
video yet. verify requires the mp4, sidecar, meta and ffprobe count to agree.
reclaim deletes those raw directories only with --apply. A verified video also
removes its .compact sibling; a compact that is the only remaining bag stays.
receipt is rosy.learning.media/1. trainer_recordings() turns each checked video
into one recording-job row {"session", "video"}. A compact bag is not a
training input.

Each receipt session row also counts the sidecar's shadow evidence:
sidecar_rows (non-empty lines), shadow_live_rows (a dict payload recorded on
the robot, backfill flag absent or false) and shadow_backfill_rows (a payload
marked "backfill": true by an offline re-run). A session with shadow_live_rows
0 was recorded without the shadow model loaded — it is still trainable, but it
carries no model-disagreement signal until backfilled. All three are null when
the sidecar is absent.

Does not harvest, label, train, or delete the robot copy. recording_job still
does not delete raw: run this stage first, then point that job at the receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import reclaim

SCHEMA = "rosy.learning.media/1"
STAGES = ("scan", "video", "verify", "reclaim", "receipt")
READY = frozenset({"ok", "compact_ok"})
SHADOW_KEY = "perception/learned/shadow"


def shadow_evidence(sidecar: Path) -> dict:
    """Count shadow payloads in a bag_to_video sidecar, live vs backfilled.

    Rows whose side[SHADOW_KEY] is a dict carry evidence; the offline backfill
    tool marks its payloads with "backfill": true. Malformed lines count as
    rows with no payload: the verify stage, not this counter, decides whether
    the sidecar is trustworthy."""
    counts = {"sidecar_rows": 0, "shadow_live_rows": 0, "shadow_backfill_rows": 0}
    with open(sidecar, encoding="utf-8") as rows:
        for line in rows:
            if not line.strip():
                continue
            counts["sidecar_rows"] += 1
            try:
                side = (json.loads(line).get("side") or {})
            except json.JSONDecodeError:
                continue
            payload = side.get(SHADOW_KEY)
            if not isinstance(payload, dict):
                continue
            if payload.get("backfill") is True:
                counts["shadow_backfill_rows"] += 1
            else:
                counts["shadow_live_rows"] += 1
    return counts


def trainer_recordings(doc: dict) -> list[dict]:
    """One video row per session name. Two raw copies of one session count once."""
    if doc.get("schema") != SCHEMA:
        raise ValueError("media receipt schema")
    rows = []
    seen = set()
    for item in doc.get("sessions") or []:
        if not item.get("trainable") or item["session"] in seen:
            continue
        seen.add(item["session"])
        rows.append({"session": item["session"], "video": item["video"]})
    return rows


def build_receipt(rows: list[dict], video_dir: Path, *, applied: bool,
                  removed: list[Path], compacts: list[Path] | None = None) -> dict:
    removed_paths = {path.resolve() for path in removed}
    sessions = []
    for row in rows:
        raw = Path(row["path"])
        video = video_dir / f"{row['stem']}.mp4" if row["stem"] else None
        trainable = row["status"] == "ok" and video is not None and video.is_file()
        sibling = reclaim.compact_sibling(raw)
        if sibling.resolve() in removed_paths:
            compact_state = "removed"
        elif sibling.is_dir():
            compact_state = "kept"
        else:
            compact_state = "absent"
        sidecar = video_dir / f"{row['stem']}.jsonl" if row["stem"] else None
        counts = (shadow_evidence(sidecar)
                  if sidecar is not None and sidecar.is_file() else None)
        sessions.append({
            "session": raw.name,
            "stem": row["stem"],
            "status": row["status"],
            "raw": str(raw),
            "raw_bytes": row["bytes"],
            "raw_state": "removed" if raw.resolve() in removed_paths else "kept",
            "compact_state": compact_state,
            "video": str(video) if trainable else None,
            "trainable": trainable,
            **(counts or {"sidecar_rows": None, "shadow_live_rows": None,
                          "shadow_backfill_rows": None}),
        })
    compact_rows = []
    for path in compacts or []:
        compact_rows.append({
            "session": path.name[:-len(".compact")],
            "compact": str(path),
            "compact_state": "removed" if path.resolve() in removed_paths else "kept",
        })
    return {"schema": SCHEMA, "stages": list(STAGES), "applied": applied,
            "sessions": sessions, "compacts": compact_rows}


def write_receipt(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run(raw: Path, video_dir: Path, *, shrink: bool, apply: bool, probe, encode, compact) -> tuple[int, dict]:
    """Returns a process exit code and the receipt. A session that is not ready blocks a clean exit."""
    rows = reclaim.plan(reclaim.iter_sessions(raw), video_dir, probe)
    reclaim.encode_missing(rows, video_dir, encode)
    rows = reclaim.plan(reclaim.iter_sessions(raw), video_dir, probe)
    if shrink:
        reclaim.shrink_missing(rows, compact)
    removed: list[Path] = []
    applied = False
    refused = False
    compacts = reclaim.compacts_with_video(raw, video_dir, probe)
    if apply:
        try:
            removed = reclaim.delete_targets(rows, raw, compacts)
            applied = True
        except ValueError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            refused = True
    doc = build_receipt(rows, video_dir, applied=applied, removed=removed, compacts=compacts)
    blocked = refused or any(row["status"] not in READY for row in rows)
    return (1 if blocked else 0), doc


def main(argv=None, probe=None, encode=None, compact=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(reclaim.DEFAULT_ROOT))
    ap.add_argument("--video-dir", default=str(reclaim.DEFAULT_VIDEO))
    ap.add_argument("--out", help="write the rosy.learning.media/1 receipt here")
    ap.add_argument("--shrink", action="store_true",
                    help="compact a session that still has no video")
    ap.add_argument("--apply", action="store_true",
                    help="delete raw directories whose video or compact checked out")
    args = ap.parse_args(argv)
    code, doc = run(Path(args.root) / "raw", Path(args.video_dir), shrink=args.shrink,
                    apply=args.apply,
                    probe=reclaim.bag_to_video.count_frames if probe is None else probe,
                    encode=reclaim._encode if encode is None else encode,
                    compact=reclaim._compact if compact is None else compact)
    trainable = trainer_recordings(doc)
    print(f"media {doc['schema']} stages={','.join(doc['stages'])} "
          f"trainable={len(trainable)} applied={str(doc['applied']).lower()}")
    if args.out:
        write_receipt(Path(args.out), doc)
        print(f"receipt {args.out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
